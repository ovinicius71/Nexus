"""Telegram bot application (Phase 2: capture + classification + corrections)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

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
    BotCommand("dia", "Tarefas e eventos de hoje"),
    BotCommand("hoje", "Entradas de hoje"),
    BotCommand("ideias", "Suas ideias"),
    BotCommand("eventos", "Seus eventos"),
    BotCommand("buscar", "Buscar por termo"),
    BotCommand("review", "Análise da semana (IA)"),
    BotCommand("export", "Exportar para o Obsidian"),
]

from ..config import Settings
from ..db.models import Entry
from ..db.repository import EntryRepository
from ..embeddings import Embedder
from ..export import VaultExporter
from ..llm.classifier import Classifier
from ..llm.insights import ReviewAnalyzer
from ..llm.search import Candidate, SearchRanker
from ..review import render_review, run_review, trigger_met, weeks_of_use
from ..semantic import SemanticIndex

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


def _embedder(context: ContextTypes.DEFAULT_TYPE) -> Embedder | None:
    return context.application.bot_data.get("embedder")


def _search_ranker(context: ContextTypes.DEFAULT_TYPE) -> SearchRanker | None:
    return context.application.bot_data.get("search_ranker")


def _review_analyzer(context: ContextTypes.DEFAULT_TYPE) -> ReviewAnalyzer | None:
    return context.application.bot_data.get("review_analyzer")


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_review(session_factory: sessionmaker[Session], analyzer: ReviewAnalyzer):
    """Blocking: build the snapshot, call Sonnet, store the review (run in a thread)."""
    with session_factory() as session:
        review, result = run_review(session, analyzer)
        return result, review.period_start, review.period_end


def _semantic_index(context: ContextTypes.DEFAULT_TYPE, session: Session) -> SemanticIndex:
    return SemanticIndex(session, context.application.bot_data["embedding_dim"])


def suggestion_keyboard(connection_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔗 Linkar", callback_data=f"lk:{connection_id}"),
                InlineKeyboardButton("✕ Ignorar", callback_data=f"nl:{connection_id}"),
            ]
        ]
    )


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
        suggestion = await _index_and_suggest(context, session, repo, entry)

    await message.reply_text(text, reply_markup=main_keyboard(entry.id))
    if suggestion is not None:
        await message.reply_text(suggestion[0], reply_markup=suggestion_keyboard(suggestion[1]))


async def _index_and_suggest(context, session, repo, entry) -> tuple[str, int] | None:
    """Embed the entry, store it, and (if a close match exists) build a suggestion."""
    embedder = _embedder(context)
    if embedder is None:
        return None
    index = _semantic_index(context, session)
    vector = await asyncio.to_thread(embedder.encode, entry.raw_text)
    matches = index.search(vector, k=1, exclude_id=entry.id)
    index.upsert(entry.id, vector)

    threshold = context.application.bot_data["similarity_threshold"]
    if not matches or matches[0][1] < threshold:
        return None
    other_id, similarity = matches[0]
    other = repo.get_by_id(other_id)
    if other is None:
        return None
    connection = repo.add_pending_connection(entry.id, other_id, similarity)
    when = other.created_at.date().isoformat()
    text = (
        f"🔗 Isso lembra a entrada #{other_id} — \"{other.title or other.raw_text[:40]}\" "
        f"(de {when}, {similarity:.0%} parecido). Quer linkar?"
    )
    return text, connection.id


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


async def cmd_dia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Today's agenda: tasks due today (or overdue) + events happening today."""
    today = datetime.now().astimezone().date()
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        tasks = repo.list_due_today_or_overdue(today)
        events = repo.list_events_on_day(today)

    if not tasks and not events:
        await update.message.reply_text("🗓 Nada marcado para hoje. Dia livre! 🎉")
        return

    if tasks:
        await update.message.reply_text(f"✅ Tarefas do dia ({len(tasks)}):")
        for task in tasks:
            overdue = task.due_date is not None and task.due_date.date() < today
            line = format_entry_line(task) + ("  ⚠️ atrasada" if overdue else "")
            await update.message.reply_text(line, reply_markup=done_keyboard(task.id))
    else:
        await update.message.reply_text("✅ Nenhuma tarefa para hoje. 🎉")

    if events:
        await update.message.reply_text(render_list("📅 Eventos de hoje:", events))


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


# For the Haiku-reranked search we cast a wide net (low similarity floor) and let
# the model provide precision; without a ranker we keep the stricter threshold.
_RERANK_RECALL_FLOOR = 0.2
_RERANK_MAX_CANDIDATES = 25


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    term = " ".join(context.args).strip() if context.args else ""
    if not term:
        await update.message.reply_text("Uso: /buscar <termo>")
        return
    ranker = _search_ranker(context)
    if ranker is not None:
        await _buscar_reranked(update, context, term, ranker)
    else:
        await _buscar_hybrid(update, context, term)


async def _buscar_reranked(
    update: Update, context: ContextTypes.DEFAULT_TYPE, term: str, ranker: SearchRanker
) -> None:
    """Gather a wide candidate pool, then let Haiku keep only true matches."""
    embedder = _embedder(context)
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        literal = repo.search(term)
        literal_ids = {e.id for e in literal}
        semantic: list[Entry] = []
        if embedder is not None:
            vector = await asyncio.to_thread(embedder.encode, term)
            matches = _semantic_index(context, session).search(vector, k=15)
            semantic_ids = [
                mid
                for mid, sim in matches
                if sim >= _RERANK_RECALL_FLOOR and mid not in literal_ids
            ]
            semantic = repo.get_by_ids(semantic_ids)

        candidates = (literal + semantic)[:_RERANK_MAX_CANDIDATES]
        if not candidates:
            await update.message.reply_text(f'🔎 Nada encontrado para "{term}".')
            return

        payload = [
            Candidate(id=e.id, text=e.title or e.raw_text[:80], type=e.type) for e in candidates
        ]
        ranked_ids = await asyncio.to_thread(ranker.rank, term, payload)
        # If the model returns nothing, fall back to exact matches so a literal
        # hit is never silently dropped.
        results = repo.get_by_ids(ranked_ids) or literal

    if results:
        await update.message.reply_text(render_list(f'🔎 Resultados para "{term}":', results))
    else:
        await update.message.reply_text(f'🔎 Nada encontrado para "{term}".')


async def _buscar_hybrid(update: Update, context: ContextTypes.DEFAULT_TYPE, term: str) -> None:
    """Local-only search: exact matches first, then semantic ones (no API)."""
    embedder = _embedder(context)
    with _session_factory(context)() as session:
        repo = EntryRepository(session)
        literal = repo.search(term)
        literal_ids = {e.id for e in literal}
        related = []
        if embedder is not None:
            vector = await asyncio.to_thread(embedder.encode, term)
            matches = _semantic_index(context, session).search(vector, k=10)
            threshold = context.application.bot_data["search_threshold"]
            related_ids = [
                mid for mid, sim in matches if sim >= threshold and mid not in literal_ids
            ]
            related = repo.get_by_ids(related_ids)

    sections = []
    if literal:
        sections.append(render_list(f'🔎 Resultados para "{term}":', literal))
    if related:
        sections.append(render_list("🔗 Relacionados (por similaridade):", related))
    if not sections:
        sections.append(f'🔎 Nada encontrado para "{term}".')
    await update.message.reply_text("\n\n".join(sections))


async def on_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    connection_id = int(query.data.split(":")[1])
    with _session_factory(context)() as session:
        EntryRepository(session).set_connection_accepted(connection_id, True)
    await query.answer("Linkado 🔗")
    await query.edit_message_text(query.message.text + "\n\n🔗 Conexão salva.")


async def on_nolink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    connection_id = int(query.data.split(":")[1])
    with _session_factory(context)() as session:
        EntryRepository(session).set_connection_accepted(connection_id, False)
    await query.answer("Ignorado")
    await query.edit_message_text(query.message.text + "\n\n✕ Ignorado.")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Export all entries to the Obsidian vault."""
    vault_path = context.application.bot_data["vault_path"]
    with _session_factory(context)() as session:
        result = await asyncio.to_thread(VaultExporter(session, vault_path).export)
    await update.message.reply_text(
        f"📤 Export concluído: {result.entries} entrada(s), {result.days} dia(s), "
        f"{result.projects} projeto(s), {result.people} pessoa(s) e "
        f"{result.reviews} review(s) em `{result.vault}`."
    )


# --- weekly review (Phase 6) -----------------------------------------------


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send the weekly review on demand (Claude Sonnet)."""
    analyzer = _review_analyzer(context)
    if analyzer is None:
        await update.message.reply_text(
            "🧠 Review indisponível — defina ANTHROPIC_API_KEY."
        )
        return
    await update.message.reply_text("🧠 Analisando sua semana… (pode levar alguns segundos)")
    try:
        result, period_start, period_end = await asyncio.to_thread(
            _generate_review, _session_factory(context), analyzer
        )
    except Exception:
        logger.exception("Weekly review failed")
        await update.message.reply_text(
            "⚠️ Não consegui gerar o review agora (erro na IA). Tente mais tarde."
        )
        return
    await update.message.reply_text(render_review(result, period_start, period_end))


async def weekly_review_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled daily; acts only on the configured weekday once the trigger is met."""
    bot_data = context.application.bot_data
    analyzer = bot_data.get("review_analyzer")
    if analyzer is None:
        return
    tz = ZoneInfo(bot_data["timezone"])
    if datetime.now(tz).weekday() != bot_data["review_weekday"]:
        return

    session_factory = bot_data["session_factory"]
    with session_factory() as session:
        repo = EntryRepository(session)
        total = repo.count_entries()
        first_at = repo.first_entry_at()
    weeks = weeks_of_use(first_at, _now_utc_naive())
    if not trigger_met(
        total, weeks, bot_data["review_min_entries"], bot_data["review_min_weeks"]
    ):
        logger.info(
            "Weekly review skipped: trigger not met (entries=%s, weeks=%s)", total, weeks
        )
        return

    try:
        result, period_start, period_end = await asyncio.to_thread(
            _generate_review, session_factory, analyzer
        )
    except Exception:
        logger.exception("Automatic weekly review failed")
        return
    await context.bot.send_message(
        bot_data["allowed_chat_id"],
        "🗓 Seu review semanal automático:\n\n"
        + render_review(result, period_start, period_end),
    )


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
    embedder: Embedder | None = None,
    search_ranker: SearchRanker | None = None,
    review_analyzer: ReviewAnalyzer | None = None,
) -> Application:
    """Wire up the Telegram application with handlers restricted to the owner chat."""
    application = (
        ApplicationBuilder().token(settings.telegram_bot_token).post_init(_post_init).build()
    )
    application.bot_data["session_factory"] = session_factory
    application.bot_data["allowed_chat_id"] = settings.allowed_chat_id
    application.bot_data["classifier"] = classifier
    application.bot_data["vault_path"] = settings.vault_path
    application.bot_data["embedder"] = embedder
    application.bot_data["embedding_dim"] = embedder.dim if embedder is not None else None
    application.bot_data["similarity_threshold"] = settings.similarity_threshold
    application.bot_data["search_threshold"] = settings.search_threshold
    application.bot_data["search_ranker"] = search_ranker
    application.bot_data["review_analyzer"] = review_analyzer
    application.bot_data["timezone"] = settings.timezone
    application.bot_data["review_weekday"] = settings.review_weekday
    application.bot_data["review_min_entries"] = settings.review_min_entries
    application.bot_data["review_min_weeks"] = settings.review_min_weeks

    owner_only = filters.Chat(chat_id=settings.allowed_chat_id)

    application.add_handler(CommandHandler("start", start, filters=owner_only))
    application.add_handler(CommandHandler("tarefas", cmd_tarefas, filters=owner_only))
    application.add_handler(CommandHandler("dia", cmd_dia, filters=owner_only))
    application.add_handler(CommandHandler("hoje", cmd_hoje, filters=owner_only))
    application.add_handler(CommandHandler("ideias", cmd_ideias, filters=owner_only))
    application.add_handler(CommandHandler("eventos", cmd_eventos, filters=owner_only))
    application.add_handler(CommandHandler("buscar", cmd_buscar, filters=owner_only))
    application.add_handler(CommandHandler("review", cmd_review, filters=owner_only))
    application.add_handler(CommandHandler("export", cmd_export, filters=owner_only))
    application.add_handler(
        MessageHandler(owner_only & filters.TEXT & ~filters.COMMAND, handle_text)
    )
    application.add_handler(CallbackQueryHandler(on_done, pattern=r"^done:"))
    application.add_handler(CallbackQueryHandler(on_link, pattern=r"^lk:"))
    application.add_handler(CallbackQueryHandler(on_nolink, pattern=r"^nl:"))
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

    _schedule_weekly_review(application, settings)
    return application


def _schedule_weekly_review(application: Application, settings: Settings) -> None:
    """Schedule the proactive weekly review (JobQueue = APScheduler under the hood).

    Runs daily at the configured hour; ``weekly_review_job`` itself gates on the
    weekday and the proactivity trigger, so the weekday choice stays robust
    regardless of the JobQueue's day-indexing.
    """
    if not settings.review_auto_enabled or application.bot_data.get("review_analyzer") is None:
        return
    if application.job_queue is None:  # pragma: no cover - needs [job-queue] extra
        logger.warning("JobQueue unavailable; automatic weekly review disabled.")
        return
    try:
        tz = ZoneInfo(settings.timezone)
    except Exception:  # pragma: no cover - bad tz name in .env
        logger.warning("Invalid TIMEZONE %r; falling back to UTC.", settings.timezone)
        tz = timezone.utc
    run_at = dtime(hour=settings.review_hour, minute=0, tzinfo=tz)
    application.job_queue.run_daily(weekly_review_job, time=run_at, name="weekly_review")
    logger.info(
        "Weekly review scheduled: weekday=%s at %02d:00 %s",
        settings.review_weekday, settings.review_hour, settings.timezone,
    )
