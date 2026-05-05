"""Identidade no imkt5.

- `Tenant`: unidade de isolamento de dados e configuração. Um tenant pode ter
  vários usuários (ex.: uma empresa) ou um só (ex.: pessoa física).
- `User`: pessoa. Pode ser alcançável por vários canais — cada canal vira um
  `ChannelBinding`.
- `ChannelBinding`: mapeia a identidade no transporte (telegram_id, whatsapp
  phone, web user id) para o `user_id` canônico.

Chave de projeto: NADA no sistema é single-user. `tenant_id` está em toda
assinatura e toda linha persistida.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ChannelKind(str, Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    WEB = "web"


@dataclass(frozen=True, slots=True)
class Tenant:
    tenant_id: str
    name: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    # Caminho do stack de identidade (SOUL.md, AGENTS.md, USER.md, MEMORY.md).
    # Convenção: `profiles/{tenant_id}/`.
    profile_path: str = ""


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    tenant_id: str
    display_name: str
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True, slots=True)
class ChannelBinding:
    """Liga uma identidade-de-transporte a um user_id canônico.

    Exemplos de `external_id`:
      - Telegram: o `chat_id` (int como string)
      - WhatsApp: o telefone com DDI (ex.: `5511999999999`)
      - Web: o user id do login
    """

    user_id: str
    tenant_id: str
    channel: ChannelKind
    external_id: str
    verified_at: datetime | None = None
