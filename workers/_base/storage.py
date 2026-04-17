"""Helper de storage compartilhado entre workers.

Em dev local (sem MinIO/S3 rodando), salva em disco e devolve `file://`.
Em prod, substituir por cliente S3 real — interface igual.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Literal


Kind = Literal["image", "audio", "video", "document"]


class LocalStorage:
    """Salva em disco local sob ./data/artifacts/."""

    def __init__(self, root: str | Path | None = None) -> None:
        if root is None:
            try:
                from imkt4.config import load
                root = load().storage.artifact_root
            except Exception:  # noqa: BLE001
                root = os.environ.get("IMKT4_ARTIFACT_ROOT", "./data/artifacts")
        self._root = Path(root).resolve()

    def save_bytes(
        self,
        *,
        tenant_id: str,
        job_id: str,
        filename: str,
        data: bytes,
    ) -> str:
        """Salva bytes e devolve URI (file:// por enquanto)."""
        folder = self._root / tenant_id / job_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / filename
        path.write_bytes(data)
        return f"file://{path}"

    def save_base64(
        self,
        *,
        tenant_id: str,
        job_id: str,
        filename: str,
        b64: str,
    ) -> str:
        return self.save_bytes(
            tenant_id=tenant_id,
            job_id=job_id,
            filename=filename,
            data=base64.b64decode(b64),
        )


def get_storage() -> LocalStorage:
    """Single entrypoint; troca fácil pra S3/MinIO depois."""
    return LocalStorage()
