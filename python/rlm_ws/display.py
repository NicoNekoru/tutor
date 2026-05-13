"""Terminal presentation for the rlm-ws tutor.

Layout:

    rlm-ws  intro to calculus
    user · gpt-5.4-mini
    ──────────────────────────────────────────

      ›  how does the chain rule work?

         If y = f(g(x)), then dy/dx = f'(g(x)) · g'(x).

      ›  /mastery

Every line sits at a two-column left margin. The chevron marks
student turns; the Prof's reply is unlabeled indented prose.
Slash-command completion is shown as the student types ``/``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator, Iterable, Iterator, Sequence

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style
from rich.console import Console, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table
from rich.tree import Tree


class C:
    accent = "cyan"
    student = "green"
    dim = "grey50"
    muted = "grey70"
    ok = "green"
    warn = "yellow"
    err = "red"


MARGIN = 2
INDENT = " " * MARGIN
BODY_INDENT = " " * (MARGIN + 3)
BODY_PAD = (0, 0, 0, MARGIN + 3)

CHEVRON = "›"
TICK = "✓"
CROSS = "✗"
BANG = "!"
DOT = "·"
ARROW = "→"


console: Console = Console(highlight=False, soft_wrap=False)
err_console: Console = Console(stderr=True, highlight=False)


def _print(markup: str) -> None:
    console.print(f"{INDENT}{markup}")


def _blank() -> None:
    console.print()


def divider() -> None:
    console.print(Rule(style=C.dim))


def section(title: str) -> None:
    _blank()
    console.print(Rule(f"[{C.dim}]{title}[/]", style=C.dim, align="left"))


# Status.

def success(msg: str) -> None:
    _print(f"[bold {C.ok}]{TICK}[/]  {msg}")


def warn(msg: str) -> None:
    _print(f"[bold {C.warn}]{BANG}[/]  {msg}")


def error(msg: str) -> None:
    err_console.print(f"{INDENT}[bold {C.err}]{CROSS}[/]  {msg}")


def info(msg: str) -> None:
    _print(f"[{C.dim}]{DOT}[/]  {msg}")


def hint(msg: str) -> None:
    _print(f"[{C.dim}]{msg}[/]")


# Headers.

def header(title: str, subtitle: str = "") -> None:
    _blank()
    _print(f"[bold {C.accent}]{title}[/]")
    if subtitle:
        _print(f"[{C.dim}]{subtitle}[/]")
    divider()


def welcome_banner(
    course: str,
    student: str,
    model: str,
    *,
    extra_lines: Iterable[str] = (),
) -> None:
    _blank()
    title = f"[bold {C.accent}]rlm-ws[/]"
    if course:
        title += f"  {course}"
    _print(title)
    _print(
        f"[{C.student}]{student}[/]  [{C.dim}]{DOT}[/]  "
        f"[{C.accent}]{model or 'offline'}[/]"
    )
    for line in extra_lines:
        _print(f"[{C.dim}]{line}[/]")
    divider()


def slash_help(commands: Sequence[tuple[str, str]]) -> None:
    table = Table.grid(padding=(0, 3))
    table.add_column(style=f"bold {C.accent}", no_wrap=True)
    table.add_column(style=C.muted)
    for cmd, desc in commands:
        table.add_row(cmd, desc)
    _blank()
    console.print(Padding(table, (0, 0, 0, MARGIN)))
    _blank()


def model_choices(provider: str, current: str, models: Sequence[str]) -> None:
    table = _bare_table("models")
    table.add_column("#", justify="right", style=C.dim)
    table.add_column("model")
    for index, model in enumerate(models, start=1):
        label = model
        if model == current:
            label = f"[bold {C.accent}]{model}[/] [{C.dim}]current[/]"
        table.add_row(str(index), label)

    _blank()
    _print(f"[{C.dim}]provider[/]  {provider}")
    _print(f"[{C.dim}]current [/][{C.accent}]{current}[/]")
    if models:
        console.print(Padding(table, (0, 0, 0, MARGIN)))
    _print(f"[{C.dim}]Enter a number from the list or any model ID.[/]")
    _blank()


# Prompt: slash-command completion + readline editing.

class _SlashCompleter(Completer):
    """Show a popup with matching slash commands as the user types."""

    def __init__(self, commands: Sequence[tuple[str, str]]) -> None:
        self._commands: list[tuple[str, str]] = list(commands)

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        space = text.find(" ")
        if space != -1 and document.cursor_position > space:
            return
        word = text if space == -1 else text[:space]
        for cmd, desc in self._commands:
            if cmd.startswith(word):
                yield Completion(
                    cmd,
                    start_position=-len(word),
                    display=cmd,
                    display_meta=desc,
                )


_PROMPT_STYLE: Style = Style.from_dict({
    "prompt-margin": "",
    "prompt-chevron": "bold ansigreen",
    "completion-menu": "bg:#1c1c1c",
    "completion-menu.completion": "bg:#1c1c1c #c8c8c8",
    "completion-menu.completion.current": "bg:#3a3a3a #ffffff bold",
    "completion-menu.meta.completion": "bg:#1c1c1c fg:#7a7a7a",
    "completion-menu.meta.completion.current": "bg:#3a3a3a fg:#cccccc",
    "scrollbar.background": "bg:#141414",
    "scrollbar.button": "bg:#3a3a3a",
})


_prompt_session: PromptSession[str] | None = None
_prompt_sig: tuple[tuple[str, str], ...] | None = None


def _get_prompt_session(
    commands: tuple[tuple[str, str], ...],
) -> PromptSession[str]:
    global _prompt_session, _prompt_sig
    if _prompt_session is None or _prompt_sig != commands:
        _prompt_sig = commands
        _prompt_session = PromptSession(
            completer=_SlashCompleter(commands),
            complete_while_typing=True,
            style=_PROMPT_STYLE,
            mouse_support=False,
        )
    return _prompt_session


def _chevron_prompt() -> FormattedText:
    return FormattedText([
        ("class:prompt-margin", INDENT),
        ("class:prompt-chevron", f"{CHEVRON}  "),
    ])


def student_input_prompt(
    *,
    commands: Iterable[tuple[str, str]] = (),
    hint_text: str = "",
) -> str:
    """Read a line of student input.

    Uses prompt_toolkit for arrow-key navigation, word-wise delete
    (ctrl/option-backspace), and a Codex/Claude-style slash-command
    popup that appears as the student types ``/``.
    """
    if hint_text:
        _print(f"[{C.dim}]{hint_text}[/]")
    cmds: tuple[tuple[str, str], ...] = tuple(commands)
    session = _get_prompt_session(cmds)
    return session.prompt(_chevron_prompt()).rstrip()


def text_prompt(label: str, *, default: str = "") -> str:
    session: PromptSession[str] = PromptSession(style=_PROMPT_STYLE)
    prompt = FormattedText([
        ("class:prompt-margin", INDENT),
        ("class:prompt-chevron", f"{label}  "),
    ])
    return session.prompt(prompt, default=default).strip()


def student_says(text: str) -> None:
    _print(f"[bold {C.student}]{CHEVRON}[/]  {text}")


def prof_says(text: str) -> None:
    _blank()
    console.print(Padding(Markdown(text), BODY_PAD))
    _blank()


model_response = prof_says


@contextmanager
def thinking(label: str = "thinking") -> Generator[None, None, None]:
    with console.status(
        f"[{C.dim}]{label}…[/]",
        spinner="dots",
        spinner_style=C.accent,
    ):
        yield


# Hash.

def hash_display(h: Any) -> str:
    return f"[{C.accent}]{h.short()}[/]"


# Tables.

def _bare_table(title: str | None = None) -> Table:
    return Table(
        title=title,
        title_style=f"bold {C.dim}",
        title_justify="left",
        show_header=True,
        header_style=f"bold {C.dim}",
        pad_edge=False,
        box=None,
    )


def _print_block(renderable: RenderableType) -> None:
    _blank()
    console.print(Padding(renderable, (0, 0, 0, MARGIN)))
    _blank()


def ref_table(refs: Sequence[tuple[str, Any]]) -> None:
    table = _bare_table("refs")
    table.add_column("name", style=C.student)
    table.add_column("target", style=C.accent)
    for name, h in refs:
        table.add_row(name, h.short())
    _print_block(table)


def session_ref_table(refs: Sequence[tuple[str, Any]]) -> None:
    table = _bare_table("sessions")
    table.add_column("ref", style=C.student)
    table.add_column("tip", style=C.accent)
    for name, h in refs:
        table.add_row(name, h.short())
    _print_block(table)


def session_trace_display(ref_name: str, rows: Sequence[Any]) -> None:
    table = _bare_table(f"trace {DOT} {ref_name}")
    table.add_column("#", justify="right", style=C.dim)
    table.add_column("event")
    table.add_column("hash", style=C.accent)
    table.add_column("depth", justify="right", style=C.dim)
    table.add_column("model", style=C.muted)
    table.add_column("inputs", style=C.muted)
    table.add_column("outputs", style=C.muted)
    table.add_column("parents", justify="right", style=C.dim)

    for row in rows:
        depth = "" if row.depth is None else str(row.depth)
        table.add_row(
            str(row.index),
            row.kind,
            row.hash.short(),
            depth,
            row.model,
            ", ".join(row.input_roles),
            ", ".join(row.output_roles),
            str(row.parent_count),
        )
    _print_block(table)


def object_counts_display(atoms: int, frames: int, events: int) -> None:
    table = _bare_table()
    table.add_column("type", style=C.dim)
    table.add_column("count", justify="right")
    table.add_row("atoms", str(atoms))
    table.add_row("frames", str(frames))
    table.add_row("events", str(events))
    table.add_row("[bold]total[/]", f"[bold {C.accent}]{atoms + frames + events}[/]")
    _print_block(table)


# Course tree.

_ATOM_STYLE: dict[str, str] = {
    "ConceptDefinition": C.accent,
    "ProblemStatement": "yellow",
    "WorkedExample": "green",
    "LessonBody": "white",
    "StudentResponse": C.student,
    "ModelOutput": C.accent,
}

_EDGE_STYLE: dict[str, str] = {
    "CoversConcept": C.accent,
    "Contains": "bold",
    "IncludesProblem": "yellow",
    "IncludesExample": "green",
    "Prerequisite": "red",
    "MasteryEstimate": "magenta",
}


def _safe_get_frame(ws: Any, h: Any) -> Any:
    """Return the frame at ``h``, or ``None`` if it's missing or an atom."""
    try:
        return ws.get_frame(h)
    except TypeError:
        return None


def _safe_get_atom(ws: Any, h: Any) -> Any:
    """Return the atom at ``h``, or ``None`` if it's missing or a frame."""
    try:
        return ws.get_atom(h)
    except TypeError:
        return None


def course_tree(ws: Any, course_hash: Any) -> None:
    tree = Tree(f"[bold {C.accent}]course[/]", guide_style=C.dim)
    _build_tree(ws, course_hash, tree, depth=0, max_depth=4)
    _print_block(tree)


def _build_tree(
    ws: Any,
    node_hash: Any,
    tree_node: Tree,
    depth: int,
    max_depth: int,
) -> None:
    if depth >= max_depth:
        return

    frame = _safe_get_frame(ws, node_hash)
    if frame is None:
        atom = _safe_get_atom(ws, node_hash)
        if atom is None:
            return
        style = _ATOM_STYLE.get(atom.kind, C.dim)
        snippet = atom.text[:60] + "…" if len(atom.text) > 60 else atom.text
        tree_node.add(f"[{style}]{atom.kind}[/]  [{C.muted}]{snippet}[/]")
        return

    for edge in frame.edges:
        label_style = _EDGE_STYLE.get(edge.label, C.dim)

        child_frame = _safe_get_frame(ws, edge.target)
        if child_frame is not None and child_frame.label:
            child_name = child_frame.label
        else:
            child_atom = _safe_get_atom(ws, edge.target)
            child_name = (
                child_atom.text[:40] if child_atom is not None else edge.target.short()
            )

        weight = (
            f"  [{C.dim}]{edge.weight:.2f}[/]" if edge.weight is not None else ""
        )
        child_node = tree_node.add(
            f"[{label_style}]{edge.label}[/]  {ARROW}  {child_name}{weight}"
        )
        if child_frame is not None:
            _build_tree(ws, edge.target, child_node, depth + 1, max_depth)


# Mastery.

_BAR_WIDTH = 20


def mastery_display(mastery: Sequence[tuple[Any, float]], ws: Any) -> None:
    table = _bare_table("mastery")
    table.add_column("concept")
    table.add_column("level", justify="right", style=C.dim)
    table.add_column("", min_width=_BAR_WIDTH)

    for concept_hash, level in sorted(mastery, key=lambda x: x[1]):
        atom = _safe_get_atom(ws, concept_hash)
        name = atom.text[:40] if atom is not None else concept_hash.short()

        filled = max(0, min(_BAR_WIDTH, int(round(level * _BAR_WIDTH))))
        if level < 0.3:
            color = C.err
        elif level < 0.7:
            color = C.warn
        else:
            color = C.ok
        bar = (
            f"[{color}]{'█' * filled}[/]"
            f"[{C.dim}]{'░' * (_BAR_WIDTH - filled)}[/]"
        )
        table.add_row(name, f"{level:.0%}", bar)

    _print_block(table)
