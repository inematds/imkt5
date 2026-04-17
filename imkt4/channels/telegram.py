"""Telegram channel — adapter real.

Long-polling via python-telegram-bot. Traduz update → IncomingMessage,
chama `on_message(msg)` (agent loop), envia OutgoingMessage de volta.

Multi-tenant: por enquanto resolve `(chat_id) → (tenant_id, user_id)` via
um mapa simples passado no construtor. Quando houver DB (#5 do backlog),
vira query em `channel_bindings`.

Segurança: só aceita mensagens de chat_ids em `allowed_chat_ids`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from imkt4.channels.base import BaseChannel
from imkt4.types.messages import IncomingMessage, OutgoingMessage
from imkt4.types.tenants import ChannelKind

log = logging.getLogger("imkt4.telegram")

OnMessage = Callable[[IncomingMessage], Awaitable[OutgoingMessage | None]]


@dataclass(frozen=True)
class TelegramIdentity:
    """Resolve telegram chat_id → (tenant_id, user_id)."""
    tenant_id: str
    user_id: str


class TelegramChannel(BaseChannel):
    kind = ChannelKind.TELEGRAM

    def __init__(
        self,
        *,
        bot_token: str,
        allowed_chat_ids: set[int],
        identity_map: dict[int, TelegramIdentity] | None = None,
        default_tenant_id: str = "demo",
    ) -> None:
        self._token = bot_token
        self._allowed = allowed_chat_ids
        self._identity_map = identity_map or {}
        self._default_tenant = default_tenant_id
        self._app: Application | None = None
        self._on_message: OnMessage | None = None

    async def start(self, on_message: OnMessage) -> None:
        self._on_message = on_message
        self._app = (
            Application.builder()
            .token(self._token)
            .build()
        )
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text)
        )
        self._app.add_handler(
            MessageHandler(filters.COMMAND, self._handle_command)
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        log.info("telegram channel started (long-polling)")

    async def send(self, message: OutgoingMessage) -> None:
        if self._app is None:
            raise RuntimeError("canal não iniciado")
        chat_id = int(message.channel_external_id)
        text = message.text or ""
        # split >4000 chars em blocos (limite Telegram é 4096)
        if len(text) <= 4000:
            await self._app.bot.send_message(chat_id=chat_id, text=text)
            return
        for i in range(0, len(text), 4000):
            await self._app.bot.send_message(chat_id=chat_id, text=text[i:i+4000])

    async def stop(self) -> None:
        if self._app is None:
            return
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        log.info("telegram channel stopped")

    # ── handlers ──────────────────────────────────────────────────────
    async def _handle_text(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch(update, is_command=False)

    async def _handle_command(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        cmd = (update.message.text or "").split()[0].lstrip("/").lower()
        # comandos especiais locais
        if cmd == "chatid":
            await self._reply(update, f"seu chat_id: `{update.effective_chat.id}`")
            return
        if cmd == "start":
            await self._reply(
                update,
                "Olá! Eu sou o imkt4. Manda uma mensagem em português — "
                "posso gerar imagem, áudio, pesquisar, rodar campanhas. "
                "Digite /help pra lista de atalhos.",
            )
            return
        if cmd == "help":
            await self._reply(
                update,
                "Comandos:\n"
                "  /start — boas-vindas\n"
                "  /chatid — mostra seu chat_id\n"
                "  /help — esta lista\n"
                "\nOu só manda sua mensagem em português.",
            )
            return
        # qualquer outro comando: trata como texto
        await self._dispatch(update, is_command=True)

    async def _dispatch(self, update: Update, *, is_command: bool) -> None:
        if self._on_message is None:
            return
        chat = update.effective_chat
        user = update.effective_user
        msg = update.message
        if chat is None or msg is None:
            return

        if chat.id not in self._allowed:
            log.warning("ignoring msg from unauthorized chat_id=%d", chat.id)
            await self._reply(update, "Desculpe, você não está autorizado.")
            return

        ident = self._identity_map.get(
            chat.id,
            TelegramIdentity(
                tenant_id=self._default_tenant,
                user_id=str(user.id if user else chat.id),
            ),
        )

        text = msg.text or ""
        inc = IncomingMessage(
            tenant_id=ident.tenant_id,
            user_id=ident.user_id,
            channel=ChannelKind.TELEGRAM,
            channel_external_id=str(chat.id),
            text=text,
        )

        try:
            await self._app.bot.send_chat_action(chat_id=chat.id, action="typing")
            out = await self._on_message(inc)
        except Exception as exc:  # noqa: BLE001
            log.exception("erro processando msg")
            await self._reply(update, f"❌ Erro: {exc}")
            return

        if out and out.text:
            await self.send(out)

    async def _reply(self, update: Update, text: str) -> None:
        await update.message.reply_text(text)
