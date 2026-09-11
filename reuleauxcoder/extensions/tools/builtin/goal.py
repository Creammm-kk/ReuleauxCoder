"""Model-facing goal control: creation by request, completion or blocked status."""

import json

from reuleauxcoder.domain.agent.tool_outcome import ToolOutcome
from reuleauxcoder.extensions.tools.base import backend_handler
from reuleauxcoder.extensions.tools.builtin.control import _AgentControlTool, _invalid


class _GoalTool(_AgentControlTool):
    @backend_handler("local")
    def _execute_local(self, **arguments):
        _, generation = self._identity()
        if generation != self._agent.session_generation:
            return _invalid("Session changed before goal update")
        controller = self._agent.goal_controller
        try:
            if self.name == "create_goal":
                budget = arguments.get(
                    "token_budget",
                    self._agent.config.goal_default_token_budget
                    if self._agent.config
                    else None,
                )
                goal = controller.create(arguments["objective"], budget)
                self._agent._goal_request = (goal.id, goal.objective)
            elif self.name == "update_goal":
                if arguments["status"] not in {"complete", "blocked"}:
                    raise ValueError("Only complete or blocked may be set by the model")
                goal = controller.update(
                    status=arguments["status"], expected_goal=self._agent._goal_request
                )
            else:
                goal = controller.state
                self._agent._goal_request = (goal.id, goal.objective) if goal else None
        except ValueError as error:
            return _invalid(str(error))
        return ToolOutcome(
            summary=f"Goal {goal.status}" if goal else "No goal set",
            content=json.dumps(
                {"goal": goal.to_dict() if goal else None}, ensure_ascii=False
            ),
        )


class GetGoalTool(_GoalTool):
    name = "get_goal"
    description = "Read the current session goal, status, cumulative token/time usage and optional token budget. No arguments."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def execute(self):
        return self.run_backend()


class CreateGoalTool(_GoalTool):
    name = "create_goal"
    description = (
        "Create a persistent session goal only when explicitly requested by the user or system/developer instructions; "
        "do not infer goals from ordinary tasks. An unfinished goal must be edited or cleared by the user first. "
        "Omit token_budget unless explicitly requested: omission uses the configured default (normally unlimited)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
                "description": "The full requested objective and verifiable end state.",
            },
            "token_budget": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional cumulative input minus cached input plus output token budget.",
            },
        },
        "required": ["objective"],
        "additionalProperties": False,
    }

    def execute(self, objective: str, **kwargs):
        return self.run_backend(objective=objective, **kwargs)


class UpdateGoalTool(_GoalTool):
    name = "update_goal"
    description = (
        "Mark the goal complete only when current evidence proves every requirement is satisfied and no required work remains. "
        "Mark blocked only when the same blocker has recurred for at least three consecutive goal turns and no meaningful work "
        "can proceed without user input or an external change. After resume, start a fresh blocked audit. "
        "Do not mark complete because a turn or budget is ending. Pause, resume, objective and budget changes belong to the user. "
        "When completing a budgeted goal, report final token usage returned by this tool."
    )
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["complete", "blocked"]},
        },
        "required": ["status"],
        "additionalProperties": False,
    }

    def execute(self, status: str):
        return self.run_backend(status=status)
