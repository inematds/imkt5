"""Bindings — origens e destinos configuráveis por tenant.

Substitui o modelo antigo do `yt-pub-lives*` (10 pastas clonadas, cada
uma com seu canal destino) por:

- `SourceBinding`: origem (ex.: canal YouTube do qual clipar lives).
- `PublishBinding`: destino (ex.: canal YouTube onde publicar clips,
  conta Instagram, etc.).

Ambos ficam em Postgres. Credenciais sensíveis (OAuth tokens, API keys)
ficam no KMS com `credentials_ref`; o binding carrega apenas a
referência.

Receitas varrem bindings com `fanout_over`. Um tenant com 2 origens e 3
destinos pode disparar 2 jobs de ingest e, por clip resultante, 3 jobs
de publish em paralelo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class BindingKind(str, Enum):
    """Kind da origem/destino — determina qual worker sabe atendê-lo."""

    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    THREADS = "threads"
    LINKEDIN = "linkedin"
    WEBHOOK = "webhook"


@dataclass(frozen=True, slots=True)
class SourceBinding:
    """Origem da qual o tenant pode ingerir conteúdo."""

    binding_id: str
    tenant_id: str
    kind: BindingKind
    external_id: str
    # Referência no KMS. Ex.: "secrets/tenant-abc/yt-source-xyz"
    credentials_ref: str
    label: str = ""
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True, slots=True)
class PublishBinding:
    """Destino para onde o tenant pode publicar."""

    binding_id: str
    tenant_id: str
    kind: BindingKind
    external_id: str
    credentials_ref: str
    label: str = ""
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
