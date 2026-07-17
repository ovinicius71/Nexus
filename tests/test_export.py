"""Tests for the PARA + Zettelkasten + LYT Obsidian export (Phase 4)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository
from organizer.export import VaultExporter, _slugify
from organizer.llm.schema import EntryClassification, EntryType, Priority


def _seed(session: Session) -> EntryRepository:
    repo = EntryRepository(session)
    task = repo.add_raw_entry("comprar leite")
    repo.apply_classification(
        task,
        EntryClassification(type=EntryType.task, title="Comprar leite",
                            due_date=date(2026, 7, 18), priority=Priority.high, project="casa"),
        "{}",
    )
    idea = repo.add_raw_entry("app que resume minhas notas")
    repo.apply_classification(
        idea,
        EntryClassification(type=EntryType.idea, title="App de resumo",
                            project="estagio", people=["Ana", "Bruno"]),
        "{}",
    )
    event = repo.add_raw_entry("reuniao com Ana")
    repo.apply_classification(
        event, EntryClassification(type=EntryType.event, title="Reuniao", people=["Ana"]), "{}"
    )
    note = repo.add_raw_entry("o cafe abre as 7h")
    repo.apply_classification(note, EntryClassification(type=EntryType.note, title="Cafe"), "{}")
    return repo


def _read(base, *parts):
    return base.joinpath(*parts).read_text(encoding="utf-8")


def test_result_counts(session: Session, tmp_path) -> None:
    _seed(session)
    result = VaultExporter(session, tmp_path).export()
    assert result.entries == 4
    assert result.days == 1
    assert result.projects == 2  # casa, estagio
    assert result.people == 2  # Ana, Bruno


def test_atomic_notes_flat_in_slipbox_with_meaningful_links(session: Session, tmp_path) -> None:
    _seed(session)
    VaultExporter(session, tmp_path).export()

    slip = list((tmp_path / "Slipbox").glob("*.md"))
    assert len(slip) == 4  # one atomic note per entry, flat

    idea = _read(tmp_path, "Slipbox", "2-app-de-resumo.md")
    assert 'tags: ["idea", "para/resource", "project/estagio"]' in idea
    assert "**Up:** [[Resources/Ideias|Ideias]]" in idea  # LYT up-link (connects the graph)
    assert "**Projeto:** [[Projects/estagio|estagio]]" in idea
    assert "[[Areas/People/Ana|Ana]]" in idea and "[[Areas/People/Bruno|Bruno]]" in idea
    # no structural noise: atomic notes don't link to days
    assert "Journal/" not in idea

    # a bare note (no project/people) still has an up-link, so it isn't isolated
    cafe = _read(tmp_path, "Slipbox", "4-cafe.md")
    assert "**Up:** [[Resources/Notas|Notas]]" in cafe


def test_para_folders_and_moc_membership(session: Session, tmp_path) -> None:
    _seed(session)
    VaultExporter(session, tmp_path).export()

    # Projects: MOC per project, links its atomic notes, no redundant self-link
    casa = _read(tmp_path, "Projects", "casa.md")
    assert "[[Slipbox/1-comprar-leite|Comprar leite]]" in casa
    assert "[[Projects/casa" not in casa

    # Areas: loose task list + agenda + people
    assert "[[Slipbox/1-comprar-leite|Comprar leite]]" in _read(tmp_path, "Areas", "Tarefas.md")
    assert "[[Slipbox/3-reuniao|Reuniao]]" in _read(tmp_path, "Areas", "Agenda.md")
    ana = _read(tmp_path, "Areas", "People", "Ana.md")
    assert "[[Slipbox/2-app-de-resumo|App de resumo]]" in ana
    assert "[[Slipbox/3-reuniao|Reuniao]]" in ana

    # Resources: ideas & notes MOCs
    assert "[[Slipbox/2-app-de-resumo|App de resumo]]" in _read(tmp_path, "Resources", "Ideias.md")
    assert "[[Slipbox/4-cafe|Cafe]]" in _read(tmp_path, "Resources", "Notas.md")


def test_home_links_every_section(session: Session, tmp_path) -> None:
    _seed(session)
    VaultExporter(session, tmp_path).export()
    home = _read(tmp_path, "Home.md")
    for target in [
        "[[Projects/casa", "[[Projects/estagio", "[[Areas/Tarefas", "[[Areas/Agenda",
        "[[Areas/People/Ana", "[[Resources/Ideias", "[[Resources/Notas", "[[Archive/Concluidas",
    ]:
        assert target in home


def test_done_task_moves_to_archive(session: Session, tmp_path) -> None:
    repo = _seed(session)
    task = repo.list_open_tasks()[0]  # Comprar leite (project casa)
    repo.mark_done(task)

    result = VaultExporter(session, tmp_path).export()

    archive = _read(tmp_path, "Archive", "Concluidas.md")
    assert "- [x] [[Slipbox/1-comprar-leite|Comprar leite]]" in archive
    assert "1-comprar-leite" not in _read(tmp_path, "Areas", "Tarefas.md")
    # casa had only that (now archived) entry -> its Project MOC is dropped
    assert not (tmp_path / "Projects" / "casa.md").exists()
    assert result.projects == 1  # estagio only


def test_journal_per_day(session: Session, tmp_path) -> None:
    repo = EntryRepository(session)
    today = repo.add_raw_entry("de hoje")
    repo.apply_classification(today, EntryClassification(type=EntryType.note, title="Hoje"), "{}")
    old = repo.add_raw_entry("de ontem")
    repo.apply_classification(old, EntryClassification(type=EntryType.note, title="Ontem"), "{}")
    old.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.commit()

    result = VaultExporter(session, tmp_path).export()
    assert result.days == 2
    assert len(list((tmp_path / "Journal").glob("*.md"))) == 2


def test_export_is_idempotent(session: Session, tmp_path) -> None:
    _seed(session)
    VaultExporter(session, tmp_path).export()
    first = {p.relative_to(tmp_path): p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.md")}
    VaultExporter(session, tmp_path).export()
    second = {p.relative_to(tmp_path): p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.md")}
    assert first == second


def test_clean_removes_stale_slipbox_note(session: Session, tmp_path) -> None:
    repo = EntryRepository(session)
    entry = repo.add_raw_entry("titulo velho")
    repo.apply_classification(
        entry, EntryClassification(type=EntryType.note, title="Titulo velho"), "{}"
    )
    VaultExporter(session, tmp_path).export()
    assert (tmp_path / "Slipbox" / "1-titulo-velho.md").exists()

    entry.title = "Titulo novo"
    session.commit()
    VaultExporter(session, tmp_path).export()

    assert not (tmp_path / "Slipbox" / "1-titulo-velho.md").exists()  # old slug wiped
    assert (tmp_path / "Slipbox" / "1-titulo-novo.md").exists()


def test_export_links_accepted_connections(session: Session, tmp_path) -> None:
    repo = EntryRepository(session)
    a = repo.add_raw_entry("primeira ideia")
    repo.apply_classification(a, EntryClassification(type=EntryType.idea, title="Ideia A"), "{}")
    b = repo.add_raw_entry("segunda ideia")
    repo.apply_classification(b, EntryClassification(type=EntryType.idea, title="Ideia B"), "{}")
    conn = repo.add_pending_connection(a.id, b.id, 0.8)
    repo.set_connection_accepted(conn.id, True)

    VaultExporter(session, tmp_path).export()
    note = _read(tmp_path, "Slipbox", f"{a.id}-ideia-a.md")
    assert "**Relacionadas:**" in note
    assert f"[[Slipbox/{b.id}-ideia-b|Ideia B]]" in note


def test_slugify() -> None:
    assert _slugify("App de Hábitos!") == "app-de-habitos"
    assert _slugify("TCC — capítulo 2") == "tcc-capitulo-2"
    assert _slugify("///") == "sem-titulo"
