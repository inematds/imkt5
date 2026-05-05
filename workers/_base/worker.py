"""Base HTTP worker — utility compartilhada.

Cada worker concreto herda e implementa `handle()`. O base cuida de:
- servidor FastAPI mínimo
- endpoint /health
- endpoint /execute (Job → JobResult)
- parsing dos tipos canônicos
- captura de exceção com status FAILED

Uso:

    class MeuWorker(BaseWorker):
        name = "inemaimg-adapter"
        capabilities = ("image.generation",)

        async def handle(self, job: Job) -> dict[str, Any]:
            ...  # faz o trabalho, retorna dict que vai no JobResult.output

    if __name__ == "__main__":
        MeuWorker().run(host="0.0.0.0", port=8010)
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import Any

# Adiciona raiz do imkt5 ao path pra worker importar os tipos canônicos
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from imkt5.types.jobs import Job, JobResult, JobStatus  # noqa: E402


class BaseWorker(ABC):
    name: str = ""
    capabilities: tuple[str, ...] = ()

    @abstractmethod
    async def handle(self, job: Job) -> dict[str, Any]:
        """Executa o trabalho. Retorna dict que vai pro JobResult.output."""

    # ── HTTP server ───────────────────────────────────────────────────
    def create_app(self) -> Any:
        from fastapi import Body, FastAPI, HTTPException

        app = FastAPI(title=self.name or "imkt5 worker")

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {
                "status": "ok",
                "name": self.name,
                "capabilities": list(self.capabilities),
            }

        @app.post("/execute")
        async def execute(req: dict[str, Any] = Body(...)) -> dict[str, Any]:
            job = Job(
                job_id=req["job_id"],
                tenant_id=req["tenant_id"],
                user_id=req["user_id"],
                worker_type=req.get("worker_type"),
                required_capability=req.get("required_capability"),
                payload=req.get("payload", {}),
                origin_channel=req.get("origin_channel", ""),
                origin_channel_external_id=req.get("origin_channel_external_id", ""),
            )
            try:
                output = await self.handle(job)
                result = JobResult(
                    job_id=job.job_id,
                    tenant_id=job.tenant_id,
                    status=JobStatus.SUCCESS,
                    output=output,
                    progress=1.0,
                )
                return _result_to_dict(result)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    500,
                    detail={
                        "error": f"{type(exc).__name__}: {exc}",
                        "job_id": job.job_id,
                    },
                ) from exc

        return app

    def run(self, *, host: str = "0.0.0.0", port: int) -> None:
        import uvicorn

        uvicorn.run(self.create_app(), host=host, port=port)


def _result_to_dict(r: JobResult) -> dict[str, Any]:
    d = asdict(r)
    d["status"] = r.status.value
    return d
