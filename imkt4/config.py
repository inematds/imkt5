"""Configuração centralizada — 3 níveis.

Precedência (maior ganha):
  1. env var  (override por ambiente)
  2. user_prefs  (por usuário — via DB, pendente)
  3. tenant config  (profiles/<tenant_id>/config.yaml)
  4. global defaults  (config/defaults.yaml)
  5. fallback hardcoded no código (defensivo)

Uso:

    from imkt4.config import settings

    # global
    settings.gateway.port                           # 8080

    # nested
    settings.dispatcher.request_timeout_seconds     # 600
    settings.workers.inemaimg_adapter.default_model # qwen-edit-2511

    # scoped por tenant
    s = settings.for_tenant("demo")
    s.tenant.visual_style                           # "minimalist"
    s.capability_payload_defaults["image.generation"]["model"]  # pode ser
                                        # override do tenant se existir

Carregamento: `load()` na boot-up do main.py; cache singleton.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


GLOBAL_DEFAULTS_PATH = "config/defaults.yaml"
TENANT_PROFILES_ROOT = "profiles"
TENANT_CONFIG_FILENAME = "config.yaml"


# ── Helpers de leitura com env override ──────────────────────────────
def _env_override(env_key: str, value: Any) -> Any:
    v = os.environ.get(env_key)
    if v is None:
        return value
    # coerce pro mesmo tipo do default
    if isinstance(value, bool):
        return v.lower() in ("1", "true", "yes")
    if isinstance(value, int):
        try:
            return int(v)
        except ValueError:
            return value
    if isinstance(value, float):
        try:
            return float(v)
        except ValueError:
            return value
    return v


# ── Classes acessoras (namespace com attr-access) ───────────────────
class Namespace:
    """Wrapper simples de dict → attr access recursivo."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data or {}

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        if key not in self._data:
            raise AttributeError(f"config sem chave {key!r}")
        v = self._data[key]
        return Namespace(v) if isinstance(v, dict) else v

    def __getitem__(self, key: str) -> Any:
        v = self._data[key]
        return Namespace(v) if isinstance(v, dict) else v

    def get(self, key: str, default: Any = None) -> Any:
        v = self._data.get(key, default)
        if isinstance(v, dict):
            return Namespace(v)
        return v

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)


# ── Loaders ──────────────────────────────────────────────────────────
def _load_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text())
    return data or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge recursivo: override vence; dicts se combinam; valores se substituem."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _apply_env_overrides(data: dict[str, Any], env_map: dict[str, tuple[str, ...]]) -> None:
    """Aplica overrides de env vars no dict in-place.

    env_map: env_key -> path (tupla de chaves) no dict.
    """
    for env_key, path in env_map.items():
        if env_key not in os.environ:
            continue
        # desce no dict até o pai
        cur = data
        for seg in path[:-1]:
            cur = cur.setdefault(seg, {})
        last = path[-1]
        current_val = cur.get(last)
        cur[last] = _env_override(env_key, current_val)


# Mapa env → path no yaml (extensível conforme adicionamos chaves)
ENV_MAP: dict[str, tuple[str, ...]] = {
    # gateway
    "GATEWAY_HOST": ("gateway", "host"),
    "GATEWAY_PORT": ("gateway", "port"),
    # dispatcher
    "IMKT4_DISPATCH_TIMEOUT": ("dispatcher", "request_timeout_seconds"),
    "IMKT4_DISPATCH_RETRY_SECONDS": ("dispatcher", "retry_when_saturated_seconds"),
    "IMKT4_DISPATCH_MAX_PENDING": ("dispatcher", "max_pending_jobs"),
    "IMKT4_DISPATCH_MAX_RETRIES": ("dispatcher", "max_select_retries"),
    # registry
    "IMKT4_PROBE_TIMEOUT": ("capability_registry", "probe_timeout_seconds"),
    # jobs store
    "IMKT4_JOBS_HISTORY": ("jobs_store", "max_history"),
    # approvals
    "IMKT4_APPROVAL_TIMEOUT": ("approvals", "default_timeout_seconds"),
    # storage
    "IMKT4_ARTIFACT_ROOT": ("storage", "artifact_root"),
    # memory
    "MEMORY_DB_PATH": ("memory", "db_path"),
    # llm
    "OPENROUTER_BASE_URL": ("llm", "openrouter", "base_url"),
    "OPENROUTER_MODEL_DEFAULT": ("llm", "openrouter", "default_model"),
    "OLLAMA_URL": ("llm", "ollama", "url"),
    "OLLAMA_MODEL": ("llm", "ollama", "chat_model"),
    "OLLAMA_ROUTER_MODEL": ("llm", "ollama", "router_model"),
    # workers
    "RESEARCH_PORT": ("workers", "research", "port"),
    "AUTO_REVIEWER_PORT": ("workers", "auto_reviewer", "port"),
    "IMKT4_INEMAIMG_ADAPTER_PORT": ("workers", "inemaimg_adapter", "port"),
    "INEMAIMG_URL": ("workers", "inemaimg_adapter", "upstream_url"),
    "INEMAIMG_MODEL": ("workers", "inemaimg_adapter", "default_model"),
    "INEMAIMG_TIMEOUT": ("workers", "inemaimg_adapter", "request_timeout_seconds"),
    "IMKT4_INEMAVOX_ADAPTER_PORT": ("workers", "inemavox_adapter", "port"),
    "INEMAVOX_URL": ("workers", "inemavox_adapter", "upstream_url"),
    "INEMAVOX_POLL_INTERVAL": ("workers", "inemavox_adapter", "poll_interval_seconds"),
    "INEMAVOX_POLL_MAX_SECONDS": ("workers", "inemavox_adapter", "poll_max_seconds"),
}


# ── Settings públicos ────────────────────────────────────────────────
class Settings:
    """Acessor de config. Instanciar uma vez via `load()`.

    Métodos:
      - `settings.gateway.port`            — atributos do global
      - `settings.for_tenant("abc")`       — Settings com overrides do tenant
      - `settings.as_dict()`               — snapshot serializável
    """

    def __init__(self, merged: dict[str, Any], tenant_id: str | None = None) -> None:
        self._merged = merged
        self._tenant_id = tenant_id

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        if key not in self._merged:
            raise AttributeError(f"settings sem chave {key!r}")
        v = self._merged[key]
        return Namespace(v) if isinstance(v, dict) else v

    def for_tenant(self, tenant_id: str) -> "Settings":
        """Carrega o config do tenant e retorna um Settings novo com
        overrides aplicados (tenant vence sobre global)."""
        tenant_cfg = _load_yaml(
            Path(TENANT_PROFILES_ROOT) / tenant_id / TENANT_CONFIG_FILENAME
        )
        if not tenant_cfg:
            return Settings(self._merged, tenant_id=tenant_id)
        merged = _deep_merge(self._merged, tenant_cfg)
        # env vars têm precedência sobre tudo, aplicar de novo
        _apply_env_overrides(merged, ENV_MAP)
        return Settings(merged, tenant_id=tenant_id)

    @property
    def tenant_id(self) -> str | None:
        return self._tenant_id

    def as_dict(self) -> dict[str, Any]:
        import copy
        return copy.deepcopy(self._merged)


# ── API de carga ─────────────────────────────────────────────────────
_settings_cache: Settings | None = None


def load(
    defaults_path: str | Path = GLOBAL_DEFAULTS_PATH,
    *,
    force: bool = False,
) -> Settings:
    """Carrega defaults.yaml + aplica env overrides. Singleton cached."""
    global _settings_cache
    if _settings_cache is not None and not force:
        return _settings_cache
    base = _load_yaml(defaults_path)
    _apply_env_overrides(base, ENV_MAP)
    _settings_cache = Settings(base)
    return _settings_cache


def settings() -> Settings:
    """Pega o singleton. Carrega se ainda não carregado."""
    return _settings_cache or load()


# ── Acesso "mágico" via módulo (imkt4.config.settings.gateway.port) ─
# Permite `from imkt4.config import settings` como atalho equivalente a
# `from imkt4.config import settings as _get; settings = _get()`.
# Resolvido via __getattr__ de módulo (PEP 562).
def __getattr__(name: str) -> Any:
    if name == "settings":
        return load()
    raise AttributeError(name)
