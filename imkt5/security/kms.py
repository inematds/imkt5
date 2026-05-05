"""KMS — abstração pra resolver referências de credenciais.

Backends:
- `local` (default): secrets em `./data/secrets/<ref>.enc` cifrados com
  Fernet. Chave mestra em env `IMKT5_KMS_MASTER_KEY` (base64). Se ausente,
  gera e salva em `./data/secrets/master.key` (modo dev).
- `env`: secrets em variáveis de ambiente (`SECRET_<REF_UPPER>`). Não
  cifra — útil em CI/testes.
- `vault`: placeholder — futura integração com HashiCorp Vault.

Uso:
    from imkt5.security import get_kms
    kms = get_kms()
    await kms.put("tg-bot-inema", b"8600523764:...")
    value = await kms.get("tg-bot-inema")
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

log = logging.getLogger("imkt5.kms")


class KMS(Protocol):
    async def get(self, ref: str) -> bytes | None: ...
    async def put(self, ref: str, value: bytes) -> None: ...
    async def delete(self, ref: str) -> None: ...


class LocalKMS:
    """Fernet-encrypted file store. Boa pra dev; NÃO usar em produção
    compartilhada — chave mestra fica em disco junto dos secrets."""

    def __init__(self, root: str | Path | None = None, master_key: bytes | None = None) -> None:
        self._root = Path(root or os.environ.get("IMKT5_KMS_ROOT", "./data/secrets")).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._master = master_key or self._load_or_create_master()

    def _load_or_create_master(self) -> bytes:
        from cryptography.fernet import Fernet
        env_key = os.environ.get("IMKT5_KMS_MASTER_KEY")
        if env_key:
            return env_key.encode() if isinstance(env_key, str) else env_key
        key_file = self._root / "master.key"
        if key_file.exists():
            return key_file.read_bytes().strip()
        # gera nova — modo dev
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        os.chmod(key_file, 0o600)
        log.warning("LocalKMS: gerou master key em %s (dev only)", key_file)
        return key

    def _fernet(self):
        from cryptography.fernet import Fernet
        return Fernet(self._master)

    async def get(self, ref: str) -> bytes | None:
        path = self._root / f"{ref}.enc"
        if not path.exists():
            return None
        try:
            return self._fernet().decrypt(path.read_bytes())
        except Exception as exc:  # noqa: BLE001
            log.warning("KMS decrypt %s: %s", ref, exc)
            return None

    async def put(self, ref: str, value: bytes) -> None:
        path = self._root / f"{ref}.enc"
        path.write_bytes(self._fernet().encrypt(value))
        os.chmod(path, 0o600)

    async def delete(self, ref: str) -> None:
        path = self._root / f"{ref}.enc"
        if path.exists():
            path.unlink()


class EnvKMS:
    """Secrets em vars de ambiente. `ref` vira `SECRET_<REF_UPPER>`."""

    def _env_key(self, ref: str) -> str:
        return f"SECRET_{ref.upper().replace('-', '_').replace('.', '_')}"

    async def get(self, ref: str) -> bytes | None:
        v = os.environ.get(self._env_key(ref))
        return v.encode() if v else None

    async def put(self, ref: str, value: bytes) -> None:
        raise RuntimeError("EnvKMS é read-only — edite o .env")

    async def delete(self, ref: str) -> None:
        raise RuntimeError("EnvKMS é read-only")


def get_kms() -> KMS:
    backend = os.environ.get("KMS_PROVIDER", "local").lower()
    if backend == "env":
        return EnvKMS()
    # Placeholder: vault → cairia aqui. Por ora default pra local.
    return LocalKMS()
