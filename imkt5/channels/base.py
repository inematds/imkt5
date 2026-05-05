"""Contrato de canal.

Um canal é um adapter fino entre um transporte (Telegram, WhatsApp, Web) e o
Gateway. Responsabilidades:

1. Receber eventos do transporte.
2. Resolver a identidade-de-transporte em `(tenant_id, user_id)` canônicos
   via `tenancy.resolver` — o adapter NÃO inventa tenants.
3. Baixar anexos para object storage e construir `IncomingMessage`.
4. Invocar `on_message(incoming)` entregue pelo Gateway.
5. Enviar `OutgoingMessage` quando o Gateway pedir.

Um canal NÃO conhece o agent loop, nem memória, nem providers. Ele só traduz.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from imkt5.types.messages import IncomingMessage, OutgoingMessage
from imkt5.types.tenants import ChannelKind

OnMessage = Callable[[IncomingMessage], Awaitable[None]]


class BaseChannel(ABC):
    """Interface que todo canal deve implementar."""

    kind: ChannelKind

    @abstractmethod
    async def start(self, on_message: OnMessage) -> None:
        """Começa a escutar o transporte. Retorna quando o canal foi
        inicializado; deve continuar rodando em background até `stop()`.
        """

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> None:
        """Entrega uma mensagem pelo transporte."""

    @abstractmethod
    async def stop(self) -> None:
        """Desliga a escuta de forma limpa."""


class ChannelRegistry:
    """Mantém canais ativos, permitindo ao Gateway enviar por `ChannelKind`."""

    def __init__(self) -> None:
        self._channels: dict[ChannelKind, BaseChannel] = {}

    def register(self, channel: BaseChannel) -> None:
        self._channels[channel.kind] = channel

    def get(self, kind: ChannelKind) -> BaseChannel:
        return self._channels[kind]

    async def send(self, message: OutgoingMessage) -> None:
        await self._channels[message.channel].send(message)

    async def stop_all(self) -> None:
        for ch in self._channels.values():
            await ch.stop()
