import json
from dataclasses import asdict

from reuleauxcoder.domain.history import HistoryLedger
from reuleauxcoder.infrastructure.persistence.history_query import SessionHistory


def _history(tmp_path):
    directory = tmp_path / "session_test"
    directory.mkdir()
    ledger = HistoryLedger(
        session_id="session_test", sink_path=directory / "events.jsonl"
    )
    return ledger, SessionHistory(tmp_path), directory


def test_large_message_pages_preserve_unicode_and_event_identity(tmp_path):
    ledger, history, _ = _history(tmp_path)
    content = "中文 👩🏽‍💻 abc\n" * 10_000
    event = ledger.append_message(
        {"role": "user", "content": content}, source="user", turn_id="turn_1"
    )
    cursor = None
    restored = []
    while True:
        page = history.read("session_test", cursor=cursor, max_chars=317)
        assert len(page.records) == 1
        record = page.records[0]
        assert record.event_id == event.event_id
        assert record.turn_id == "turn_1"
        assert record.offset == sum(map(len, restored))
        assert len(record.content) <= 317
        restored.append(record.content)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert "".join(restored) == content


def test_search_has_bounded_scan_and_finds_chunk_boundary_matches(tmp_path):
    ledger, history, _ = _history(tmp_path)
    content = "x" * (4096 * 260 - 3) + "Find中文needle" + "x" * 50
    ledger.append_message({"role": "user", "content": content}, source="user")
    first = history.search("session_test", "find中文needle")
    assert not first.records
    assert first.next_cursor is not None
    second = history.search("session_test", "find中文needle", cursor=first.next_cursor)
    assert len(second.records) == 1
    assert "Find中文needle" in second.records[0].content
    assert second.next_cursor is None


def test_search_scan_budget_includes_filtered_internal_events(tmp_path):
    ledger, history, _ = _history(tmp_path)
    ledger.append("context_view_committed", {"items": "internal" * 160_000})
    event = ledger.append_message({"role": "user", "content": "needle"}, source="user")
    first = history.search("session_test", "needle")
    assert not first.records
    assert first.next_cursor is not None
    second = history.search("session_test", "needle", cursor=first.next_cursor)
    assert [record.event_id for record in second.records] == [event.event_id]


def test_index_only_parses_appends_and_rebuilds_after_source_replacement(
    tmp_path, monkeypatch
):
    ledger, history, directory = _history(tmp_path)
    ledger.append_message({"role": "user", "content": "old"}, source="user")
    history.read("session_test")
    original = json.loads
    parsed_events = []

    def loads(value, *args, **kwargs):
        result = original(value, *args, **kwargs)
        if isinstance(result, dict) and "event_id" in result:
            parsed_events.append(result)
        return result

    monkeypatch.setattr(json, "loads", loads)
    history.read("session_test")
    assert parsed_events == []
    ledger.append_message({"role": "assistant", "content": "new"}, source="assistant")
    page = history.read("session_test", reverse=True, limit=1)
    assert page.records[0].content == "new"
    assert len(parsed_events) == 2
    replacement = directory / "replacement.jsonl"
    replacement.write_text(
        (directory / "events.jsonl").read_text().replace('"new"', '"replacement"')
    )
    replacement.replace(directory / "events.jsonl")
    assert (
        history.read("session_test", reverse=True, limit=1).records[0].content
        == "replacement"
    )


def test_incomplete_tail_is_retried_and_recovery_gaps_are_visible(tmp_path):
    ledger, history, directory = _history(tmp_path)
    event = ledger.append_message({"role": "user", "content": "before"}, source="user")
    source = directory / "events.jsonl"
    good = source.read_bytes()
    source.write_bytes(good + b'{"broken":')
    first = history.read("session_test")
    assert first.indexing
    assert first.awaiting_tail
    assert first.records[0].event_id == event.event_id
    assert first.skipped_records == 0
    with source.open("ab") as stream:
        stream.write(b"\n")
    ledger.append_message({"role": "assistant", "content": "after"}, source="assistant")
    second = history.read("session_test")
    assert not second.indexing
    assert not second.awaiting_tail
    assert second.skipped_records == 1
    assert [record.content for record in second.records] == ["before", "after"]


def test_index_batches_continue_without_losing_or_repeating_messages(
    tmp_path, monkeypatch
):
    import reuleauxcoder.infrastructure.persistence.history_query as module

    monkeypatch.setattr(module, "INDEX_BYTES", 1024)
    ledger, history, _ = _history(tmp_path)
    expected = [
        ledger.append_message(
            {"role": "user", "content": f"message {index}"}, source="user"
        ).event_id
        for index in range(100)
    ]
    cursor, found = None, []
    while True:
        page = history.read("session_test", cursor=cursor)
        found.extend(record.event_id for record in page.records)
        cursor = page.next_cursor
        if cursor is None:
            assert not page.indexing
            break
    assert found == expected


def test_encoded_page_budget_includes_metadata_and_escaped_content(tmp_path):
    ledger, history, _ = _history(tmp_path)
    source = '\x00\n"\\' * 6000
    ledger.append_message({"role": "user", "content": source}, source="user")
    for _ in range(200):
        ledger.append_message({"role": "assistant", "content": ""}, source="assistant")
    cursor, contents, ids = None, [], set()
    while True:
        page = history.read("session_test", limit=200, cursor=cursor)
        assert len(json.dumps(asdict(page), ensure_ascii=False)) < 25_000
        contents.extend(record.content for record in page.records)
        ids.update(record.event_id for record in page.records)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert "".join(contents) == source
    assert len(ids) == 201
