"""Agenda importer tests (BIG #28 §15).

ICS parsing is stdlib-only and bounded; duplicates collapse
on (source, UID); nothing is invented.
"""

import pytest

from coordinator.app.agenda import (
    AgendaRefusedError,
    list_events,
    list_sources,
    parse_ics,
    store_preview,
)

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//NL
BEGIN:VEVENT
UID:evt-001@example
DTSTART:20260918T090000
DTEND:20260918T100000
SUMMARY:Freerunning les UMZ
LOCATION:Sporthal Zeeland
DESCRIPTION:Lesgroep A\\, warming-up
END:VEVENT
BEGIN:VEVENT
UID:evt-002@example
DTSTART:20260919T140000
DTEND:20260919T150000
SUMMARY:Camper klussen
RRULE:FREQ=WEEKLY;COUNT=4
END:VEVENT
END:VCALENDAR
"""


def test_parse_two_events():
    preview = parse_ics(SAMPLE_ICS, source_label="test")
    assert len(preview.events) == 2
    first = preview.events[0]
    assert first.uid == "evt-001@example"
    assert first.title == "Freerunning les UMZ"
    assert first.location == "Sporthal Zeeland"
    assert "warming-up" in first.description
    assert preview.events[1].recurrence.startswith("FREQ=WEEKLY")


def test_missing_uid_derived_and_labelled():
    ics = SAMPLE_ICS.replace("UID:evt-001@example\n", "")
    preview = parse_ics(ics)
    assert preview.events[0].uid.startswith("derived-")
    assert "derived" in preview.events[0].provenance_note


def test_not_a_calendar_refuses():
    with pytest.raises(AgendaRefusedError):
        parse_ics("hello world")


def test_no_events_refuses():
    with pytest.raises(AgendaRefusedError):
        parse_ics("BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR")


def test_empty_refuses():
    with pytest.raises(AgendaRefusedError):
        parse_ics("   ")


def test_store_and_list(tmp_path, monkeypatch):
    import sqlite3
    from coordinator.app.agenda import init_agenda_tables
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "a.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "a-chat.db"))
    from coordinator.app.database import (
        chat_connection,
        init_chat_database,
    )
    init_chat_database()
    with chat_connection() as db:
        init_agenda_tables(db)
        preview = parse_ics(SAMPLE_ICS, source_label="gezinskalender")
        result = store_preview(db, preview)
        assert result["inserted"] == 2
        assert result["updated"] == 0
        events = list_events(db)
        assert len(events) == 2
        sources = list_sources(db)
        assert sources[0]["label"] == "gezinskalender"


def test_reimport_same_label_dedups():
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    from coordinator.app.agenda import init_agenda_tables
    init_agenda_tables(db)
    first = store_preview(
        db, parse_ics(SAMPLE_ICS, source_label="gezin"))
    assert first["inserted"] == 2
    second = store_preview(
        db, parse_ics(SAMPLE_ICS, source_label="gezin"))
    assert second["inserted"] == 0
    assert second["updated"] == 2
    assert second["source_id"] == first["source_id"]
    assert len(list_events(db)) == 2
    db.close()
