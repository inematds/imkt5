"""skyreels-adapter worker.

Capability: `video.skyreels_queue`. Porta 8120.

Proxy fino que traduz o contrato `/execute` do imkt5 pra webui do SkyReels V3
(default em `:7861`). Fluxo:

  1. POST /nqueues/import      (com queue_json + project)                 → nq_id
  2. POST /nqueues/<id>/run    (com callback_url apontando pra este adapter)
  3. aguarda callback HTTP no próprio adapter (asyncio.Event por nq_id)
  4. opcional: POST /nqueues/<id>/finalize pra gerar mp4 concatenado
  5. devolve {external_id, output_videos, finalized_video, duration_s}

Rationale: o plano original propõe um endpoint novo no gateway imkt5 (`POST
/queue-callback/<job_id>`), mas consolidar callback no próprio adapter evita
acoplamento, mantém o gateway agnóstico a esse worker e respeita o
princípio #4 do CLAUDE.md (adapters são finos).

Variáveis de ambiente:
  SKYREELS_URL                — URL do webui skyreelsv3 (default http://localhost:7861)
  SKYREELS_ADAPTER_PUBLIC_URL — URL pública deste adapter (default http://localhost:8120)
                                 Usada como base pro callback_url. Se o
                                 skyreelsv3 roda em outra máquina, precisa
                                 ser reachable de lá.
  SKYREELS_ADAPTER_PORT       — porta pra bind (default 8120)

Input payload (de /execute):
  {
    "queue_json":    [ ... cenas do script-to-queue ... ],
    "queue_name":    "..." | "imkt5-<job_id[:8]>",
    "project":       "INETUSX" | "",
    "auto_finalize": true | false (default true),
    "timeout_s":     int (default 3600 = 1h)
  }

Output (de /execute, síncrono — bloqueia até callback do skyreelsv3):
  {
    "external_id":     <nq_id>,
    "upstream_url":    "http://.../nqueues/<id>",
    "output_videos":   [ "result/.../cena_01.mp4", ... ],
    "finalized_video": "result/<project>/finalized/<name>_<ts>.mp4" | null,
    "failed_jobs":     [],
    "duration_s":      123.4,
    "status":          "done"
  }

Se a queue falhar (status=error no callback), lança RuntimeError com
resumo dos failed_jobs — BaseWorker transforma em HTTP 500 pro gateway.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.parse import quote_plus

import httpx

from workers._base import BaseWorker

DEFAULT_UPSTREAM = "http://localhost:7861"
DEFAULT_PUBLIC = "http://localhost:8120"
DEFAULT_TIMEOUT = 3600  # 1h — queue grande (15-30 cenas) pode passar disso


class SkyReelsAdapterWorker(BaseWorker):
    name = "skyreels-adapter"
    capabilities = ("video.skyreels_queue",)

    def __init__(self) -> None:
        # nq_id -> {"event": asyncio.Event, "payload": dict | None}
        self._pending: dict[int, dict[str, Any]] = {}
        self._pending_lock = asyncio.Lock()

    # ── HTTP app: registra também a rota de callback ──────────────────
    def create_app(self) -> Any:
        from fastapi import Body, HTTPException

        app = super().create_app()

        @app.post("/queue-callback/{nq_id}")
        async def queue_callback(
            nq_id: int, body: dict[str, Any] = Body(...),
        ) -> dict[str, Any]:
            """Recebe webhook do skyreelsv3 quando a queue termina (done ou
            error). Libera o asyncio.Event que o handle() aguarda."""
            async with self._pending_lock:
                pending = self._pending.get(nq_id)
            if not pending:
                # Pode ser retry tardio ou nq_id desconhecido — ack sem erro
                print(f"[adapter] callback para nq_id={nq_id} desconhecido; ignorado")
                return {"ok": True, "known": False}
            pending["payload"] = body
            pending["event"].set()
            return {"ok": True, "known": True}

        return app

    # ── Worker logic ──────────────────────────────────────────────────
    async def handle(self, job) -> dict[str, Any]:
        payload = job.payload
        queue_json = payload.get("queue_json")
        if not queue_json or not isinstance(queue_json, list):
            raise ValueError("queue_json vazio ou não é lista")

        project = (payload.get("project") or "").strip()
        queue_name = (payload.get("queue_name") or "").strip()
        if not queue_name:
            queue_name = f"imkt5-{job.job_id[:8]}"
        auto_finalize = bool(payload.get("auto_finalize", True))
        timeout_s = int(payload.get("timeout_s") or DEFAULT_TIMEOUT)

        upstream = os.environ.get("SKYREELS_URL", DEFAULT_UPSTREAM).rstrip("/")
        public = os.environ.get("SKYREELS_ADAPTER_PUBLIC_URL", DEFAULT_PUBLIC).rstrip("/")

        # 1) importar queue
        import_url = (
            f"{upstream}/nqueues/import"
            f"?name={quote_plus(queue_name)}"
            f"&project={quote_plus(project)}"
        )
        body_str = json.dumps(queue_json, ensure_ascii=False)
        async with httpx.AsyncClient(timeout=600.0) as c:
            r = await c.post(
                import_url,
                content=body_str.encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            if r.status_code >= 400:
                raise RuntimeError(
                    f"/nqueues/import falhou ({r.status_code}): {r.text[:300]}"
                )
            data = r.json()
        nq_id = int(data["id"])
        job_count = int(data.get("job_count", len(queue_json)))
        print(f"[adapter] queue importada: nq_id={nq_id}, jobs={job_count}")

        # 2) registrar Event antes do run pra não perder callback race
        event = asyncio.Event()
        async with self._pending_lock:
            self._pending[nq_id] = {"event": event, "payload": None}

        try:
            # 3) rodar a queue com callback apontando pra este adapter
            callback_url = f"{public}/queue-callback/{nq_id}"
            run_url = (
                f"{upstream}/nqueues/{nq_id}/run"
                f"?callback_url={quote_plus(callback_url)}"
            )
            async with httpx.AsyncClient(timeout=600.0) as c:
                r = await c.post(run_url)
                if r.status_code >= 400:
                    raise RuntimeError(
                        f"/nqueues/{nq_id}/run falhou ({r.status_code}): {r.text[:300]}"
                    )
            print(f"[adapter] queue {nq_id} disparada; aguardando callback em {callback_url}")

            # 4) aguardar callback (OU timeout)
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout_s)
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    f"timeout aguardando skyreelsv3 (nq_id={nq_id}, {timeout_s}s)"
                ) from exc

            async with self._pending_lock:
                cb_payload = self._pending[nq_id]["payload"] or {}

            cb_status = cb_payload.get("status") or "unknown"
            output_videos = cb_payload.get("output_videos") or []
            failed_jobs = cb_payload.get("failed_jobs") or []
            duration_s = cb_payload.get("duration_s")

            # 5) finalize (auto-concat) se pediram
            finalized_video: str | None = None
            if auto_finalize and cb_status == "done" and output_videos:
                try:
                    async with httpx.AsyncClient(timeout=900.0) as c:
                        r = await c.post(f"{upstream}/nqueues/{nq_id}/finalize")
                        if r.status_code == 200:
                            finalized_video = r.json().get("output_video") or None
                        else:
                            print(
                                f"[adapter] finalize nq_id={nq_id} devolveu "
                                f"{r.status_code}: {r.text[:200]}"
                            )
                except Exception as exc:  # noqa: BLE001
                    print(f"[adapter] finalize falhou: {exc}")

            def _to_url(path: str | None) -> str | None:
                if not path or not isinstance(path, str):
                    return path
                if path.startswith(("http://", "https://", "/")):
                    return path
                return f"{upstream}/video/{path}"

            result = {
                "external_id": nq_id,
                "upstream_url": f"{upstream}/nqueues/{nq_id}",
                "status": cb_status,
                "output_videos": [_to_url(p) for p in output_videos],
                "finalized_video": _to_url(finalized_video),
                "failed_jobs": failed_jobs,
                "duration_s": duration_s,
                "queue_name": queue_name,
                "project": project,
            }

            if cb_status == "error":
                # Levanta pro gateway reportar falha (BaseWorker transforma em 500)
                summary = ", ".join(
                    f"#{fj.get('index', '?')}:{fj.get('label', '')}"
                    for fj in failed_jobs
                )
                raise RuntimeError(
                    f"skyreelsv3 queue {nq_id} falhou (failed_jobs: {summary or 'desconhecido'})"
                )

            return result

        finally:
            async with self._pending_lock:
                self._pending.pop(nq_id, None)


if __name__ == "__main__":
    port = int(os.environ.get("SKYREELS_ADAPTER_PORT", 8120))
    SkyReelsAdapterWorker().run(port=port)
