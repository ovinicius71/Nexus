"""Telegram bot application (Phase 1: raw capture)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker, Session
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import Settings
from ..db.repository import EntryRepository

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Olá! Sou seu organizador pessoal.\n\n"
    "Me mande qualquer coisa ao longo do dia — tarefas, ideias, eventos ou "
    "anotações — e eu guardo tudo para você. Por enquanto (Fase 1) apenas salvo "
    "o texto; em breve vou classificar e organizar automaticamente."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if update.message is None:
        return
    await update.message.reply_text(WELCOME)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist an incoming text message as a raw entry and confirm."""
    message = update.message
    if message is None or not message.text:
        return

    session_factory: sessionmaker[Session] = context.application.bot_data["session_factory"]
    with session_factory() as session:
        repo = EntryRepository(session)
        entry = repo.add_raw_entry(message.text)

    logger.info("Saved entry id=%s (%d chars)", entry.id, len(message.text))
    saved_at = entry.created_at.astimezone().strftime("%H:%M")
    await message.reply_text(f"✅ Salvo (#{entry.id}) às {saved_at}")


async def log_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the chat id of every incoming message (setup helper).

    Runs in a separate handler group so it fires even for chats that are not
    allowed, letting the user discover their own ALLOWED_CHAT_ID from the console.
    """
    chat = update.effective_chat
    if chat is None:
        return
    allowed = context.application.bot_data.get("allowed_chat_id")
    status = "authorized" if chat.id == allowed else "IGNORED (set this as ALLOWED_CHAT_ID)"
    logger.info("Incoming message from chat_id=%s -> %s", chat.id, status)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and, when possible, notify the user."""
    logger.error("Error while handling update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                "⚠️ Algo deu errado ao salvar sua mensagem. Tente novamente."
            )
        except Exception:  # pragma: no cover - best effort notification
            logger.exception("Failed to send error message to user")


def build_application(settings: Settings, session_factory: sessionmaker[Session]) -> Application:
    """Wire up the Telegram application with handlers restricted to the owner chat."""
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    application.bot_data["session_factory"] = session_factory
    application.bot_data["allowed_chat_id"] = settings.allowed_chat_id

    owner_only = filters.Chat(chat_id=settings.allowed_chat_id)

    application.add_handler(CommandHandler("start", start, filters=owner_only))
    application.add_handler(
        MessageHandler(owner_only & filters.TEXT & ~filters.COMMAND, handle_text)
    )
    # Setup helper (group 1): logs the chat id of any incoming message so the
    # user can find their ALLOWED_CHAT_ID. Fires alongside the handlers above.
    application.add_handler(MessageHandler(filters.ALL, log_incoming), group=1)
    application.add_error_handler(on_error)

    return application
