"""Terminal display helpers using rich."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown

console = Console()
err_console = Console(stderr=True)


def header(title: str, subtitle: str = "") -> None:
    text = Text(title, style="bold cyan")
    if subtitle:
        text.append(f"\n{subtitle}", style="dim")
    console.print(Panel(text, border_style="cyan", padding=(1, 2)))


def success(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]![/yellow] {msg}")


def error(msg: str) -> None:
    err_console.print(f"[red]✗[/red] {msg}")


def info(msg: str) -> None:
    console.print(f"[dim]→[/dim] {msg}")


def hash_display(h) -> str:
    """Format a Hash for terminal display."""
    return f"[cyan]{h.short()}[/cyan]"


def ref_table(refs: list[tuple[str, object]]) -> None:
    """Display refs as a table."""
    table = Table(title="Refs", show_header=True, header_style="bold")
    table.add_column("Name", style="green")
    table.add_column("Target", style="cyan")
    for name, h in refs:
        table.add_row(name, h.short())
    console.print(table)


def object_counts_display(atoms: int, frames: int, events: int) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("Type")
    table.add_column("Count", justify="right")
    table.add_row("Atoms", str(atoms))
    table.add_row("Frames", str(frames))
    table.add_row("Events", str(events))
    table.add_row("[bold]Total[/bold]", f"[bold]{atoms + frames + events}[/bold]")
    console.print(table)


def course_tree(ws, course_hash) -> None:
    """Display the course structure as a tree."""
    from .rlm_ws import Workspace

    tree = Tree(f"[bold]Course[/bold]")
    _build_tree(ws, course_hash, tree, depth=0, max_depth=4)
    console.print(tree)


def _build_tree(ws, hash, tree_node, depth: int, max_depth: int) -> None:
    if depth >= max_depth:
        return

    frame = ws.get_frame(hash)
    if frame is None:
        # It's an atom.
        atom = ws.get_atom(hash)
        if atom:
            style = {
                "ConceptDefinition": "blue",
                "ProblemStatement": "yellow",
                "WorkedExample": "green",
                "LessonBody": "white",
                "StudentResponse": "magenta",
                "ModelOutput": "cyan",
            }.get(atom.kind, "dim")
            text = atom.text[:60] + "..." if len(atom.text) > 60 else atom.text
            tree_node.add(f"[{style}]{atom.kind}[/{style}]: {text}")
        return

    for edge in frame.edges:
        label_style = {
            "CoversConcept": "blue",
            "Contains": "bold",
            "IncludesProblem": "yellow",
            "IncludesExample": "green",
            "Prerequisite": "red",
            "MasteryEstimate": "magenta",
        }.get(edge.label, "dim")

        child_frame = ws.get_frame(edge.target)
        if child_frame and child_frame.label:
            child_name = child_frame.label
        else:
            child_atom = ws.get_atom(edge.target)
            if child_atom:
                child_name = child_atom.text[:40]
            else:
                child_name = edge.target.short()

        weight_str = f" ({edge.weight:.2f})" if edge.weight is not None else ""
        child_node = tree_node.add(
            f"[{label_style}]{edge.label}[/{label_style}] → {child_name}{weight_str}"
        )

        if child_frame:
            _build_tree(ws, edge.target, child_node, depth + 1, max_depth)


def mastery_display(mastery: list[tuple[object, float]], ws) -> None:
    """Display mastery levels with bar visualization."""
    table = Table(title="Student Mastery", show_header=True, header_style="bold")
    table.add_column("Concept")
    table.add_column("Level", justify="right")
    table.add_column("Bar", min_width=20)

    for concept_hash, level in sorted(mastery, key=lambda x: x[1]):
        atom = ws.get_atom(concept_hash)
        name = atom.text[:40] if atom else concept_hash.short()
        bar_width = int(level * 20)
        if level < 0.3:
            color = "red"
        elif level < 0.7:
            color = "yellow"
        else:
            color = "green"
        bar = f"[{color}]{'█' * bar_width}{'░' * (20 - bar_width)}[/{color}]"
        table.add_row(name, f"{level:.0%}", bar)

    console.print(table)


def model_response(text: str) -> None:
    """Display a model response."""
    console.print(
        Panel(
            Markdown(text),
            title="[bold cyan]Assistant[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def student_input_prompt() -> str:
    """Prompt for student input."""
    return Prompt.ask("\n[bold green]You[/bold green]")
