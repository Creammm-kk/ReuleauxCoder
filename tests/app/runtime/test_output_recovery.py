from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from reuleauxcoder.app.runtime.session_state import (
    apply_session_runtime_state,
    bind_session_persistence,
)
from reuleauxcoder.domain.agent.agent import Agent
from reuleauxcoder.domain.agent.events import AgentEvent
from reuleauxcoder.domain.config.models import Config
from reuleauxcoder.domain.history import HistoryLedger
from reuleauxcoder.infrastructure.persistence.session_store import (
    SessionRestoreError,
    SessionStore,
)


_WORKER = """
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from reuleauxcoder.app.runtime.session_state import bind_session_persistence
from reuleauxcoder.domain.agent.agent import Agent
from reuleauxcoder.domain.agent.events import AgentEvent
from reuleauxcoder.domain.config.models import Config
from reuleauxcoder.infrastructure.persistence.session_store import SessionStore

config = Config(api_key='test', session_dir=sys.argv[1])
agent = Agent(SimpleNamespace(model='model', debug_trace=False), tools=[], config=config)
store = SessionStore(Path(sys.argv[1]))
sid = store.generate_session_id()
bind_session_persistence(config, agent, store, sid, fingerprint='local')
agent._current_turn_id = 'turn-before-crash'
agent._append_message({'role': 'user', 'content': 'Please keep this conversation'}, source='user_input')
if sys.argv[2] == 'stream':
    durable = threading.Event()
    pending = {'response', 'reasoning', 'tool'}
    write = agent.history_ledger._write_sink_events
    def observe_write(events):
        write(events)
        for event in events:
            if event.kind == 'output_checkpoint':
                pending.discard(event.payload['kind'])
        if not pending:
            durable.set()
    agent.history_ledger._write_sink_events = observe_write
    for text in ['Already received ', '中文👩🏽‍💻']:
        agent._emit_event(AgentEvent.stream_token(text))
    agent._emit_event(AgentEvent.stream_reasoning('Reasoning before interruption'))
    agent._emit_event(AgentEvent.tool_output_delta('shell', 'Process output before interruption', tool_call_id='tool-crash'))
    if not durable.wait(10):
        raise RuntimeError('output checkpoint did not reach disk')
print(sid, flush=True)
threading.Event().wait()
"""


@pytest.mark.parametrize("phase", ["first_message", "stream"])
def test_killed_backend_restores_durable_content_without_shutdown(tmp_path, phase):
    process = subprocess.Popen(
        [sys.executable, "-c", _WORKER, str(tmp_path), phase],
        cwd=Path(__file__).resolve().parents[3],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            session_id = pool.submit(process.stdout.readline).result(timeout=20).strip()
        finally:
            # SIGKILL / TerminateProcess bypasses all finally and exit handlers.
            process.kill()
            process.wait(timeout=10)
    assert session_id, process.stderr.read()
    process.stdout.close()
    process.stderr.close()

    store = SessionStore(tmp_path)
    assert store.list_result().sessions[0].id == session_id
    loaded = store.load(session_id)
    assert [message["content"] for message in loaded.messages] == [
        "Please keep this conversation"
    ]
    if phase == "stream":
        text = "\n".join(entry["content"] for entry in loaded.get_recent_conversation())
        for expected in [
            "Already received 中文👩🏽‍💻",
            "Reasoning before interruption",
            "Process output before interruption",
        ]:
            assert expected in text
        assert text.count("— session interrupted]") == 3
        assert (
            sum(event.kind == "output_checkpoint" for event in loaded.history_events)
            == 3
        ), "chunks are batched, including when the upstream goes silent"

    config = Config(api_key="test", session_dir=str(tmp_path))
    agent = Agent(
        SimpleNamespace(model="model", debug_trace=False), tools=[], config=config
    )
    apply_session_runtime_state(loaded, config, agent)
    assert all(
        "before interruption" not in str(message)
        and "Already received" not in str(message)
        for message in agent.messages
    )
    assert not agent.pending_user_steering(), (
        "recovery does not automatically resubmit work"
    )


def test_committed_message_acknowledges_chunks_without_duplicate_recovery(tmp_path):
    config = Config(api_key="test", session_dir=str(tmp_path))
    agent = Agent(
        SimpleNamespace(model="model", debug_trace=False), tools=[], config=config
    )
    store = SessionStore(tmp_path)
    sid = store.generate_session_id()
    bind_session_persistence(config, agent, store, sid, fingerprint="local")
    try:
        agent._append_message(
            {"role": "user", "content": "Request"}, source="user_input"
        )
        agent._emit_event(AgentEvent.stream_reasoning("Reasoning"))
        agent._emit_event(AgentEvent.stream_token("Complete response"))
        agent._append_message(
            {"role": "assistant", "content": "Complete response"},
            source="assistant_response",
        )
        # Load before the deferred replay snapshot: the commit is in the ledger.
        loaded = store.load(sid)
        assert loaded.get_recent_conversation() == [
            {"role": "user", "content": "Request"},
            {"role": "assistant", "content": "Complete response"},
        ]
        committed = next(
            event
            for event in loaded.history_events
            if event.kind == "message_committed" and event.role == "assistant"
        )
        assert len(committed.payload["output_stream_ids"]) == 2
    finally:
        agent.unbind_session_persistence()


def test_rebinding_after_a_torn_tail_keeps_the_next_message(tmp_path):
    store = SessionStore(tmp_path)
    config = Config(api_key="test", session_dir=str(tmp_path))
    agent = Agent(
        SimpleNamespace(model="model", debug_trace=False), tools=[], config=config
    )
    sid = store.generate_session_id()
    bind_session_persistence(config, agent, store, sid, fingerprint="local")
    agent._append_message({"role": "user", "content": "Original"}, source="user_input")
    agent.unbind_session_persistence()
    path = store.get_session_events_path(sid)
    with path.open("ab") as stream:
        stream.write(b'{"seq":999,"unfinished":')
    recovered = store.load(sid)
    assert any(issue.phase == "history_decode" for issue in recovered.restore_issues)
    ledger = HistoryLedger(
        recovered.history_events,
        next_seq_floor=recovered.history_next_seq_floor,
        session_id=sid,
    )
    ledger.bind_jsonl(path)
    ledger.append_message(
        {"role": "assistant", "content": "After recovery"}, source="assistant_response"
    )
    loaded = store.load(sid)
    assert [message["content"] for message in loaded.messages] == ["Original"]
    assert [entry["content"] for entry in loaded.get_recent_conversation()] == [
        "Original",
        "After recovery",
    ]
    assert not loaded.history_behavior_projection_safe, (
        "readable recovery does not authorize behavioral replay"
    )


def test_finished_tool_result_is_durable_before_the_next_model_message(tmp_path):
    config = Config(api_key="test", session_dir=str(tmp_path))
    agent = Agent(
        SimpleNamespace(model="model", debug_trace=False), tools=[], config=config
    )
    store = SessionStore(tmp_path)
    sid = store.generate_session_id()
    bind_session_persistence(config, agent, store, sid, fingerprint="local")
    try:
        agent._append_message(
            {"role": "user", "content": "Run the tool"}, source="user_input"
        )
        agent._append_message(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tool",
                        "type": "function",
                        "function": {"name": "shell", "arguments": "{}"},
                    }
                ],
            },
            source="assistant_tool_calls",
        )
        agent._emit_event(
            AgentEvent.tool_output_delta("shell", "first line", tool_call_id="tool")
        )
        agent._emit_event(
            AgentEvent.tool_call_end(
                "shell", "first line\nfinal line", tool_call_id="tool", success=True
            )
        )
        recovered = store.load(sid).get_recent_conversation()
        text = "\n".join(entry["content"] for entry in recovered)
        assert text.count("first line") == 1
        assert "final line" in text
        agent._append_message(
            {
                "role": "tool",
                "tool_call_id": "tool",
                "content": "first line\nfinal line",
            },
            source="tool_result",
        )
        assert "Recovered" not in str(store.load(sid).get_recent_conversation())
    finally:
        agent.unbind_session_persistence()


def test_invalid_output_checkpoint_does_not_hide_committed_history(tmp_path):
    store = SessionStore(tmp_path)
    sid = store.save([{"role": "user", "content": "Original"}], "model")
    loaded = store.load(sid)
    event = loaded.history_events[-1].to_dict()
    event.update(
        kind="output_checkpoint",
        seq=event["seq"] + 1,
        event_id="bad-output",
        payload={"stream_id": "stream", "kind": "response", "text": 123},
    )
    with store.get_session_events_path(sid).open("a") as stream:
        stream.write(json.dumps(event) + "\n")
    recovered = store.load(sid)
    assert recovered.get_recent_conversation() == [
        {"role": "user", "content": "Original"}
    ]
    assert any(issue.phase == "history_decode" for issue in recovered.restore_issues)


def test_failed_disk_flush_leaves_the_previous_snapshot_readable(tmp_path, monkeypatch):
    store = SessionStore(tmp_path)
    sid = store.save([{"role": "user", "content": "Keep this snapshot"}], "model")

    def failed_flush(descriptor):
        raise OSError("disk flush failed")

    monkeypatch.setattr("os.fsync", failed_flush)
    with pytest.raises(SessionRestoreError):
        store.save([{"role": "user", "content": "Replacement"}], "model", sid)
    assert (
        SessionStore(tmp_path).load(sid).messages[0]["content"] == "Keep this snapshot"
    )
