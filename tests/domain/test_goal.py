from types import SimpleNamespace

import pytest

from reuleauxcoder.domain.agent.agent import Agent
from reuleauxcoder.domain.config.models import Config
from reuleauxcoder.domain.goal import GoalController
from reuleauxcoder.domain.llm.usage import track_usage
from reuleauxcoder.extensions.tools.builtin.goal import (
    CreateGoalTool,
    GetGoalTool,
    UpdateGoalTool,
)


def agent():
    return Agent(SimpleNamespace(model="test"), config=Config(api_key="test"))


def usage(input=100, cached=80, output=10):
    return {
        "input_tokens": input,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "estimated": False,
    }


def test_budget_counts_uncached_input_and_output_and_preserves_usage_on_resume():
    control = agent().goal_controller
    control.create("Finish migration", 30)
    recorder = control.turn_usage_recorder()
    recorder()(usage())
    assert control.state.status == "budget_limited"
    # The current turn's final report remains chargeable after crossing the limit.
    recorder()(usage(10, None, 5))
    assert control.state.tokens_used == 45
    control.update(token_budget=100, change_budget=True)
    assert control.state.status == "budget_limited"
    control.update(status="active")
    assert control.state.tokens_used == 45
    assert control.state.status == "active"


def test_late_usage_is_attributed_to_original_goal_and_new_requests_stop_on_pause():
    control = agent().goal_controller
    first = control.create("First", None)
    recorder = control.turn_usage_recorder()
    inflight = recorder()
    control.stop("paused")
    assert recorder() is None
    inflight(usage())
    assert control.state.tokens_used == 30
    control.clear()
    second = control.create("Second", None)
    inflight(usage())
    assert second.id != first.id
    assert control.state.tokens_used == 0


def test_ledger_recovers_newer_state_and_clear_when_snapshot_is_stale(tmp_path):
    from reuleauxcoder.app.runtime.session_state import bind_session_persistence
    from reuleauxcoder.infrastructure.persistence.session_store import SessionStore

    owner = agent()
    store = SessionStore(tmp_path)
    bind_session_persistence(
        owner.config, owner, store, "goal-session", fingerprint="local"
    )
    owner.goal_controller.create("Verify persisted goal", None)
    owner.goal_controller.record_usage(owner.goal_controller.state.id, usage())
    loaded = store.load("goal-session")
    recovered = GoalController(agent())
    recovered.restore(loaded.runtime_state.goal, loaded.history_events)
    assert recovered.state.objective == "Verify persisted goal"
    assert recovered.state.tokens_used == 30
    assert recovered.state.status == "active"
    stale = loaded.runtime_state.goal
    # Simulate loss of the snapshot writer after the durable ledger append.
    owner._session_persist_callback = lambda: None
    owner.goal_controller.clear()
    loaded = store.load("goal-session")
    recovered.restore(stale, loaded.history_events)
    assert recovered.state is None
    owner.unbind_session_persistence()


def test_model_tools_use_default_budget_and_cannot_resume_or_replace_unfinished_goal():
    from reuleauxcoder.extensions.tools.builtin import builtin_tool_types

    assert {CreateGoalTool, GetGoalTool, UpdateGoalTool}.issubset(builtin_tool_types())
    owner = agent()
    owner.config.goal_default_token_budget = 100

    def bind(tool):
        tool.bind_agent(owner)
        tool.bind_execution(
            tool_call_id=tool.name, session_generation=owner.session_generation
        )
        return tool

    create, read, update = map(
        bind, [CreateGoalTool(), GetGoalTool(), UpdateGoalTool()]
    )
    assert create.execute("Finish the requested migration").success
    assert owner.goal_controller.state.token_budget == 100
    assert not create.execute("Replace it").success
    assert not update.execute("active").success
    assert read.execute().success
    owner.goal_controller.update(objective="Also verify remote mode")
    assert not update.execute("complete").success
    assert owner.goal_controller.state.status == "active"
    assert read.execute().success
    assert update.execute("complete").success
    assert create.execute("Next goal", token_budget=200).success
    owner.subagent_depth = 1
    assert not owner.is_tool_in_scope("create_goal")
    assert not owner.is_tool_in_scope("update_goal")


@pytest.mark.parametrize("budget", [0, -1, True, "100"])
def test_configuration_rejects_invalid_goal_budget(budget):
    assert any(
        "goal.default_token_budget" in error
        for error in Config(api_key="test", goal_default_token_budget=budget).validate()
    )


def test_config_default_and_yaml_override():
    from reuleauxcoder.services.config.loader import ConfigLoader

    loader = ConfigLoader()
    assert loader._parse_config({}).goal_default_token_budget is None
    assert (
        loader._parse_config(
            {"goal": {"default_token_budget": 1234}}
        ).goal_default_token_budget
        == 1234
    )


def test_restore_keeps_snapshot_elapsed_time_and_excludes_process_downtime(monkeypatch):
    import reuleauxcoder.domain.goal as module

    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    owner = agent()
    owner.goal_controller.create("Wait for completion", None)
    clock[0] = 110.0
    snapshot = owner.goal_controller.state.to_dict()
    clock[0] = 1000.0
    restored = GoalController(agent())
    restored.restore(snapshot, owner.history_ledger.events)
    assert restored.state.time_used_seconds == 10
    clock[0] = 1005.0
    assert restored.state.time_used_seconds == 15


def test_request_scope_accounts_main_and_summary_calls_without_double_counting(
    monkeypatch,
):
    from reuleauxcoder.services.llm.client import LLM
    from tests.services.test_llm_client import _FakeChunk, _FakeUsage

    owner = agent()
    owner.goal_controller.create("Long work", None)
    llm = LLM(model="test", api_key="test")
    monkeypatch.setattr(
        llm,
        "_call_with_retry",
        lambda params: iter(
            [_FakeChunk(content="done", usage=_FakeUsage(100, 10, 80))]
        ),
    )
    with track_usage(owner.goal_controller.turn_usage_recorder()):
        llm.chat([{"role": "user", "content": "normal work"}])
        llm.chat([{"role": "user", "content": "summary work"}], max_output_tokens=4096)
    assert owner.goal_controller.state.tokens_used == 60
    assert owner.goal_controller.state.estimated_requests == 0
    llm.chat([{"role": "user", "content": "unrelated request"}])
    assert owner.goal_controller.state.tokens_used == 60
