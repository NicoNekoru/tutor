"""
rlm-ws: Command-line interface for RLM workspaces.

Usage:
    rlm-ws init [PATH]           # Initialize a new workspace
    rlm-ws ingest <FILES>        # Ingest markdown course materials
    rlm-ws session               # Start an interactive tutoring session
    rlm-ws inspect               # Inspect workspace state
    rlm-ws gc                    # Garbage collection
    rlm-ws export                # Export subgraph as JSON
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from . import display
from .rlm_ws import Workspace

app = typer.Typer(
    name="rlm-ws",
    help="Content-addressable workspace for RLM tutoring systems.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _resolve_workspace(path: Path | None) -> Workspace:
    """Find and open a workspace, searching upward from cwd if no path given."""
    if path:
        return Workspace.open(str(path))

    # Search upward for .rlm directory.
    current = Path.cwd()
    while True:
        if (current / ".rlm").is_dir():
            return Workspace.open(str(current))
        parent = current.parent
        if parent == current:
            break
        current = parent

    display.error("No workspace found. Run 'rlm-ws init' first.")
    raise typer.Exit(1)


# ============================================================================
# init
# ============================================================================


@app.command()
def init(
    path: Optional[Path] = typer.Argument(
        None,
        help="Directory for the workspace. Defaults to current directory.",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Course name. If omitted, prompted interactively.",
    ),
    ingest_from: Optional[Path] = typer.Option(
        None,
        "--ingest",
        "-i",
        help="Path to markdown files to ingest immediately after init.",
    ),
):
    """Initialize a new RLM workspace.

    Creates a .rlm/ directory at the given path (or cwd) with the object
    store, refs, and index. Optionally ingests course materials.
    """
    ws_path = path or Path.cwd()

    if (ws_path / ".rlm").exists():
        display.error(f"Workspace already exists at {ws_path}")
        raise typer.Exit(1)

    display.header("rlm-ws", "Initialize a new workspace")

    # Interactive prompts if not provided.
    if name is None:
        from rich.prompt import Prompt

        name = Prompt.ask(
            "Course name",
            default=ws_path.name,
        )

    ws = Workspace.init(str(ws_path))
    display.success(f"Workspace created at {ws_path / '.rlm'}")

    # Ingest if requested.
    if ingest_from:
        from .ingest import ingest_directory, ingest_file

        ingest_path = ingest_from.resolve()
        if ingest_path.is_dir():
            ingest_directory(ws, ingest_path, course_name=name or "")
        elif ingest_path.is_file():
            ingest_file(ws, ingest_path, course_name=name or "")
        else:
            display.error(f"Path not found: {ingest_from}")
            raise typer.Exit(1)

    display.console.print()
    display.info("Next steps:")
    display.info("  rlm-ws ingest <markdown-files>   — add course materials")
    display.info("  rlm-ws session                   — start tutoring")
    display.info("  rlm-ws inspect                   — view workspace")


# ============================================================================
# ingest
# ============================================================================


@app.command()
def ingest(
    paths: list[Path] = typer.Argument(
        ...,
        help="Markdown files or directories to ingest.",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace path. Searches upward from cwd if omitted.",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Course name override.",
    ),
):
    """Ingest markdown course materials into the workspace.

    Parses markdown files following the rlm-ws convention:

    \b
      # Module Name
      ## Lesson Name
      ### Concept: Name
      ### Problem: Name
      ### Example: Name
      <!-- prerequisite: Other Lesson -->
    """
    ws = _resolve_workspace(workspace)
    from .ingest import ingest_directory, ingest_file

    for p in paths:
        resolved = p.resolve()
        if resolved.is_dir():
            ingest_directory(ws, resolved, course_name=name or "")
        elif resolved.is_file():
            ingest_file(ws, resolved, course_name=name or "")
        else:
            display.error(f"Not found: {p}")

    # Show result.
    atoms, frames, events = ws.object_counts()
    display.object_counts_display(atoms, frames, events)


# ============================================================================
# session
# ============================================================================


@app.command()
def session(
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace path.",
    ),
    student: str = typer.Option(
        "default",
        "--student",
        "-s",
        help="Student identifier.",
    ),
    model: str = typer.Option(
        "anthropic/claude-sonnet-4-20250514",
        "--model",
        "-m",
        help="Model to use (OpenRouter model string).",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        "-k",
        help="API key. Defaults to OPENROUTER_API_KEY env var.",
    ),
    api_base: str = typer.Option(
        "https://openrouter.ai/api/v1",
        "--api-base",
        help="API base URL.",
    ),
):
    """Start an interactive tutoring session.

    Enters a REPL where you can ask questions and get tutored. The system
    retrieves relevant course context and tracks your mastery over time.

    Commands available during the session:
      /mastery  — show current mastery levels
      /tree     — show course structure
      /status   — show workspace statistics
      /quit     — end session
    """
    ws = _resolve_workspace(workspace)

    # Verify course exists.
    if ws.get_ref_hash("course/structure") is None:
        display.error("No course ingested. Run 'rlm-ws ingest' first.")
        raise typer.Exit(1)

    from .session import SessionConfig, run_interactive

    config = SessionConfig(
        student_id=student,
        model=model,
        api_key=api_key or "",
        api_base=api_base,
    )

    display.header("rlm-ws", f"Tutoring session • student: {student}")
    run_interactive(ws, config)


# ============================================================================
# inspect
# ============================================================================


@app.command()
def inspect(
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace path.",
    ),
    refs: bool = typer.Option(False, "--refs", "-r", help="Show all refs."),
    tree: bool = typer.Option(
        False, "--tree", "-t", help="Show course structure tree."
    ),
    mastery: Optional[str] = typer.Option(
        None,
        "--mastery",
        "-m",
        help="Show mastery for a student ID.",
    ),
    counts: bool = typer.Option(False, "--counts", "-c", help="Show object counts."),
):
    """Inspect the workspace state.

    With no flags, shows a summary. Use flags to drill into specific views.
    """
    ws = _resolve_workspace(workspace)

    if not any([refs, tree, mastery, counts]):
        # Default: show everything.
        refs = tree = counts = True

    if counts:
        atoms, frames, events = ws.object_counts()
        display.object_counts_display(atoms, frames, events)

    if refs:
        all_refs = ws.list_refs("")
        if all_refs:
            display.ref_table(all_refs)
        else:
            display.info("No refs set")

    if tree:
        course_hash = ws.get_ref_hash("course/structure")
        if course_hash:
            display.course_tree(ws, course_hash)
        else:
            display.info("No course structure found")

    if mastery:
        mastery_hash = ws.get_ref_hash(f"student/{mastery}/mastery")
        if mastery_hash:
            mastery_data = ws.student_mastery_map(mastery_hash)
            display.mastery_display(mastery_data, ws)
        else:
            display.warn(f"No mastery data for student '{mastery}'")


# ============================================================================
# gc
# ============================================================================


@app.command()
def gc(
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace path.",
    ),
    rebuild_index: bool = typer.Option(
        False,
        "--rebuild-index",
        help="Also rebuild the secondary index.",
    ),
):
    """Run garbage collection on the workspace.

    Removes objects not reachable from any ref. Optionally rebuilds the
    secondary index from scratch.
    """
    ws = _resolve_workspace(workspace)

    total, reachable, removed = ws.gc()
    display.success(f"GC complete: {removed} object(s) removed")
    display.info(f"  Total: {total}, Reachable: {reachable}, Removed: {removed}")

    if rebuild_index:
        count = ws.rebuild_index()
        display.success(f"Index rebuilt: {count} object(s) indexed")


# ============================================================================
# export
# ============================================================================


@app.command()
def export(
    ref: str = typer.Argument(
        ...,
        help="Ref name or hex hash to export from.",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace path.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file. Defaults to stdout.",
    ),
):
    """Export a subgraph as JSON.

    Exports all objects reachable from the given ref or hash.
    """
    from .rlm_ws import Hash

    ws = _resolve_workspace(workspace)

    # Try as ref name first, then as hex hash.
    target = ws.get_ref_hash(ref)
    if target is None:
        try:
            target = Hash.from_hex(ref)
        except Exception:
            display.error(f"'{ref}' is not a valid ref name or hash")
            raise typer.Exit(1)

    json_str = ws.export_json(target)

    if output:
        output.write_text(json_str, encoding="utf-8")
        display.success(f"Exported to {output}")
    else:
        display.console.print(json_str)
