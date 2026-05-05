"""Mensagens conversacionais.

`IncomingMessage` é o que um canal emite ao Gateway. `OutgoingMessage` é o que
o Gateway manda de volta. Todo campo "quem" já carrega `tenant_id` + `user_id`
canônicos — a resolução de identidade acontece dentro do adapter (via
`tenancy.resolver`), antes de construir a mensagem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from imkt5.types.tenants import ChannelKind


class AttachmentKind(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    VOICE = "voice"


@dataclass(frozen=True, slots=True)
class MessageAttachment:
    kind: AttachmentKind
    # Caminho em object storage (S3/MinIO). Canais baixam para cá antes de
    # emitir a mensagem — o agente nunca lida com URLs do transporte.
    storage_path: str
    mime_type: str | None = None
    size_bytes: int | None = None
    original_filename: str | None = None


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """Mensagem recebida, já resolvida para identidade canônica."""

    tenant_id: str
    user_id: str
    channel: ChannelKind
    # Identidade no transporte (ex.: telegram chat_id). Útil pra o adapter
    # responder. Nunca usar como chave de domínio.
    channel_external_id: str
    text: str
    attachments: tuple[MessageAttachment, ...] = ()
    received_at: datetime = field(default_factory=datetime.utcnow)
    # Correlação opcional: se a mensagem é resposta a um job em andamento.
    in_reply_to_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """Mensagem a ser entregue por um canal."""

    tenant_id: str
    user_id: str
    channel: ChannelKind
    channel_external_id: str
    text: str
    attachments: tuple[MessageAttachment, ...] = ()
    # Progresso parcial de um job — canais podem renderizar como typing
    # indicator, edição de mensagem anterior, etc.
    is_progress_update: bool = False
