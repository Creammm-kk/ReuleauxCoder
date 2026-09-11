from inspect import Parameter, signature

from reuleauxcoder.extensions.tools.backend import LocalToolBackend
from reuleauxcoder.extensions.tools.builtin import builtin_tool_types
from reuleauxcoder.extensions.tools.registry import build_tools, iter_tool_classes


def test_factory_preserves_registered_tool_types_and_schema_order() -> None:
    tool_types = builtin_tool_types()
    assert tool_types == iter_tool_classes()
    assert len(set(tool_types)) == len(tool_types)
    assert tuple(type(tool) for tool in build_tools(LocalToolBackend())) == tool_types


def test_build_tools_requires_an_explicit_backend() -> None:
    assert signature(build_tools).parameters["backend"].default is Parameter.empty
