"""HttpDispatcher — despacha jobs para workers via HTTP.

Faz a ponte entre o Recipe Runner (in-process, async) e os workers
(serviços HTTP separados). Para cada job:

1. Resolve worker via `select_worker(registry, job.required_capability)`
   ou `worker_type` direto.
2. POST `{endpoint}/execute` com payload do Job.
3. Atualiza `in_flight` no registry (acquire/release).
4. Notifica callback de fim de job (success/failure).

Quando todas as instâncias estão saturadas, o dispatcher segura o job
em uma fila local e tenta de novo quando alguma libera (ou pode ser
configurado pra rejeitar imediatamente — útil pra back-pressure).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any, Awaitable, Callable

import httpx

from imkt4.capabilities.matcher import NoWorkerAvailable, select_worker
from imkt4.capabilities.registry import CapabilityRegistry
from imkt4.types.jobs import Job

log = logging.getLogger("imkt4.dispatcher")

OnFinishCallback = Callable[[str, bool, dict[str, Any] | None, str | None], Awaitable[None]]


class HttpDispatcher:
    """Dispatcher que roteia jobs para workers HTTP."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        request_timeout: float | None = None,
        retry_when_saturated_seconds: float | None = None,
        max_pending: int | None = None,
        max_select_retries: int | None = None,
        jobs_store: Any | None = None,
        channel_notifier: Any | None = None,
    ) -> None:
        from imkt4.config import load
        cfg = load().dispatcher
        self._registry = registry
        self._timeout = request_timeout if request_timeout is not None else cfg.request_timeout_seconds
        self._retry_seconds = (
            retry_when_saturated_seconds
            if retry_when_saturated_seconds is not None
            else cfg.retry_when_saturated_seconds
        )
        self._max_select_retries = (
            max_select_retries if max_select_retries is not None else cfg.max_select_retries
        )
        _max_pending = max_pending if max_pending is not None else cfg.max_pending_jobs
        self._on_finish: OnFinishCallback | None = None
        self._pending: asyncio.Queue[Job] = asyncio.Queue(maxsize=_max_pending)
        self._consumer_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._jobs_store = jobs_store
        self._notifier = channel_notifier

    def set_on_finish(self, cb: OnFinishCallback) -> None:
        self._on_finish = cb

    async def dispatch(self, job: Job) -> None:
        """Enfileira pra processamento. Retorna imediatamente."""
        # Se job ainda não está no store (quick-dispatch via tool LLM em vez
        # de via rota HTTP), cria agora pra ser rastreável.
        if self._jobs_store and await self._jobs_store.get(job.job_id) is None:
            await self._jobs_store.create(
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                user_id=job.user_id,
                capability=job.required_capability,
                worker_type=job.worker_type,
            )
        await self._pending.put(job)

    async def start(self) -> None:
        if self._consumer_task and not self._consumer_task.done():
            return
        self._stopping = False
        self._consumer_task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        self._stopping = True
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

    async def drain(self) -> None:
        await self._pending.join()

    # ── interno ───────────────────────────────────────────────────────
    async def _consume(self) -> None:
        while not self._stopping:
            job = await self._pending.get()
            asyncio.create_task(self._process_one(job))

    async def _process_one(self, job: Job) -> None:
        try:
            worker = await self._select_with_retry(job)
        except Exception as exc:  # noqa: BLE001
            log.warning("job %s: select falhou (%s)", job.job_id, exc)
            await self._notify(job.job_id, False, None, f"select: {exc}")
            self._pending.task_done()
            return

        log.info(
            "job %s → worker=%s capability=%s",
            job.job_id, worker.name, job.required_capability or job.worker_type,
        )
        if self._jobs_store:
            await self._jobs_store.mark_running(job.job_id, worker.name)
        await self._registry.acquire(worker.name)
        try:
            output = await self._call_worker(worker, job)
            log.info("job %s ✓ worker=%s", job.job_id, worker.name)
            if self._jobs_store:
                await self._jobs_store.mark_finished(
                    job.job_id, success=True, output=output, error=None,
                )
            await self._notify(job.job_id, True, output, None)
            await self._deliver_to_channel(job, output, None)
        except Exception as exc:  # noqa: BLE001
            err_str = f"worker={worker.name} err={type(exc).__name__}: {exc}"
            log.warning("job %s ✗ worker=%s err=%s", job.job_id, worker.name, exc)
            if self._jobs_store:
                await self._jobs_store.mark_finished(
                    job.job_id, success=False, output=None, error=err_str,
                )
            await self._notify(job.job_id, False, None, err_str)
            await self._deliver_to_channel(job, None, err_str)
        finally:
            await self._registry.release(worker.name)
            self._pending.task_done()

    async def _deliver_to_channel(self, job: Job, output, error) -> None:
        """Notifica o canal de origem do job (Telegram/WA) com o resultado."""
        # Stage de receita: runner já entrega no fim — pula intermediários.
        if job.parent_job_id:
            log.info("delivery: job %s é stage de receita (parent=%s); skip",
                     job.job_id, job.parent_job_id)
            return
        if self._notifier is None:
            log.info("delivery: notifier não configurado pro job %s", job.job_id)
            return
        log.info(
            "delivery: tentando entregar job %s no canal '%s' chat='%s'",
            job.job_id, job.origin_channel, job.origin_channel_external_id,
        )
        try:
            await self._notifier.deliver(
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                user_id=job.user_id,
                origin_channel=job.origin_channel,
                origin_external_id=job.origin_channel_external_id,
                output=output,
                error=error,
            )
            log.info("delivery: job %s entregue", job.job_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("delivery falhou pro job %s: %s", job.job_id, exc)

    async def _select_with_retry(self, job):
        # Se saturado, espera um tick e tenta de novo.
        for attempt in range(self._max_select_retries):
            try:
                if job.worker_type:
                    return self._registry.get_worker(job.worker_type)
                if not job.required_capability:
                    raise ValueError("job sem worker_type nem required_capability")
                return select_worker(self._registry, job.required_capability)
            except NoWorkerAvailable:
                await asyncio.sleep(self._retry_seconds)
        # Última tentativa, sem retry
        if job.worker_type:
            return self._registry.get_worker(job.worker_type)
        return select_worker(self._registry, job.required_capability)

    async def _call_worker(self, worker, job: Job) -> dict[str, Any]:
        body = _job_to_request(job)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{worker.endpoint.rstrip('/')}/execute", json=body
            )
            if r.status_code != 200:
                # Extrai a mensagem real do worker em vez de propagar o
                # genérico "Server error '500'" do httpx.raise_for_status.
                detail = ""
                try:
                    j = r.json()
                    d = j.get("detail")
                    if isinstance(d, dict):
                        detail = d.get("error") or str(d)
                    elif isinstance(d, str):
                        detail = d
                    else:
                        detail = json.dumps(j)[:500]
                except Exception:  # noqa: BLE001
                    detail = (r.text or "")[:500] or "(corpo vazio)"
                raise RuntimeError(
                    f"{worker.name} HTTP {r.status_code}: {detail}"
                )
            data = r.json()
        return data.get("output", {})

    async def _notify(
        self,
        job_id: str,
        success: bool,
        output: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        if self._on_finish:
            await self._on_finish(job_id, success, output, error)


def _job_to_request(job: Job) -> dict[str, Any]:
    """Serializa Job para o shape do BaseWorker.execute."""
    return {
        "job_id": job.job_id,
        "tenant_id": job.tenant_id,
        "user_id": job.user_id,
        "worker_type": job.worker_type,
        "required_capability": job.required_capability,
        "payload": job.payload,
        "origin_channel": job.origin_channel,
        "origin_channel_external_id": job.origin_channel_external_id,
    }
