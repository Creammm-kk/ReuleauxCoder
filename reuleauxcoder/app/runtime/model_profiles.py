"""Apply a main-model profile consistently across commands and session restore."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reuleauxcoder.domain.config.models import (
    Config,
    ModelProfileConfig,
    resolve_context_strategies,
)
from reuleauxcoder.services.llm.factory import reconfigure_llm_from_settings

if TYPE_CHECKING:
    from reuleauxcoder.domain.agent.agent import Agent


def apply_main_model_profile(
    config: Config,
    agent: Agent,
    profile_name: str,
    profile: ModelProfileConfig,
    *,
    debug_trace: bool | None = None,
) -> None:
    """Update the model, context policy and active profile as one runtime operation."""
    if debug_trace is None:
        debug_trace = getattr(
            agent.llm, "debug_trace", getattr(config, "llm_debug_trace", False)
        )
    reconfigure_llm_from_settings(agent.llm, profile, debug_trace=debug_trace)
    agent.context.reconfigure(
        profile.max_context_tokens,
        **resolve_context_strategies(config.context, getattr(profile, "context", None)),
    )
    agent.active_main_model_profile = profile_name
