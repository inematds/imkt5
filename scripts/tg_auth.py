#!/usr/bin/env python3
"""One-shot Telegram auth — gera session file pro worker telegram-scraper.

Uso:
  python scripts/tg_auth.py +5511999999999 inema

Argumentos:
  phone    — número do usuário com DDI (ex: +5511988887777)
  tenant   — tenant_id (identifica session; ex: "inema")

Pede código SMS (Telegram envia app/sms) e senha 2FA se configurada.
Gera session file em $TELEGRAM_SESSION_DIR/<tenant>.session.

Requer TELEGRAM_API_ID e TELEGRAM_API_HASH no .env.
Criar credentials em https://my.telegram.org/apps (grátis, 5 min).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


def _load_env() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


async def main() -> None:
    _load_env()

    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)

    phone = sys.argv[1]
    tenant = sys.argv[2]

    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        print("ERROR: TELEGRAM_API_ID + TELEGRAM_API_HASH precisam estar no .env.",
              file=sys.stderr)
        print("Pega em https://my.telegram.org/apps", file=sys.stderr)
        sys.exit(3)

    try:
        api_id_int = int(api_id)
    except ValueError:
        print(f"ERROR: TELEGRAM_API_ID deve ser int, got: {api_id}", file=sys.stderr)
        sys.exit(3)

    session_dir = Path(os.environ.get("TELEGRAM_SESSION_DIR", "./data/tg-sessions"))
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / tenant

    from telethon import TelegramClient

    print(f"Conectando… session = {session_path}.session")
    client = TelegramClient(str(session_path), api_id_int, api_hash)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"✓ Já autenticado como {me.first_name} (@{me.username or '-'})")
        print(f"  Session reutilizável em: {session_path}.session")
        await client.disconnect()
        return

    print(f"Pedindo código pra {phone}…")
    sent = await client.send_code_request(phone)
    code = input("Código Telegram recebido: ").strip()

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
    except Exception as exc:  # SessionPasswordNeededError etc
        if "2FA" in str(exc) or "password" in str(exc).lower():
            pw = input("Senha 2FA (cloud password): ")
            await client.sign_in(password=pw)
        else:
            raise

    me = await client.get_me()
    print(f"✓ Autenticado como {me.first_name} (@{me.username or '-'}) id={me.id}")
    print(f"  Session salva em: {session_path}.session")
    print(f"  Worker telegram-scraper agora pode usar tenant='{tenant}'.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
