"""
rlm-ws: Command-line interface for RLM workspaces.

Usage:
    rlm-ws init [NAME]           # Initialize a new workspace (guided)
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
from rich.prompt import Prompt

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
    name: Optional[str] = typer.Argument(
        None,
        help=(
            "Course name. Creates a directory with this name (like 'cargo init'). "
            "Use '.' to initialize in the current directory."
        ),
    ),
    template: Optional[str] = typer.Option(
        None,
        "--template",
        "-t",
        help="Template directory name. If omitted, prompted interactively.",
    ),
    templates_dir: Optional[Path] = typer.Option(
        None,
        "--templates-dir",
        help="Additional directory to search for templates.",
        envvar="RLM_TEMPLATES_DIR",
    ),
    no_ingest: bool = typer.Option(
        False,
        "--no-ingest",
        help="Skip automatic ingestion of template content.",
    ),
):
    """Initialize a new RLM workspace.

    Creates a workspace directory with course content ready to use.

    \b
    Templates are directories containing a template.json and course files.
    Searched in: --templates-dir, $RLM_TEMPLATES_DIR, then built-in templates.

    \b
    Examples:
      rlm-ws init my-course                # guided setup
      rlm-ws init . -t algorithms          # current dir, algorithms template
      rlm-ws init "Linear Algebra"         # creates ./linear-algebra/
      rlm-ws init x -t my-tmpl --templates-dir ~/templates
    """
    from .templates import discover_templates, apply_template

    display.header("rlm-ws", "Initialize a new workspace")

    # --- Resolve name and directory ---

    if name is None:
        name = Prompt.ask("Course name")

    if name == ".":
        ws_dir = Path.cwd()
        course_name = Prompt.ask("Course name", default=ws_dir.name)
    else:
        course_name = name
        dir_name = name.lower().replace(" ", "-")
        dir_name = "".join(c for c in dir_name if c.isalnum() or c == "-")
        ws_dir = Path.cwd() / dir_name

    # --- Check directory state ---

    if (ws_dir / ".rlm").exists():
        display.error(f"Workspace already exists at {ws_dir}")
        raise typer.Exit(1)

    if ws_dir.exists() and any(ws_dir.iterdir()):
        if name != ".":
            display.error(f"Directory '{ws_dir}' already exists and is not empty.")
            raise typer.Exit(1)
        display.warn(f"Initializing in non-empty directory: {ws_dir}")

    # --- Discover and choose template ---

    templates = discover_templates(templates_dir)

    if template is None:
        display.console.print()
        display.console.print("[bold]Choose a starting point:[/bold]")
        display.console.print()

        keys = list(templates.keys())
        for i, key in enumerate(keys, 1):
            tmpl = templates[key]
            display.console.print(
                f"  [cyan]{i}[/cyan]  [bold]{tmpl.name}[/bold] — {tmpl.description}"
            )
        empty_idx = len(keys) + 1
        display.console.print(
            f"  [cyan]{empty_idx}[/cyan]  [bold]Empty[/bold] — just the workspace, no content"
        )
        display.console.print()

        choices = [str(i) for i in range(1, empty_idx + 1)]
        choice = Prompt.ask("Select", choices=choices, default="1")
        idx = int(choice)
        if idx <= len(keys):
            template = keys[idx - 1]
        else:
            template = "empty"

    if template != "empty" and template not in templates:
        available = ", ".join(templates.keys()) or "(none found)"
        display.error(f"Unknown template: '{template}'. Available: {available}, empty")
        raise typer.Exit(1)

    # --- Create workspace ---

    ws_dir.mkdir(parents=True, exist_ok=True)
    ws = Workspace.init(str(ws_dir))
    display.success(f"Workspace created at {ws_dir / '.rlm'}")

    # --- Apply template ---

    if template != "empty":
        tmpl = templates[template]
        written = apply_template(tmpl, ws_dir, course_name)
        for p in written:
            display.info(f"Created {p.relative_to(ws_dir)}")

        # Ingest content/ if present.
        if not no_ingest:
            content_dir = ws_dir / "content"
            if content_dir.is_dir():
                from .ingest import ingest_directory

                display.console.print()
                ingest_directory(ws, content_dir, course_name=course_name)

    # --- Summary ---

    display.console.print()
    atoms, frames, events = ws.object_counts()
    if atoms + frames + events > 0:
        display.object_counts_display(atoms, frames, events)
        display.console.print()
        display.success("Workspace is ready!")
        display.info(f"  cd {ws_dir.name}")
        display.info("  rlm-ws session                   — start tutoring")
        display.info("  rlm-ws inspect --tree             — view course structure")
    else:
        display.info("Workspace initialized (empty).")
        display.info(f"  cd {ws_dir.name}")
        display.info("  # Add .md files to content/, then:")
        display.info("  rlm-ws ingest content/            — parse course materials")
        display.info("  rlm-ws session                    — start tutoring")


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

    See COURSE_FORMAT.md (created during init) for the markdown format.
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

    \b
    In-session commands:
      /mastery  — show current mastery levels
      /tree     — show course structure
      /status   — show workspace statistics
      /quit     — end session
    """
    ws = _resolve_workspace(workspace)

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
    """Inspect the workspace state. With no flags, shows a summary."""
    ws = _resolve_workspace(workspace)

    if not any([refs, tree, mastery, counts]):
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
    """Run garbage collection on the workspace."""
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
    """Export a subgraph as JSON."""
    from .rlm_ws import Hash

    ws = _resolve_workspace(workspace)

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
