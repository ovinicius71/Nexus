"""Telegram bot application (Phase 2: capture + classification + corrections)."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session, sessionmaker
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_COMMANDS = [
    BotCommand("tarefas", "Tarefas abertas"),
    BotCommand("hoje", "Entradas de hoje"),
    BotCommand("ideias", "Suas ideias"),
    BotCommand("eventos", "Seus eventos"),
    BotCommand("buscar", "Buscar por termo"),
]

from ..config import Settings
from ..db.models import Entry
from ..db.repository import EntryRepository
from ..llm.classifier import Classifier

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Olá! Sou seu organizador pessoal.\n\n"
    "Me mande qualquer coisa ao longo do dia — tarefas, ideias, eventos ou "
    "anotações. Eu classifico e guardo tudo, e você pode corrigir a "
    "classificação nos botões abaixo de cada mensagem."
)

TYPE_LABELS = {"idea": "💡 Ideia", "task": "✅ Tarefa", "event": "📅 Evento", "note": "📝 Nota"}
PRIORITY_LABELS = {"high": "🔴 Alta", "medium": "🟡 Média", "low": "🟢 Baixa"}


# --- rendering -------------------------------------------------------------


def render_card(entry: Entry, people: list[str], suffix: str = "") -> str:
    """Build the human-readable classification summary for an entry."""
    type_label = TYPE_LABELS.get(entry.type or "", entry.type or "—")
    due = entry.due_date.date().isoformat() if entry.due_date else "—"
    priority = PRIORITY_LABELS.get(entry.priority or "", "—")
    lines = [
        f"📥 Entrada #{entry.id} classificada:",
        f"• Tipo: {type_label}",
        f"• Título: {entry.title or '—'}",
        f"• Prazo: {due}",
        f"• Prioridade: {priority}",
        f"• Projeto: {entry.project or '—'}",
        f"• Pessoas: {', '.join(people) if people else '—'}",
    ]
    if suffix:
        lines.append("")
        lines.append(suffix)
    return "\n".join(lines)


def main_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Correto", callback_data=f"ok:{entry_id}")],
            [
                InlineKeyboardButton("✏️ Tipo", callback_data=f"et:{entry_id}"),
                InlineKeyboardButton("✏️ Prazo/Prioridade", callback_data=f"ep:{entry_id}"),
            ],
        ]
    )


def type_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💡 Ideia", callback_data=f"st:{entry_id}:idea"),
                InlineKeyboardButton("✅ Tarefa", callback_data=f"st:{entry_id}:task"),
            ],
            [
                InlineKeyboardButton("📅 Evento", callback_data=f"st:{entry_id}:event"),
                InlineKeyboardButton("📝 Nota", callback_data=f"st:{entry_id}:note"),
            ],
            [InlineKeyboardButton("⬅️ Voltar", callback_data=f"bk:{entry_id}")],
        ]
    )


def priority_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔴 Alta", callback_data=f"sp:{entry_id}:high"),
                InlineKeyboardButton("🟡 Média", callback_data=f"sp:{entry_id}:medium"),
                InlineKeyboardButton("🟢 Baixa", callback_data=f"sp:{entry_id}:low"),
            ],
            [
                InlineKeyboardButton("Sem prioridade", callback_data=f"sp:{entry_id}:none"),
                InlineKeyboardButton("🗑 Limpar prazo", callback_data=f"cd:{entry_id}"),
            ],
            [InlineKeyboardButton("⬅️ Voltar", callback_data=f"bk:{entry_id}")],
        ]
    )


PRIORITY_MARK = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def format_entry_line(entry: Entry) -> str:
    """One-line summary of an entry for list views."""
    icon = {"idea": "💡", "task": "✅", "event": "📅", "note": "📝"}.get(entry.type or "", "•")
    parts = [f"{icon} #{entry.id} {entry.title or entry.raw_text[:40]}"]
    if entry.due_date is not None:
        parts.append(f"🗓 {entry.due_date.date().isoformat()}")
    if entry.priority:
        parts.append(PRIORITY_MARK.get(entry.priority, ""))
    return "  ".join(p for p in parts if p)


def render_list(title: str, entries: list[Entry]) -> str:
    if not entries:
        return f"{title}\n(nada por aqui)"
    return "\n".join([title, *(format_entry_line(e) for e in entries)])


def done_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✔️ Concluir", callback_data=f"done:{entry_id}")]]
    )


# --- helpers ---------------------------------------------------------------


def _session_factory(context: ContextTypes.DEFAULT_TYPE) -> sessionmaker[Session]:
    return context.application.bot_data["session_factory"]


def _classifier(context: ContextTypes.DEFAULT_TYPE) -> Classifier | None:
    return context.application.bot_data.get("classifier")


def _entry_id_from_callback(data: str) -> int:
    # data forms: "ok:12", "st:12:task", "sp:12:high"
    return int(data.split(":")[1])


async def _rerender(update: Update, context: ContextTypes.DEFAULT_TYPE, suffix: str) -> None:
    """Re-render an entry's card in place with the main keyboard."""
    entry_id = _entry_id_from_callback(update.callback_query.data)
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        entry = repo.get_by_id(entry_id)
        if entry is None:
            return
        people = repo.get_people(entry)
        text = render_card(entry, people, suffix)
    await update.callback_query.edit_message_text(text, reply_markup=main_keyboard(entry_id))


# --- command / message handlers -------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is not None:
        await update.message.reply_text(WELCOME)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist a raw note, classify it, and reply with the summary card."""
    message = update.message
    if message is None or not message.text:
        return

    classifier = _classifier(context)
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        entry = repo.add_raw_entry(message.text)

        if classifier is None:
            await message.reply_text(
                f"✅ Salvo (#{entry.id}) — classificação desativada "
                "(defina ANTHROPIC_API_KEY)."
            )
            return

        corrections = repo.get_recent_corrections(limit=10)
        try:
            classification = await asyncio.to_thread(
                classifier.classify, message.text, corrections
            )
        except Exception:
            logger.exception("Classification failed for entry id=%s", entry.id)
            await message.reply_text(
                f"✅ Salvo (#{entry.id}), mas não consegui classificar agora "
                "(erro na IA). O texto está guardado."
            )
            return

        repo.apply_classification(entry, classification, classification.model_dump_json())
        people = repo.get_people(entry)
        text = render_card(entry, people)

    await message.reply_text(text, reply_markup=main_keyboard(entry.id))


# --- callback handlers -----------------------------------------------------


async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Confirmado ✅")
    await query.edit_message_reply_markup(reply_markup=None)
    await query.edit_message_text(query.message.text + "\n\n✅ Confirmado.")


async def on_edit_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    entry_id = _entry_id_from_callback(query.data)
    await query.edit_message_reply_markup(reply_markup=type_keyboard(entry_id))


async def on_edit_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    entry_id = _entry_id_from_callback(query.data)
    await query.edit_message_reply_markup(reply_markup=priority_keyboard(entry_id))


async def on_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    entry_id = _entry_id_from_callback(query.data)
    await query.edit_message_reply_markup(reply_markup=main_keyboard(entry_id))


async def on_set_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    new_type = query.data.split(":")[2]
    entry_id = _entry_id_from_callback(query.data)
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        entry = repo.get_by_id(entry_id)
        if entry is not None:
            repo.record_correction(entry, "type", new_type)
    await query.answer("Tipo corrigido ✏️")
    await _rerender(update, context, "✏️ Tipo corrigido (vou lembrar disso).")


async def on_set_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    raw = query.data.split(":")[2]
    new_priority = None if raw == "none" else raw
    entry_id = _entry_id_from_callback(query.data)
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        entry = repo.get_by_id(entry_id)
        if entry is not None:
            repo.record_correction(entry, "priority", new_priority)
    await query.answer("Prioridade corrigida ✏️")
    await _rerender(update, context, "✏️ Prioridade corrigida (vou lembrar disso).")


async def on_clear_due(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    entry_id = _entry_id_from_callback(query.data)
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        entry = repo.get_by_id(entry_id)
        if entry is not None:
            repo.record_correction(entry, "due_date", None)
    await query.answer("Prazo removido ✏️")
    await _rerender(update, context, "✏️ Prazo removido (vou lembrar disso).")


# --- query commands (Phase 3) ----------------------------------------------


async def cmd_tarefas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List open tasks, each with a 'Concluir' button."""
    with _session_factory(context)() as session:
        tasks = EntryRepository(session).list_open_tasks()
    if not tasks:
        await update.message.reply_text("✅ Nenhuma tarefa aberta. 🎉")
        return
    await update.message.reply_text(f"✅ Tarefas abertas ({len(tasks)}):")
    for task in tasks:
        await update.message.reply_text(
            format_entry_line(task), reply_markup=done_keyboard(task.id)
        )


async def cmd_hoje(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with _session_factory(context)() as session:
        entries = EntryRepository(session).list_today()
    await update.message.reply_text(render_list("📆 Entradas de hoje:", entries))


async def cmd_ideias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with _session_factory(context)() as session:
        entries = EntryRepository(session).list_by_type("idea")
    await update.message.reply_text(render_list("💡 Ideias:", entries))


async def cmd_eventos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with _session_factory(context)() as session:
        entries = EntryRepository(session).list_by_type("event")
    await update.message.reply_text(render_list("📅 Eventos:", entries))


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    term = " ".join(context.args).strip() if context.args else ""
    if not term:
        await update.message.reply_text("Uso: /buscar <termo>")
        return
    with _session_factory(context)() as session:
        entries = EntryRepository(session).search(term)
    await update.message.reply_text(render_list(f'🔎 Resultados para "{term}":', entries))


async def on_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    entry_id = _entry_id_from_callback(query.data)
    line = ""
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        entry = repo.get_by_id(entry_id)
        if entry is not None:
            repo.mark_done(entry)
            line = format_entry_line(entry)
    await query.answer("Concluída ✔️")
    await query.edit_message_text(f"{line}\n\n✔️ Concluída.")


# --- setup helpers / wiring ------------------------------------------------


async def log_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the chat id of every incoming message (setup helper)."""
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
            await update.effective_message.reply_text("⚠️ Algo deu errado. Tente novamente.")
        except Exception:  # pragma: no cover - best effort notification
            logger.exception("Failed to send error message to user")


async def _post_init(application: Application) -> None:
    """Register the command menu shown in the Telegram UI."""
    await application.bot.set_my_commands(BOT_COMMANDS)


def build_application(
    settings: Settings,
    session_factory: sessionmaker[Session],
    classifier: Classifier | None = None,
) -> Application:
    """Wire up the Telegram application with handlers restricted to the owner chat."""
    application = (
        ApplicationBuilder().token(settings.telegram_bot_token).post_init(_post_init).build()
    )
    application.bot_data["session_factory"] = session_factory
    application.bot_data["allowed_chat_id"] = settings.allowed_chat_id
    application.bot_data["classifier"] = classifier

    owner_only = filters.Chat(chat_id=settings.allowed_chat_id)

    application.add_handler(CommandHandler("start", start, filters=owner_only))
    application.add_handler(CommandHandler("tarefas", cmd_tarefas, filters=owner_only))
    application.add_handler(CommandHandler("hoje", cmd_hoje, filters=owner_only))
    application.add_handler(CommandHandler("ideias", cmd_ideias, filters=owner_only))
    application.add_handler(CommandHandler("eventos", cmd_eventos, filters=owner_only))
    application.add_handler(CommandHandler("buscar", cmd_buscar, filters=owner_only))
    application.add_handler(
        MessageHandler(owner_only & filters.TEXT & ~filters.COMMAND, handle_text)
    )
    application.add_handler(CallbackQueryHandler(on_done, pattern=r"^done:"))
    application.add_handler(CallbackQueryHandler(on_confirm, pattern=r"^ok:"))
    application.add_handler(CallbackQueryHandler(on_edit_type, pattern=r"^et:"))
    application.add_handler(CallbackQueryHandler(on_edit_priority, pattern=r"^ep:"))
    application.add_handler(CallbackQueryHandler(on_back, pattern=r"^bk:"))
    application.add_handler(CallbackQueryHandler(on_set_type, pattern=r"^st:"))
    application.add_handler(CallbackQueryHandler(on_set_priority, pattern=r"^sp:"))
    application.add_handler(CallbackQueryHandler(on_clear_due, pattern=r"^cd:"))

    # Setup helper (group 1): logs the chat id of any incoming message.
    application.add_handler(MessageHandler(filters.ALL, log_incoming), group=1)
    application.add_error_handler(on_error)

    return application
