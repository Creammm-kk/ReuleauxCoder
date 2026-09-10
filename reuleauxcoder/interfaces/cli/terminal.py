"""Small resize-safe Rich primitives shared by CLI presenters."""

from rich.text import Text

from reuleauxcoder.presentation.policy import fold_text
from reuleauxcoder.interfaces.cli.theme import CLITheme, DEFAULT_CLI_THEME


def build_diff_text(
    result: str,
    *,
    max_lines: int | None = None,
    max_chars: int | None = None,
    theme: CLITheme = DEFAULT_CLI_THEME,
) -> Text:
    """Build a themed diff renderable for history rows or review frames."""
    if max_lines is not None and max_chars is not None:
        result = fold_text(result, max_lines=max_lines, max_chars=max_chars)
    text = Text()
    lines = result.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("@@"):
            style = theme.diff_header
        elif line.startswith("+++"):
            style = theme.diff_addition
        elif line.startswith("---"):
            style = theme.diff_deletion
        elif line.startswith("+"):
            style = theme.diff_addition
        elif line.startswith("-"):
            style = theme.diff_deletion
        elif line.startswith("… (output folded;"):
            style = theme.diff_fold
        else:
            style = theme.diff_context
        text.append(line, style=style)
        if index < len(lines) - 1:
            text.append("\n")
    return text
