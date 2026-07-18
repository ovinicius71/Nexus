"""Export entries to an Obsidian vault — a PARA + Zettelkasten + LYT hybrid (Phase 4).

Design goals (few, meaningful links — not structural noise):

- **Zettelkasten**: every entry is a flat atomic note in ``Slipbox/`` with rich
  frontmatter. Its body links only to things that carry meaning — its project
  and the people it mentions. No "day" or "type" backlinks.
- **PARA** (Tiago Forte) organizes by actionability in the top-level folders:
  ``Projects/`` (has a project), ``Areas/`` (ongoing: loose tasks, agenda,
  people), ``Resources/`` (reference: ideas & notes), ``Archive/`` (done).
- **LYT / MOCs** (Nick Milo): those folders hold Maps of Content that link
  *down* to the atomic notes. A note can appear in several MOCs. ``Home.md`` is
  the root MOC — open one MOC and see the whole landscape (great for AI too).

The vault is generated output: the exporter wipes the folders it manages and
regenerates them deterministically, so the export is idempotent.

Triggered from the bot (``/export``) or as a script (``python -m organizer.export``).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .db.models import Entry
from .db.repository import EntryRepository

logger = logging.getLogger(__name__)

TYPE_ICON = {"task": "✅", "idea": "💡", "event": "📅", "note": "📝", "happening": "📔"}
TYPE_LABEL = {
    "task": "Tarefas", "idea": "Ideias", "event": "Eventos",
    "note": "Notas", "happening": "Acontecimentos",
}
TYPE_ORDER = ["task", "event", "happening", "idea", "note"]
PRIORITY_MARK = {"high": "🔴", "medium": "🟡", "low": "🟢"}

# Folders (and Home.md) regenerated every run. Includes the legacy Phase-4
# layout so re-exporting into an old vault cleans it up.
MANAGED_DIRS = [
    "Projects", "Areas", "Resources", "Archive", "Journal", "Slipbox",
    "index", "daily", "tasks", "ideas", "events", "notes", "projects", "people",
]

_INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class ExportResult:
    entries: int
    days: int
    projects: int
    people: int
    vault: Path
    reviews: int = 0


# Weekly-review sections: json field -> heading (shared with the bot rendering).
REVIEW_SECTIONS = [
    ("postponed_tasks", "⏳ Tarefas adiadas"),
    ("growing_themes", "📈 Temas em crescimento"),
    ("orphan_ideas", "💡 Ideias órfãs"),
    ("routine_patterns", "🔁 Padrões de rotina"),
]


class VaultExporter:
    """Renders the SQLite entries into a PARA + Zettelkasten + LYT vault."""

    def __init__(self, session: Session, vault_path: str | Path) -> None:
        self._repo = EntryRepository(session)
        self._vault = Path(vault_path)

    def export(self) -> ExportResult:
        entries = self._repo.list_all()
        people_map = {e.id: self._repo.get_people(e) for e in entries}

        self._clean()
        for entry in entries:
            self._write_atomic(entry, people_map[entry.id])

        projects = self._write_project_mocs(entries)
        self._write_tarefas_moc(entries)
        self._write_agenda_moc(entries)
        people = self._write_people_mocs(entries, people_map)
        self._write_type_moc("idea", "Resources/Ideias.md", entries)
        self._write_type_moc("note", "Resources/Notas.md", entries)
        self._write_type_moc("happening", "Resources/Acontecimentos.md", entries)
        self._write_archive_moc(entries)
        days = self._write_journal(entries)
        reviews = self._write_reviews()
        self._write_home(projects, people)

        result = ExportResult(
            entries=len(entries), days=days, projects=len(projects),
            people=len(people), vault=self._vault, reviews=reviews,
        )
        logger.info(
            "Exported %s entries, %s days, %s projects, %s people, %s reviews to %s",
            result.entries, result.days, result.projects, result.people,
            result.reviews, self._vault,
        )
        return result

    # --- links ---------------------------------------------------------

    def _atomic_link(self, entry: Entry) -> str:
        return f"[[Slipbox/{_basename(entry)}|{_title(entry)}]]"

    def _project_link(self, project: str) -> str:
        return f"[[Projects/{_slugify(project)}|{project}]]"

    def _home_moc_link(self, entry: Entry) -> str:
        """The note's PARA 'home' MOC — every note up-links here (LYT style)."""
        if _is_archived(entry):
            return "[[Archive/Concluidas|Concluídas]]"
        type_key = _type_of(entry)
        homes = {
            "task": "[[Areas/Tarefas|Tarefas]]",
            "event": "[[Areas/Agenda|Agenda]]",
            "idea": "[[Resources/Ideias|Ideias]]",
            "note": "[[Resources/Notas|Notas]]",
            "happening": "[[Resources/Acontecimentos|Acontecimentos]]",
        }
        return homes[type_key]

    def _person_link(self, name: str) -> str:
        return f"[[Areas/People/{_fs_name(name)}|{name}]]"

    def _moc_line(self, entry: Entry, show_project: bool = True) -> str:
        if entry.type == "task":
            box = "[x]" if _is_archived(entry) else "[ ]"
            line = f"- {box} {self._atomic_link(entry)}"
        else:
            line = f"- {self._atomic_link(entry)}"
        extras = []
        if entry.due_date is not None:
            extras.append(f"🗓 {entry.due_date.date().isoformat()}")
        if entry.priority:
            extras.append(PRIORITY_MARK.get(entry.priority, ""))
        if show_project and entry.project:
            extras.append(self._project_link(entry.project))
        extras = [x for x in extras if x]
        return line + (" — " + " · ".join(extras) if extras else "")

    # --- atomic notes (Zettelkasten) ----------------------------------

    def _write_atomic(self, entry: Entry, people: list[str]) -> None:
        type_key = _type_of(entry)
        tags = [type_key, f"para/{_para_category(entry)}"]
        if entry.project:
            tags.append(f"project/{_slugify(entry.project)}")

        front = _frontmatter(
            {
                "id": entry.id,
                "type": type_key,
                "status": entry.status,
                "created": _local_dt(entry.created_at).isoformat(),
                "due": entry.due_date.date().isoformat() if entry.due_date else None,
                "priority": entry.priority,
                "project": entry.project,
                "people": people,
                "tags": tags,
            }
        )
        body = [front, "", f"# {TYPE_ICON[type_key]} {_title(entry)}", "", entry.raw_text]
        # Up-link to the note's home MOC (LYT): guarantees every note is
        # connected in the graph, even without a project or people.
        links = [f"**Up:** {self._home_moc_link(entry)}"]
        if entry.project:
            links.append(f"**Projeto:** {self._project_link(entry.project)}")
        if people:
            links.append("**Pessoas:** " + " ".join(self._person_link(n) for n in people))
        related = self._repo.get_related(entry.id)
        if related:
            links.append("**Relacionadas:** " + " ".join(self._atomic_link(r) for r in related))
        if links:
            body += ["", "---", *links]
        _write(self._vault / "Slipbox" / f"{_basename(entry)}.md", "\n".join(body).rstrip() + "\n")

    # --- Projects (PARA) ----------------------------------------------

    def _write_project_mocs(self, entries: list[Entry]) -> list[str]:
        groups: dict[str, list[Entry]] = defaultdict(list)
        for entry in entries:
            if entry.project and not _is_archived(entry):
                groups[entry.project].append(entry)

        for project, items in groups.items():
            lines = [
                _frontmatter({"type": "moc", "tags": ["moc", "para/project"]}),
                "", f"# 🎯 {project}", "",
            ]
            self._append_type_sections(lines, items, show_project=False)
            _write(self._vault / "Projects" / f"{_slugify(project)}.md",
                   "\n".join(lines).rstrip() + "\n")
        return sorted(groups)

    # --- Areas (PARA) --------------------------------------------------

    def _write_tarefas_moc(self, entries: list[Entry]) -> None:
        tasks = sorted(
            (e for e in entries if e.type == "task" and e.status == "open"),
            key=_task_sort_key,
        )
        lines = [
            _frontmatter({"type": "moc", "tags": ["moc", "para/area"]}),
            "", "# ✅ Tarefas abertas", "",
        ]
        lines += [self._moc_line(e) for e in tasks] or ["_(nenhuma)_"]
        _write(self._vault / "Areas" / "Tarefas.md", "\n".join(lines) + "\n")

    def _write_agenda_moc(self, entries: list[Entry]) -> None:
        events = sorted(
            (e for e in entries if e.type == "event"),
            key=lambda e: (e.due_date is None, e.due_date or datetime.max, e.id),
        )
        lines = [
            _frontmatter({"type": "moc", "tags": ["moc", "para/area"]}),
            "", "# 📅 Agenda", "",
        ]
        lines += [self._moc_line(e) for e in events] or ["_(nenhum evento)_"]
        _write(self._vault / "Areas" / "Agenda.md", "\n".join(lines) + "\n")

    def _write_people_mocs(
        self, entries: list[Entry], people_map: dict[int, list[str]]
    ) -> list[str]:
        groups: dict[str, list[Entry]] = defaultdict(list)
        for entry in entries:
            if _is_archived(entry):
                continue
            for name in people_map[entry.id]:
                groups[name].append(entry)
        for name, items in groups.items():
            lines = [
                _frontmatter({"type": "moc", "tags": ["moc", "para/area", "person"]}),
                "", f"# 👤 {name}", "", "Mencionada(o) em:", "",
            ]
            lines += [self._moc_line(e) for e in sorted(items, key=lambda e: e.id, reverse=True)]
            _write(self._vault / "Areas" / "People" / f"{_fs_name(name)}.md",
                   "\n".join(lines) + "\n")
        return sorted(groups)

    # --- Resources (PARA) ---------------------------------------------

    def _write_type_moc(self, type_key: str, rel_path: str, entries: list[Entry]) -> None:
        items = sorted(
            (e for e in entries if _type_of(e) == type_key and not _is_archived(e)),
            key=lambda e: e.id, reverse=True,
        )
        lines = [
            _frontmatter({"type": "moc", "tags": ["moc", "para/resource"]}),
            "", f"# {TYPE_ICON[type_key]} {TYPE_LABEL[type_key]}", "",
        ]
        lines += [self._moc_line(e) for e in items] or ["_(vazio)_"]
        _write(self._vault / rel_path, "\n".join(lines) + "\n")

    # --- Archive (PARA) ------------------------------------------------

    def _write_archive_moc(self, entries: list[Entry]) -> None:
        items = sorted(
            (e for e in entries if _is_archived(e)), key=lambda e: e.id, reverse=True
        )
        lines = [
            _frontmatter({"type": "moc", "tags": ["moc", "para/archive"]}),
            "", "# 🗄 Concluídas", "",
        ]
        lines += [self._moc_line(e) for e in items] or ["_(vazio)_"]
        _write(self._vault / "Archive" / "Concluidas.md", "\n".join(lines) + "\n")

    # --- Journal (chronological log) ----------------------------------

    def _write_journal(self, entries: list[Entry]) -> int:
        by_day: dict[date, list[Entry]] = defaultdict(list)
        for entry in entries:
            by_day[_local_date(entry.created_at)].append(entry)
        for day, items in by_day.items():
            lines = [
                _frontmatter({"type": "journal", "date": day.isoformat(), "tags": ["journal"]}),
                "", f"# 📆 {day.isoformat()}", "",
            ]
            self._append_type_sections(lines, items, show_project=True)
            _write(self._vault / "Journal" / f"{day.isoformat()}.md",
                   "\n".join(lines).rstrip() + "\n")
        return len(by_day)

    # --- Reviews (Phase 6) --------------------------------------------

    def _review_basename(self, review) -> str:
        return f"{_plain_date(review.period_end).isoformat()}-{review.id}"

    def _review_link(self, review) -> str:
        label = f"Review {_plain_date(review.period_end).isoformat()}"
        return f"[[Journal/Reviews/{self._review_basename(review)}|{label}]]"

    def _write_reviews(self) -> int:
        reviews = self._repo.list_reviews()
        for review in reviews:
            data = json.loads(review.content_json)
            ps = _plain_date(review.period_start).isoformat()
            pe = _plain_date(review.period_end).isoformat()
            front = _frontmatter(
                {
                    "type": "review",
                    "period_start": ps,
                    "period_end": pe,
                    "created": _local_dt(review.created_at).isoformat(),
                    "tags": ["review", "para/resource"],
                }
            )
            body = [front, "", f"# 🧠 Review {ps} → {pe}", ""]
            summary = data.get("summary") or review.summary
            if summary:
                body += [summary, ""]
            for field, heading in REVIEW_SECTIONS:
                items = data.get(field) or []
                if not items:
                    continue
                body.append(f"## {heading}")
                body += [f"- {item}" for item in items]
                body.append("")
            body.append("**Up:** [[Resources/Reviews|Reviews]]")
            _write(
                self._vault / "Journal" / "Reviews" / f"{self._review_basename(review)}.md",
                "\n".join(body).rstrip() + "\n",
            )
        self._write_reviews_moc(reviews)
        return len(reviews)

    def _write_reviews_moc(self, reviews: list) -> None:
        lines = [
            _frontmatter({"type": "moc", "tags": ["moc", "para/resource"]}),
            "", "# 🧠 Reviews", "",
        ]
        if reviews:
            lines += [f"- {self._review_link(r)} — {r.summary}" for r in reviews]
        else:
            lines.append("_(nenhum review ainda)_")
        _write(self._vault / "Resources" / "Reviews.md", "\n".join(lines) + "\n")

    # --- Home (root MOC) ----------------------------------------------

    def _write_home(self, projects: list[str], people: list[str]) -> None:
        lines = [
            _frontmatter({"type": "home", "tags": ["moc", "home"]}),
            "", "# 🗂 Organizer — Home", "",
            "## 🎯 Projects",
        ]
        lines += [f"- {self._project_link(p)}" for p in projects] or ["_(nenhum)_"]
        lines += [
            "", "## 🔁 Areas",
            "- [[Areas/Tarefas|Tarefas abertas]]",
            "- [[Areas/Agenda|Agenda]]",
        ]
        lines += [f"- {self._person_link(n)}" for n in people]
        lines += [
            "", "## 📚 Resources",
            "- [[Resources/Ideias|Ideias]]",
            "- [[Resources/Notas|Notas]]",
            "- [[Resources/Acontecimentos|Acontecimentos]]",
            "- [[Resources/Reviews|Reviews]]",
            "", "## 🗄 Archive",
            "- [[Archive/Concluidas|Concluídas]]",
        ]
        _write(self._vault / "Home.md", "\n".join(lines) + "\n")

    # --- shared --------------------------------------------------------

    def _append_type_sections(
        self, lines: list[str], items: list[Entry], show_project: bool
    ) -> None:
        for type_key in TYPE_ORDER:
            section = [e for e in items if _type_of(e) == type_key]
            if not section:
                continue
            lines.append(f"## {TYPE_ICON[type_key]} {TYPE_LABEL[type_key]}")
            lines += [self._moc_line(e, show_project=show_project) for e in section]
            lines.append("")

    def _clean(self) -> None:
        for folder in MANAGED_DIRS:
            shutil.rmtree(self._vault / folder, ignore_errors=True)
        (self._vault / "Home.md").unlink(missing_ok=True)


# --- module helpers --------------------------------------------------------


def _type_of(entry: Entry) -> str:
    return entry.type if entry.type in TYPE_ICON else "note"


def _title(entry: Entry) -> str:
    return entry.title or entry.raw_text[:40]


def _is_archived(entry: Entry) -> bool:
    return entry.type == "task" and entry.status in ("done", "archived")


def _para_category(entry: Entry) -> str:
    if _is_archived(entry):
        return "archive"
    type_key = _type_of(entry)
    if type_key in ("task", "event"):
        return "project" if entry.project else "area"
    return "resource"


def _task_sort_key(entry: Entry) -> tuple:
    rank = {"high": 0, "medium": 1, "low": 2}.get(entry.priority or "", 3)
    return (entry.due_date is None, entry.due_date or datetime.max, rank, entry.id)


def _basename(entry: Entry) -> str:
    return f"{entry.id}-{_slugify(entry.title or entry.raw_text)}"


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "sem-titulo"


def _fs_name(name: str) -> str:
    """Filesystem/wikilink-safe person name (keeps spaces and accents)."""
    return _INVALID_FS.sub("", name).strip() or "sem-nome"


def _frontmatter(fields: dict) -> str:
    """Render YAML frontmatter (values as JSON, a valid YAML subset)."""
    lines = ["---"]
    for key, value in fields.items():
        if value is None or (isinstance(value, list) and not value):
            continue
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def _local_dt(dt: datetime) -> datetime:
    """Interpret a stored (naive UTC) datetime as an aware local datetime."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def _local_date(dt: datetime) -> date:
    return _local_dt(dt).date()


def _plain_date(dt: datetime) -> date:
    """Calendar date as stored (UTC), without shifting into the local timezone.

    Used for review period boundaries, which are logical day markers, not
    wall-clock moments to localize.
    """
    return (dt.replace(tzinfo=None) if dt.tzinfo is not None else dt).date()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    from .config import get_settings
    from .db.engine import make_engine, make_session_factory
    from .logging_setup import setup_logging

    settings = get_settings()
    setup_logging(settings.log_level)

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        result = VaultExporter(session, settings.vault_path).export()
    print(
        f"Export: {result.entries} entrada(s), {result.days} dia(s), "
        f"{result.projects} projeto(s), {result.people} pessoa(s), "
        f"{result.reviews} review(s) -> {result.vault.resolve()}"
    )


if __name__ == "__main__":
    main()
