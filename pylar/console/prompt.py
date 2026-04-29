"""Interactive CLI prompts — ask, confirm, choice.

Mirrors Laravel's ``$this->ask()``, ``$this->confirm()``, and
``$this->choice()`` so console commands can gather input
interactively without pulling in a heavy TUI library.

All prompts write to stderr so they don't interfere with stdout
output that callers might pipe. When stdin is not a TTY (CI, Docker)
each function returns its *default* immediately.
"""

from __future__ import annotations

import sys


def ask(question: str, *, default: str = "") -> str:
    """Prompt the user for a string answer.

    Returns *default* when stdin is not a TTY.
    """
    if not sys.stdin.isatty():
        return default
    prompt = f"{question} [{default}] " if default else f"{question} "
    sys.stderr.write(prompt)
    sys.stderr.flush()
    answer = input().strip()
    return answer if answer else default


def confirm(question: str, *, default: bool = False) -> bool:
    """Ask a yes/no question. Returns *default* when non-interactive."""
    if not sys.stdin.isatty():
        return default
    hint = "Y/n" if default else "y/N"
    sys.stderr.write(f"{question} [{hint}] ")
    sys.stderr.flush()
    answer = input().strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "1", "true")


def choice(
    question: str,
    options: list[str],
    *,
    default: int = 0,
) -> str:
    """Present a numbered list and return the chosen option.

    Returns ``options[default]`` when non-interactive.
    """
    if not options:
        raise ValueError("choice() requires at least one option")
    if not sys.stdin.isatty():
        return options[default]
    sys.stderr.write(f"{question}\n")
    for i, option in enumerate(options):
        marker = " *" if i == default else ""
        sys.stderr.write(f"  [{i}] {option}{marker}\n")
    sys.stderr.write(f"Choice [{default}]: ")
    sys.stderr.flush()
    raw = input().strip()
    if not raw:
        return options[default]
    try:
        idx = int(raw)
        if 0 <= idx < len(options):
            return options[idx]
    except ValueError:
        pass
    return options[default]
