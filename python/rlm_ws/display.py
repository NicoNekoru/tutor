"""Terminal presentation for the rlm-ws tutor.

Layout sketch:

    rlm-ws  intro to calculus
    user · gpt-5.4-mini
    ──────────────────────────────────────────

      ›  how does the chain rule work?

         If y = f(g(x)), then dy/dx = f'(g(x)) · g'(x).
         Concretely: differentiate the outer function at the
         inner one, then multiply by the inner derivative.

      ›  /mastery

Every line sits at a two-column left margin. The chevron marks
student turns; the Prof's reply is unlabeled indented prose.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable, Iterator

from rich.console import Console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
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


console = Console(highlight=False, soft_wrap=False)
err_console = Console(stderr=True, highlight=False)


def _print(markup: str) -> None:
    console.print(f"{INDENT}{markup}")


def _blank() -> None:
    console.print()


def divider() -> None:
    console.print(Rule(style=C.dim))


def section(title: str) -> None:
    _blank()
    console.print(Rule(f"[{C.dim}]{title}[/]", style=C.dim, align="left"))


# Status messages.

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


def slash_help(commands: list[tuple[str, str]]) -> None:
    table = Table.grid(padding=(0, 3))
    table.add_column(style=f"bold {C.accent}", no_wrap=True)
    table.add_column(style=C.muted)
    for cmd, desc in commands:
        table.add_row(cmd, desc)
    _blank()
    console.print(Padding(table, (0, 0, 0, MARGIN)))
    _blank()


# Conversation.

def student_input_prompt(*, hint_text: str = "") -> str:
    if hint_text:
        _print(f"[{C.dim}]{hint_text}[/]")
    raw = console.input(f"{INDENT}[bold {C.student}]{CHEVRON}[/]  ")
    return raw.rstrip()


def student_says(text: str) -> None:
    _print(f"[bold {C.student}]{CHEVRON}[/]  {text}")


def prof_says(text: str) -> None:
    _blank()
    console.print(Padding(Markdown(text), BODY_PAD))
    _blank()


model_response = prof_says


@contextmanager
def thinking(label: str = "thinking") -> Iterator[None]:
    with console.status(
        f"[{C.dim}]{label}…[/]",
        spinner="dots",
        spinner_style=C.accent,
    ):
        yield


# Hash.

def hash_display(h) -> str:
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


def _print_block(renderable) -> None:
    _blank()
    console.print(Padding(renderable, (0, 0, 0, MARGIN)))
    _blank()


def ref_table(refs: list[tuple[str, object]]) -> None:
    table = _bare_table("refs")
    table.add_column("name", style=C.student)
    table.add_column("target", style=C.accent)
    for name, h in refs:
        table.add_row(name, h.short())
    _print_block(table)


def session_ref_table(refs: list[tuple[str, object]]) -> None:
    table = _bare_table("sessions")
    table.add_column("ref", style=C.student)
    table.add_column("tip", style=C.accent)
    for name, h in refs:
        table.add_row(name, h.short())
    _print_block(table)


def session_trace_display(ref_name: str, rows: list[object]) -> None:
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

_ATOM_STYLE = {
    "ConceptDefinition": C.accent,
    "ProblemStatement": "yellow",
    "WorkedExample": "green",
    "LessonBody": "white",
    "StudentResponse": C.student,
    "ModelOutput": C.accent,
}

_EDGE_STYLE = {
    "CoversConcept": C.accent,
    "Contains": "bold",
    "IncludesProblem": "yellow",
    "IncludesExample": "green",
    "Prerequisite": "red",
    "MasteryEstimate": "magenta",
}


def course_tree(ws, course_hash) -> None:
    tree = Tree(f"[bold {C.accent}]course[/]", guide_style=C.dim)
    _build_tree(ws, course_hash, tree, depth=0, max_depth=4)
    _print_block(tree)


def _build_tree(ws, hash, tree_node, depth: int, max_depth: int) -> None:
    if depth >= max_depth:
        return

    frame = ws.get_frame(hash)
    if frame is None:
        atom = ws.get_atom(hash)
        if atom is None:
            return
        style = _ATOM_STYLE.get(atom.kind, C.dim)
        snippet = atom.text[:60] + "…" if len(atom.text) > 60 else atom.text
        tree_node.add(f"[{style}]{atom.kind}[/]  [{C.muted}]{snippet}[/]")
        return

    for edge in frame.edges:
        label_style = _EDGE_STYLE.get(edge.label, C.dim)

        child_frame = ws.get_frame(edge.target)
        if child_frame and child_frame.label:
            child_name = child_frame.label
        else:
            child_atom = ws.get_atom(edge.target)
            child_name = (
                child_atom.text[:40] if child_atom else edge.target.short()
            )

        weight = (
            f"  [{C.dim}]{edge.weight:.2f}[/]" if edge.weight is not None else ""
        )
        child_node = tree_node.add(
            f"[{label_style}]{edge.label}[/]  {ARROW}  {child_name}{weight}"
        )
        if child_frame:
            _build_tree(ws, edge.target, child_node, depth + 1, max_depth)


# Mastery.

_BAR_WIDTH = 20


def mastery_display(mastery: list[tuple[object, float]], ws) -> None:
    table = _bare_table("mastery")
    table.add_column("concept")
    table.add_column("level", justify="right", style=C.dim)
    table.add_column("", min_width=_BAR_WIDTH)

    for concept_hash, level in sorted(mastery, key=lambda x: x[1]):
        atom = ws.get_atom(concept_hash)
        name = atom.text[:40] if atom else concept_hash.short()

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
