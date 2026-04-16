"""Wrapper de fila.

Duas implementações:

- `InMemoryDispatcher`: sem dependências externas. Usado em testes
  unitários e e2e do runner de receitas.
- `RedisJobQueue`: baseado em Redis (lista simples por worker_type ou
  capability). Evita acoplar RQ porque queremos async-first; o contrato
  interno é o `JobDispatcher` do runner.

Ambas são stateless em relação ao job: só publicam/consomem. O estado
persistente (status, outputs) vive em Postgres em produção; no scaffold
atual, fica em memória.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import asdict
from typing import Any, Awaitable, Callable

from imkt4.types.jobs import Job


JobHandler = Callable[[Job], Awaitable[dict[str, Any]]]


class InMemoryDispatcher:
    """Dispatcher in-process para testes e cenários single-node.

    Executa handlers registrados por `worker_type` ou `required_capability`.
    Útil pra validar o Recipe Runner sem subir Redis.
    """

    def __init__(self) -> None:
        self._by_worker: dict[str, JobHandler] = {}
        self._by_capability: dict[str, JobHandler] = {}
        self._on_finish: Callable[[str, bool, dict[str, Any] | None, str | None], Awaitable[None]] | None = None
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    def register_worker(self, worker_type: str, handler: JobHandler) -> None:
        self._by_worker[worker_type] = handler

    def register_capability(self, capability: str, handler: JobHandler) -> None:
        self._by_capability[capability] = handler

    def set_on_finish(
        self,
        cb: Callable[[str, bool, dict[str, Any] | None, str | None], Awaitable[None]],
    ) -> None:
        self._on_finish = cb

    async def dispatch(self, job: Job) -> None:
        await self._queue.put(job)

    async def start(self) -> None:
        """Começa a consumir a fila em background."""
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def drain(self) -> None:
        """Processa tudo que estiver na fila e retorna quando vazia."""
        while not self._queue.empty():
            await asyncio.sleep(0)  # cede pro consumer
        # Aguarda o consumer realmente processar
        await self._queue.join()

    async def _consume(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                handler = self._resolve_handler(job)
                if handler is None:
                    raise LookupError(
                        f"sem handler pra worker_type={job.worker_type} "
                        f"capability={job.required_capability}"
                    )
                output = await handler(job)
                if self._on_finish:
                    await self._on_finish(job.job_id, True, output, None)
            except Exception as exc:  # noqa: BLE001
                if self._on_finish:
                    await self._on_finish(
                        job.job_id, False, None, f"{type(exc).__name__}: {exc}"
                    )
            finally:
                self._queue.task_done()

    def _resolve_handler(self, job: Job) -> JobHandler | None:
        if job.worker_type and job.worker_type in self._by_worker:
            return self._by_worker[job.worker_type]
        if job.required_capability and job.required_capability in self._by_capability:
            return self._by_capability[job.required_capability]
        return None


class JobQueue:
    """Fila baseada em Redis (lista por worker_type/capability).

    Implementação intencionalmente simples: LPUSH no enqueue, BRPOP no
    consume. Serialização JSON. Sem reenfileiramento automático — se
    precisar de retry/dead-letter, refatora pra RQ/Celery/Temporal.
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    @staticmethod
    def _queue_name(job: Job) -> str:
        if job.worker_type:
            return f"imkt4:jobs:worker:{job.worker_type}"
        return f"imkt4:jobs:capability:{job.required_capability}"

    async def enqueue(self, job: Job) -> None:
        payload = json.dumps(_serialize_job(job), default=str)
        await self._redis.lpush(self._queue_name(job), payload)

    async def dequeue(
        self, *, worker_types: list[str] | None = None, capabilities: list[str] | None = None,
        timeout: int = 0,
    ) -> Job | None:
        names = []
        for w in worker_types or []:
            names.append(f"imkt4:jobs:worker:{w}")
        for c in capabilities or []:
            names.append(f"imkt4:jobs:capability:{c}")
        if not names:
            return None
        result = await self._redis.brpop(names, timeout=timeout)
        if result is None:
            return None
        _, raw = result
        return _deserialize_job(json.loads(raw))


def _serialize_job(job: Job) -> dict[str, Any]:
    d = asdict(job)
    # Enums viram str
    d["priority"] = job.priority.value
    return d


def _deserialize_job(d: dict[str, Any]) -> Job:
    from imkt4.types.jobs import JobPriority as _P

    d["priority"] = _P(d["priority"])
    # datetime volta como str — deixamos como str aqui; uso downstream
    # lida. Se precisar datetime real, converter.
    return Job(**{k: v for k, v in d.items() if k in Job.__dataclass_fields__})
