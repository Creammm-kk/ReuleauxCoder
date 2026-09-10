"""Frontend identity and capabilities accepted by the command application."""

from dataclasses import dataclass, field
from enum import Enum


class UICapability(str, Enum):
    TEXT_INPUT = "text_input"
    STREAM_OUTPUT = "stream_output"
    PALETTE = "palette"
    BUTTONS = "buttons"
    MENUS = "menus"
    TABS = "tabs"
    MODAL = "modal"
    DIFF_REVIEW = "diff_review"
    TEXT_SELECT = "text_select"
    TEXT_EDIT = "text_edit"
    SECURE_TEXT_INPUT = "secure_text_input"


@dataclass(frozen=True, slots=True)
class UIProfile:
    ui_id: str
    display_name: str
    capabilities: frozenset[UICapability] = field(default_factory=frozenset)
