"""Helper de storage compartilhado entre workers.

Backends:
- LocalStorage (default): salva em disco sob ./data/artifacts/,
  devolve file:// (o gateway converte pra /artifacts/ quando serve).
- S3Storage: S3/MinIO-compatible. Ativado via IMKT4_STORAGE=s3 +
  env S3_ENDPOINT/S3_BUCKET/S3_ACCESS_KEY/S3_SECRET_KEY.

Escolha automática via env IMKT4_STORAGE (local|s3).
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Literal, Protocol

log = logging.getLogger("imkt4.storage")


Kind = Literal["image", "audio", "video", "document"]


class Storage(Protocol):
    def save_bytes(
        self, *, tenant_id: str, job_id: str, filename: str, data: bytes,
    ) -> str: ...

    def save_base64(
        self, *, tenant_id: str, job_id: str, filename: str, b64: str,
    ) -> str: ...


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
            tenant_id=tenant_id, job_id=job_id, filename=filename,
            data=base64.b64decode(b64),
        )


class S3Storage:
    """S3/MinIO-compatible. URL pública via `presigned_url`."""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        public_base: str | None = None,
        secure: bool = False,
        presign_ttl: int = 3600 * 24,
    ) -> None:
        import boto3
        self._bucket = bucket
        self._presign_ttl = presign_ttl
        self._public_base = public_base
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            use_ssl=secure,
        )
        # ensure bucket exists (idempotente)
        try:
            self._client.head_bucket(Bucket=bucket)
        except Exception:
            try:
                self._client.create_bucket(Bucket=bucket)
            except Exception as exc:  # noqa: BLE001
                log.warning("S3 create_bucket falhou: %s", exc)

    def save_bytes(
        self,
        *,
        tenant_id: str,
        job_id: str,
        filename: str,
        data: bytes,
    ) -> str:
        key = f"{tenant_id}/{job_id}/{filename}"
        import mimetypes
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=ctype,
        )
        # Devolve path relativo `/s3/<bucket>/<key>` — o gateway faz
        # streaming proxy pro MinIO interno. Garante que a URL funciona
        # de qualquer máquina que acessa o gateway, sem depender de
        # hostname do S3_ENDPOINT.
        #
        # Se S3_PUBLIC_BASE estiver setado (bucket público direto da
        # internet), devolve URL direta em vez do proxy.
        if self._public_base:
            return f"{self._public_base.rstrip('/')}/{self._bucket}/{key}"
        return f"/s3/{self._bucket}/{key}"

    def save_base64(
        self,
        *,
        tenant_id: str,
        job_id: str,
        filename: str,
        b64: str,
    ) -> str:
        return self.save_bytes(
            tenant_id=tenant_id, job_id=job_id, filename=filename,
            data=base64.b64decode(b64),
        )


def get_storage() -> Storage:
    backend = os.environ.get("IMKT4_STORAGE", "local").lower()
    if backend == "s3":
        try:
            return S3Storage(
                endpoint=os.environ["S3_ENDPOINT"],
                bucket=os.environ.get("S3_BUCKET", "imkt4-artifacts"),
                access_key=os.environ["S3_ACCESS_KEY"],
                secret_key=os.environ["S3_SECRET_KEY"],
                region=os.environ.get("S3_REGION", "us-east-1"),
                public_base=os.environ.get("S3_PUBLIC_BASE") or None,
            )
        except KeyError as exc:
            log.warning("S3 mal configurado (%s) — caindo pra local", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("S3 init falhou: %s — caindo pra local", exc)
    return LocalStorage()
