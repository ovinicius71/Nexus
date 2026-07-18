"""Weekly review orchestration (Phase 6).

Builds a compact text snapshot of the database, sends it to
:class:`~organizer.llm.insights.ReviewAnalyzer` (Claude Sonnet), stores the
result and renders it for Telegram / Obsidian. Also holds the proactivity
trigger (enough entries or enough weeks of use).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .db.models import Entry, Review
from .db.repository import EntryRepository
from .llm.insights import ReviewAnalyzer, WeeklyReview

WEEK_DAYS = 7

# Section metadata: json field -> (emoji + heading) for rendering.
_SECTIONS = [
    ("postponed_tasks", "⏳ Tarefas adiadas"),
    ("growing_themes", "📈 Temas em crescimento"),
    ("orphan_ideas", "💡 Ideias órfãs"),
    ("routine_patterns", "🔁 Padrões de rotina"),
]


def _now_naive() -> datetime:
    """Current time as naive UTC, matching how ``created_at`` is stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def weeks_of_use(first_at: datetime | None, now: datetime) -> int:
    """Whole weeks between the first entry and ``now`` (0 if no entries)."""
    if first_at is None:
        return 0
    return max(0, (now - _naive(first_at)).days) // WEEK_DAYS


def trigger_met(
    total_entries: int, weeks: int, min_entries: int, min_weeks: int
) -> bool:
    """Proactivity gate: enough accumulated entries OR enough weeks of use."""
    return total_entries >= min_entries or weeks >= min_weeks


# --- snapshot building ------------------------------------------------------


def _entry_age_days(entry: Entry, now: datetime) -> int:
    return max(0, (now - _naive(entry.created_at)).days)


def _describe_entry(repo: EntryRepository, entry: Entry) -> str:
    people = ", ".join(repo.get_people(entry)) or "—"
    due = entry.due_date.date().isoformat() if entry.due_date else "—"
    head = (
        f"- [{entry.type or 'note'}] #{entry.id} \"{entry.title or entry.raw_text[:40]}\" | "
        f"projeto: {entry.project or '—'} | pessoas: {people} | prazo: {due} | "
        f"status: {entry.status or '—'}"
    )
    return head + f"\n  texto: {entry.raw_text}"


def _type_counts(entries: list[Entry]) -> str:
    counts = Counter(e.type or "note" for e in entries)
    order = ["task", "event", "idea", "note"]
    return ", ".join(f"{t}: {counts.get(t, 0)}" for t in order)


def _project_counts(entries: list[Entry], top: int = 8) -> str:
    counts = Counter(e.project for e in entries if e.project)
    if not counts:
        return "—"
    return ", ".join(f"{p}: {n}" for p, n in counts.most_common(top))


def build_snapshot(
    repo: EntryRepository, now: datetime | None = None
) -> tuple[str, datetime, datetime]:
    """Return ``(snapshot_text, period_start, period_end)`` for the analyzer."""
    now = now or _now_naive()
    period_start = now - timedelta(days=WEEK_DAYS)

    all_entries = repo.list_all()
    total = len(all_entries)
    first_at = all_entries[0].created_at if all_entries else None
    recent = [e for e in all_entries if _naive(e.created_at) >= period_start]

    open_tasks = [e for e in all_entries if e.type == "task" and e.status == "open"]
    orphan_ideas = [
        e
        for e in all_entries
        if e.type == "idea" and not e.project and not repo.get_related(e.id)
    ]

    lines: list[str] = [
        f"CURRENT DATE: {now.date().isoformat()}",
        f"JANELA DA SEMANA: {period_start.date().isoformat()} a {now.date().isoformat()}",
        "",
        "VISAO GERAL:",
        f"- Total de entradas (historico): {total}",
        f"- Semanas de uso: {weeks_of_use(first_at, now)}",
        f"- Entradas nesta semana: {len(recent)}",
        f"- Por tipo (historico): {_type_counts(all_entries)}",
        f"- Por tipo (semana): {_type_counts(recent)}",
        f"- Por projeto (historico): {_project_counts(all_entries)}",
        f"- Por projeto (semana): {_project_counts(recent)}",
        "",
        "TAREFAS ABERTAS (id, titulo, idade, prazo, prioridade):",
    ]
    if open_tasks:
        for e in open_tasks:
            due = e.due_date.date().isoformat() if e.due_date else "sem prazo"
            overdue = (
                " [VENCIDA]"
                if e.due_date is not None and _naive(e.due_date) < now
                else ""
            )
            lines.append(
                f"- #{e.id} \"{e.title or e.raw_text[:40]}\" — criada ha "
                f"{_entry_age_days(e, now)}d, prazo {due}{overdue}, "
                f"prioridade {e.priority or '—'}"
            )
    else:
        lines.append("- (nenhuma)")

    lines += ["", "IDEIAS SEM PROJETO E SEM CONEXAO (possiveis orfas):"]
    if orphan_ideas:
        for e in orphan_ideas:
            when = _naive(e.created_at).date().isoformat()
            lines.append(f"- #{e.id} \"{e.title or e.raw_text[:40]}\" (de {when})")
    else:
        lines.append("- (nenhuma)")

    lines += ["", "ENTRADAS DESTA SEMANA (cruas):"]
    if recent:
        lines += [_describe_entry(repo, e) for e in recent]
    else:
        lines.append("- (nenhuma nesta semana)")

    return "\n".join(lines), period_start, now


# --- orchestration ----------------------------------------------------------


def run_review(
    session: Session, analyzer: ReviewAnalyzer, now: datetime | None = None
) -> tuple[Review, WeeklyReview]:
    """Build the snapshot, analyze it, store the review and return both."""
    repo = EntryRepository(session)
    snapshot, period_start, period_end = build_snapshot(repo, now)
    result = analyzer.analyze(snapshot)
    review = repo.add_review(
        period_start=period_start,
        period_end=period_end,
        summary=result.summary or "(sem resumo)",
        content_json=result.model_dump_json(),
    )
    return review, result


# --- rendering --------------------------------------------------------------


def render_review(review: WeeklyReview, period_start: datetime, period_end: datetime) -> str:
    """Human-readable review for Telegram (also the basis for the Obsidian note)."""
    header = (
        f"🧠 Review da semana "
        f"({period_start.date().isoformat()} → {period_end.date().isoformat()})"
    )
    parts = [header]
    if review.summary:
        parts.append(review.summary)
    for field, heading in _SECTIONS:
        items = getattr(review, field)
        if not items:
            continue
        block = "\n".join(f"• {item}" for item in items)
        parts.append(f"{heading}:\n{block}")
    if len(parts) == 1:  # only the header — nothing to report
        parts.append("Sem destaques nesta semana. 🌱")
    return "\n\n".join(parts)
