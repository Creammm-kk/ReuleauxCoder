"""Shared presentation contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class ApprovalRuleView:
    """Structured presentation model for one configured approval rule."""

    scope: str
    action: str
    tool_source: str | None = None
    mcp_server: str | None = None
    tool_name: str | None = None
    effect_class: str | None = None
    profile: str | None = None
    pattern: str | None = None
    scope_key: str | None = None
    source: str = "builtin"


@dataclass(slots=True)
class ApprovalEffectiveToolView:
    name: str
    action: str
    source: str


@dataclass(slots=True)
class ApprovalEffectivePolicyView:
    """Structured presentation model for one MCP server's effective policy."""

    server_name: str
    action: str
    source: str
    tools: list[ApprovalEffectiveToolView] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ApprovalEditorHint:
    supports_text_command: bool
    set_command_format: str
    future_ui_editor: bool
    targets: tuple[str, ...]


@dataclass(slots=True)
class ApprovalToolPolicyView:
    """Effective approval policy for a single callable tool."""

    tool_name: str
    action: str
    source: str
    tool_source: str
    scope: str


@dataclass(slots=True)
class ApprovalView:
    """Structured approval rules view payload."""

    default_mode: str
    default_mode_source: str = "builtin"
    rules: list[ApprovalRuleView] = field(default_factory=list)
    tool_policies: list[ApprovalToolPolicyView] = field(default_factory=list)
    effective_mcp_policies: list[ApprovalEffectivePolicyView] = field(
        default_factory=list
    )
    editor_hint: ApprovalEditorHint = field(
        default_factory=lambda: ApprovalEditorHint(False, "", False, ())
    )
    view_type: str = "approval_rules"

    def to_payload(self) -> dict[str, Any]:
        return {
            "default_mode": self.default_mode,
            "default_mode_source": self.default_mode_source,
            "rules": [
                {
                    "scope": rule.scope,
                    "action": rule.action,
                    "tool_source": rule.tool_source,
                    "mcp_server": rule.mcp_server,
                    "tool_name": rule.tool_name,
                    "effect_class": rule.effect_class,
                    "profile": rule.profile,
                    "pattern": rule.pattern,
                    "scope_key": rule.scope_key,
                    "source": rule.source,
                }
                for rule in self.rules
            ],
            "tool_policies": [
                {
                    "tool_name": policy.tool_name,
                    "action": policy.action,
                    "source": policy.source,
                    "tool_source": policy.tool_source,
                    "scope": policy.scope,
                }
                for policy in self.tool_policies
            ],
            "effective_mcp_policies": [
                {
                    "server_name": item.server_name,
                    "action": item.action,
                    "source": item.source,
                    "tools": [
                        {
                            "name": tool.name,
                            "action": tool.action,
                            "source": tool.source,
                        }
                        for tool in item.tools
                    ],
                }
                for item in self.effective_mcp_policies
            ],
            "editor_hint": {
                "supports_text_command": self.editor_hint.supports_text_command,
                "set_command_format": self.editor_hint.set_command_format,
                "future_ui_editor": self.editor_hint.future_ui_editor,
                "targets": list(self.editor_hint.targets),
            },
        }
