"""
rlm-ws: Command-line interface for RLM workspaces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

from . import display
from .rlm_ws import Workspace

app = typer.Typer(
    name="rlm-ws",
    help="Content-addressable workspace for RLM tutoring systems.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


DEMO_COURSE_MD = """# Binary Search Demo

## Sorted Search

Binary search works on sorted collections by keeping a low and high boundary
around the part of the collection that may still contain the target.

### Concept: Binary Search
Binary search compares the target to the middle element. If the target is
smaller, the upper half can be discarded. If the target is larger, the lower
half can be discarded. Each step halves the remaining search interval.

### Problem: Find A Number
Given a sorted list and a target value, decide whether the target appears in the
list by repeatedly halving the search interval.

### Example: Searching For 7
In [1, 3, 5, 7, 9], compare 7 to the middle value 5. Since 7 is larger, search
the right half [7, 9], then compare with 7.
"""


def _resolve_workspace(path: Path | None) -> tuple[Workspace, Path]:
    """Find and open a workspace. Returns (Workspace, ws_dir)."""
    if path:
        resolved = path.resolve()
        return Workspace.open(str(resolved)), resolved

    current = Path.cwd()
    while True:
        if (current / ".rlm").is_dir():
            return Workspace.open(str(current)), current
        parent = current.parent
        if parent == current:
            break
        current = parent

    display.error("No workspace found. Run 'rlm-ws init' first.")
    raise typer.Exit(1)


# ============================================================================
# auth
# ============================================================================


@app.command()
def auth(
    provider: Optional[str] = typer.Argument(
        None,
        help="Provider to configure: codex, openai, openrouter",
    ),
    show: bool = typer.Option(False, "--show", "-s", help="Show saved keys."),
    set_default: Optional[str] = typer.Option(
        None,
        "--default",
        "-d",
        help="Set default provider.",
    ),
):
    """Manage API keys for model providers.

    \b
    Keys are stored in ~/.config/rlm-ws/auth.toml (never in the workspace).

    \b
    Examples:
      rlm-ws auth                    # guided setup
      rlm-ws auth codex              # reuse `codex login` credentials
      rlm-ws auth openai             # configure OpenAI with a typed key
      rlm-ws auth --show             # show saved keys + codex status
      rlm-ws auth --default codex    # set default provider
    """
    from .auth import (
        PROVIDERS,
        codex_status,
        is_managed,
        load_auth,
        set_api_key,
        set_default_provider,
        _auth_path,
    )

    if set_default:
        if set_default not in PROVIDERS:
            display.error(
                f"Unknown provider: '{set_default}'. Available: {', '.join(PROVIDERS)}"
            )
            raise typer.Exit(1)
        set_default_provider(set_default)
        display.success(f"Default provider set to {set_default}")
        return

    if show:
        auth_data = load_auth()
        keys = auth_data.get("keys", {})
        from .auth import DEFAULT_PROVIDER

        default = auth_data.get("default", {}).get("provider", DEFAULT_PROVIDER)
        display.console.print()
        if keys:
            for prov, key in keys.items():
                masked = key[:8] + "..." + key[-4:] if len(key) > 16 else "***"
                marker = " [green](default)[/green]" if prov == default else ""
                display.console.print(f"  {prov}: {masked}{marker}")
        else:
            display.info("No rlm-ws keys saved.")

        cx = codex_status()
        display.console.print()
        codex_marker = " [green](default)[/green]" if default == "codex" else ""
        if cx["found"]:
            if cx["has_api_key"]:
                kind = "api key"
            elif cx["has_chatgpt"]:
                kind = f"chatgpt ({cx['account_id'] or 'unknown account'})"
            else:
                kind = "no usable credential"
            display.console.print(f"  codex: {kind}{codex_marker}")
            display.info(f"  via {cx['path']}")
        else:
            display.console.print(f"  codex: not logged in{codex_marker}")
            display.info(f"  expected at {cx['path']} — run `codex login`")

        display.console.print()
        display.info(f"Config file: {_auth_path()}")
        return

    # Interactive setup.
    display.header("rlm-ws auth", "Configure a model provider")

    if provider is None:
        display.console.print()
        display.console.print("[bold]Choose a provider:[/bold]")
        display.console.print()
        prov_keys = list(PROVIDERS.keys())
        for i, key in enumerate(prov_keys, 1):
            info = PROVIDERS[key]
            tag = " [dim](no key needed)[/dim]" if info.get("managed") else ""
            display.console.print(
                f"  [cyan]{i}[/cyan]  [bold]{info['name']}[/bold]{tag}"
            )
        display.console.print()
        choice = Prompt.ask(
            "Select",
            choices=[str(i) for i in range(1, len(prov_keys) + 1)],
            default="1",
        )
        provider = prov_keys[int(choice) - 1]

    if provider not in PROVIDERS:
        display.error(f"Unknown provider: '{provider}'")
        raise typer.Exit(1)

    info = PROVIDERS[provider]

    if is_managed(provider):
        cx = codex_status()
        display.console.print()
        if not cx["found"]:
            display.warn(f"No Codex auth at {cx['path']}.")
            display.info("Run `codex login` and re-run this command.")
            return
        if cx["has_api_key"]:
            display.success("Found a Codex-stored API key.")
        elif cx["has_chatgpt"]:
            account = cx["account_id"] or "unknown account"
            display.success(f"Found a ChatGPT OAuth token (account {account}).")
            display.info("Routes through chatgpt.com/backend-api/codex (experimental).")
        else:
            display.warn("Codex auth file present but has no usable credential.")
            return

        auth_data = load_auth()
        current_default = auth_data.get("default", {}).get("provider", "")
        if current_default != provider:
            if Confirm.ask(f"\n  Set {provider} as the default provider?", default=True):
                set_default_provider(provider)
                display.success(f"Default provider: {provider}")
        return

    display.console.print()
    display.info(
        f"Get an API key at: [link={info['signup_url']}]{info['signup_url']}[/link]"
    )
    display.console.print()

    key = Prompt.ask(f"  {info['name']} API key")
    if not key.strip():
        display.warn("No key entered, skipping.")
        return

    path = set_api_key(provider, key.strip())
    display.success(f"Key saved to {path}")
    display.info(f"  Provider: {provider}")
    display.info(f"  API base: {info['api_base']}")
    display.info(f"  Default model: {info['models'][0]}")

    # Offer to set as default.
    auth_data = load_auth()
    current_default = auth_data.get("default", {}).get("provider", "")
    if current_default != provider:
        if Confirm.ask(f"\n  Set {provider} as the default provider?", default=True):
            set_default_provider(provider)
            display.success(f"Default provider: {provider}")


# ============================================================================
# init
# ============================================================================


@app.command()
def init(
    name: Optional[str] = typer.Argument(
        None,
        help="Course name. Creates a directory with this name. Use '.' for cwd.",
    ),
    template: Optional[str] = typer.Option(
        None,
        "--template",
        "-t",
        help="Template name. If omitted, prompted interactively.",
    ),
    templates_dir: Optional[Path] = typer.Option(
        None,
        "--templates-dir",
        help="Additional templates directory.",
        envvar="RLM_TEMPLATES_DIR",
    ),
    no_ingest: bool = typer.Option(
        False,
        "--no-ingest",
        help="Skip automatic ingestion of template content.",
    ),
):
    """Initialize a new RLM workspace.

    \b
    Walks you through configuring the learning relationship.
    Answers shape the system prompt used in every tutoring session.
    """
    from .templates import (
        discover_templates,
        apply_template,
        run_prompts,
        build_system_prompt,
        save_workspace_config,
    )

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
            f"  [cyan]{empty_idx}[/cyan]  [bold]Empty[/bold] — just the workspace, no template"
        )
        display.console.print()

        choices = [str(i) for i in range(1, empty_idx + 1)]
        choice = Prompt.ask("Select", choices=choices, default="1")
        idx = int(choice)
        template = keys[idx - 1] if idx <= len(keys) else "empty"

    if template != "empty" and template not in templates:
        available = ", ".join(templates.keys()) or "(none found)"
        display.error(f"Unknown template: '{template}'. Available: {available}, empty")
        raise typer.Exit(1)

    # --- Run template prompts ---

    answers: dict[str, str] = {"course_name": course_name}
    system_prompt = ""
    selected_template = None

    if template != "empty":
        selected_template = templates[template]
        answers = run_prompts(selected_template, course_name)
        system_prompt = build_system_prompt(selected_template, answers)

    # --- Show the user what they configured ---

    if system_prompt:
        display.console.print()
        display.console.print(
            Panel(
                system_prompt.strip(),
                title="[bold cyan]Generated System Prompt[/bold cyan]",
                border_style="cyan",
                padding=(1, 2),
            )
        )
        display.console.print()

        if not Confirm.ask("  Does this look right?", default=True):
            display.info(
                "You can edit workspace.toml after init to change the system prompt."
            )

    # --- Create workspace ---

    ws_dir.mkdir(parents=True, exist_ok=True)
    ws = Workspace.init(str(ws_dir))
    display.success(f"Workspace created at {ws_dir / '.rlm'}")

    # --- Save configuration ---

    config_path = save_workspace_config(
        ws_dir,
        template or "empty",
        answers,
        system_prompt,
    )
    display.info(f"Configuration saved to {config_path.name}")

    # --- Apply template files ---

    if selected_template is not None:
        written = apply_template(selected_template, ws_dir, course_name)
        for p in written:
            display.info(f"Created {p.relative_to(ws_dir)}")

        if not no_ingest:
            content_dir = ws_dir / "content"
            if content_dir.is_dir():
                from .ingest import ingest_directory

                display.console.print()
                ingest_directory(ws, content_dir, course_name=course_name)

    # --- Check auth ---

    from .auth import get_api_key

    api_key, _, _ = get_api_key()

    # --- Summary ---

    display.console.print()
    atoms, frames, events = ws.object_counts()
    if atoms + frames + events > 0:
        display.object_counts_display(atoms, frames, events)
        display.console.print()
        display.success("Workspace is ready!")
        display.info(f"  cd {ws_dir.name}")
        if not api_key:
            display.info("  rlm-ws auth                      — configure an API key")
        display.info("  rlm-ws session                   — start tutoring")
        display.info("  rlm-ws inspect --tree             — view course structure")
    else:
        display.info("Workspace initialized (empty).")
        display.info(f"  cd {ws_dir.name}")
        display.info("  # Add .md files to content/, then:")
        display.info("  rlm-ws ingest content/")
        if not api_key:
            display.info("  rlm-ws auth                      — configure an API key")
        display.info("  rlm-ws session                    — start tutoring")

    display.console.print()
    display.info("Edit workspace.toml to change the system prompt or identities.")


# ============================================================================
# demo
# ============================================================================


@app.command()
def demo(
    path: Path = typer.Argument(
        Path("rlm-demo"),
        help="Directory to create for the demo workspace.",
    ),
    online: bool = typer.Option(
        False,
        "--online",
        help="Use the configured provider instead of offline mode.",
    ),
):
    """Create a minimal inspectable tutoring demo workspace."""
    demo_dir = path.resolve()
    if demo_dir.exists() and not demo_dir.is_dir():
        display.error(f"Demo path exists and is not a directory: {demo_dir}")
        raise typer.Exit(1)
    if demo_dir.exists() and any(demo_dir.iterdir()):
        display.error(f"Demo directory is not empty: {demo_dir}")
        raise typer.Exit(1)

    demo_dir.mkdir(parents=True, exist_ok=True)
    content_dir = demo_dir / "content"
    content_dir.mkdir()
    course_path = content_dir / "binary-search.md"
    course_path.write_text(DEMO_COURSE_MD, encoding="utf-8")

    ws = Workspace.init(str(demo_dir))
    from .ingest import ingest_file
    from .session import SessionConfig, end_session, run_turn, start_session

    ingest_file(ws, course_path, course_name="Binary Search Demo")

    provider = "openai"
    model = "gpt-5.4-mini"
    api_base = "https://api.openai.com/v1"
    api_key = ""
    extra_headers: dict[str, str] = {}
    mastery_judgment = "heuristic"
    if online:
        from .auth import resolve_api_config

        resolved = resolve_api_config(None)
        provider = resolved.provider
        model = resolved.model
        api_base = resolved.api_base
        api_key = resolved.api_key
        extra_headers = dict(resolved.extra_headers)
        mastery_judgment = "model" if api_key else "heuristic"
        if not api_key:
            display.warn("No configured API key found. Running demo offline.")

    config = SessionConfig(
        student_id="demo",
        provider=provider,
        model=model,
        api_base=api_base,
        api_key=api_key,
        extra_headers=extra_headers,
        mastery_judgment=mastery_judgment,
        ws_dir=demo_dir,
    )
    state = start_session(ws, config)
    for prompt in [
        "Explain binary search.",
        "I understand that binary search halves the remaining interval.",
    ]:
        display.info(f"demo turn: {prompt}")
        response = run_turn(state, prompt)
        display.prof_says(response)
    end_session(state)

    display.success("Demo workspace ready")
    display.info(f"cd {demo_dir}")
    display.info("rlm-ws inspect --sessions demo")
    display.info("rlm-ws inspect --timeline demo --concept \"binary search\"")


# ============================================================================
# ingest
# ============================================================================


@app.command()
def ingest(
    paths: list[Path] = typer.Argument(..., help="Markdown files or directories."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    name: Optional[str] = typer.Option(None, "--name", "-n"),
):
    """Ingest markdown course materials into the workspace."""
    ws, ws_dir = _resolve_workspace(workspace)
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
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    student: str = typer.Option("default", "--student", "-s"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k"),
    api_base: Optional[str] = typer.Option(None, "--api-base"),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        "-p",
        help="Provider from auth config: codex, openai, openrouter",
    ),
    mastery_judge: str = typer.Option(
        "model",
        "--mastery-judge",
        help="Mastery update mode when the tutor emits no explicit update: model or heuristic.",
    ),
):
    """Start an interactive tutoring session.

    \b
    In-session commands:
      /mastery  — show current mastery levels
      /provider — show or switch the active provider
      /model    — show or change the current model
      /judge    — show or change mastery judgment mode
      /tree     — show course structure
      /status   — show workspace statistics
      /quit     — end session
    """
    ws, ws_dir = _resolve_workspace(workspace)

    if ws.get_ref_hash("course/structure") is None:
        display.error("No course ingested. Run 'rlm-ws ingest' first.")
        raise typer.Exit(1)

    # Resolve auth.
    from .auth import PROVIDERS, resolve_api_config
    from .session import SessionConfig, run_interactive

    if provider is not None and provider not in PROVIDERS:
        display.error(
            f"Unknown provider: '{provider}'. Available: {', '.join(PROVIDERS)}"
        )
        raise typer.Exit(1)

    resolved = resolve_api_config(provider)

    config = SessionConfig(
        student_id=student,
        provider=resolved.provider,
        model=model or resolved.model,
        api_key=api_key or resolved.api_key,
        api_base=api_base or resolved.api_base,
        extra_headers=dict(resolved.extra_headers),
        mastery_judgment=mastery_judge,
        ws_dir=ws_dir,
    )

    if not config.api_key:
        if resolved.provider == "codex":
            display.warn("Codex is not logged in. Run `codex login` first.")
        else:
            display.warn("No API key configured. Running in offline mode.")
            display.info("Run 'rlm-ws auth' to configure a provider.")
    elif resolved.source == "codex.chatgpt":
        display.info("Using Codex ChatGPT credentials (experimental).")
    elif resolved.source == "codex.api_key":
        display.info("Using Codex stored API key.")

    run_interactive(ws, config)


# ============================================================================
# inspect
# ============================================================================


@app.command()
def inspect(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    refs: bool = typer.Option(False, "--refs", "-r"),
    tree: bool = typer.Option(False, "--tree", "-t"),
    mastery: Optional[str] = typer.Option(None, "--mastery", "-m"),
    sessions: Optional[str] = typer.Option(
        None,
        "--sessions",
        help="Show persisted session traces for a student.",
    ),
    timeline: Optional[str] = typer.Option(
        None,
        "--timeline",
        help="Show a per-concept learning timeline for a student.",
    ),
    concept: Optional[str] = typer.Option(
        None,
        "--concept",
        help="Concept hash, short hash, or name substring for --timeline.",
    ),
    counts: bool = typer.Option(False, "--counts", "-c"),
):
    """Inspect the workspace state. With no flags, shows a summary."""
    ws, ws_dir = _resolve_workspace(workspace)

    if not any([refs, tree, mastery, sessions, timeline, counts]):
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
    if sessions:
        from .session import mastery_judgment_trace_rows, session_trace_rows

        session_refs = ws.list_refs(f"student/{sessions}/session")
        if session_refs:
            display.session_ref_table(session_refs)
            for ref_name, tip_hash in session_refs:
                display.session_trace_display(
                    ref_name,
                    session_trace_rows(ws, tip_hash),
                )
                display.mastery_judgment_trace_display(
                    ref_name,
                    mastery_judgment_trace_rows(ws, tip_hash),
                )
        else:
            display.warn(f"No session refs for student '{sessions}'")
    if timeline:
        from .session import concept_learning_timeline_rows, resolve_concept_reference

        if not concept:
            display.warn("--timeline requires --concept")
            return
        matches = resolve_concept_reference(ws, concept)
        if not matches:
            display.warn(f"No concept matched '{concept}'")
            return
        if len(matches) > 1:
            display.warn(f"Concept reference '{concept}' matched multiple concepts")
            for concept_hash, concept_name in matches[:8]:
                display.info(f"{concept_hash.short()}  {concept_name}")
            if len(matches) > 8:
                display.info(f"...and {len(matches) - 8} more")
            return
        concept_hash, concept_name = matches[0]
        display.concept_timeline_display(
            timeline,
            concept_name,
            concept_learning_timeline_rows(ws, timeline, concept_hash),
        )


# ============================================================================
# gc / export
# ============================================================================


@app.command()
def gc(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    rebuild_index: bool = typer.Option(False, "--rebuild-index"),
):
    """Run garbage collection on the workspace."""
    ws, ws_dir = _resolve_workspace(workspace)
    total, reachable, removed = ws.gc()
    display.success(f"GC complete: {removed} object(s) removed")
    display.info(f"  Total: {total}, Reachable: {reachable}, Removed: {removed}")
    if rebuild_index:
        count = ws.rebuild_index()
        display.success(f"Index rebuilt: {count} object(s) indexed")


@app.command()
def export(
    ref: str = typer.Argument(..., help="Ref name or hex hash."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
):
    """Export a subgraph as JSON."""
    from .rlm_ws import Hash

    ws, ws_dir = _resolve_workspace(workspace)
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


@app.command("import")
def import_graph(
    input_path: Path = typer.Argument(
        ...,
        help="JSON file produced by rlm-ws export.",
        exists=True,
        readable=True,
        dir_okay=False,
    ),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    set_ref: Optional[str] = typer.Option(
        None,
        "--set-ref",
        help="Set this ref to the imported root hash.",
    ),
    root: Optional[str] = typer.Option(
        None,
        "--root",
        help="Root hash to use with --set-ref if the JSON has no root field.",
    ),
):
    """Import a JSON subgraph produced by export."""
    import json

    from .rlm_ws import Hash

    ws, ws_dir = _resolve_workspace(workspace)
    json_str = input_path.read_text(encoding="utf-8")
    try:
        atoms, frames, events = ws.import_json(json_str)
    except Exception as exc:
        display.error(f"Import failed: {exc}")
        raise typer.Exit(1)

    display.success(
        f"Imported {atoms} atom(s), {frames} frame(s), {events} event(s)"
    )

    if set_ref:
        root_hash = root
        if root_hash is None:
            try:
                payload = json.loads(json_str)
            except json.JSONDecodeError:
                payload = {}
            root_hash = payload.get("root") if isinstance(payload, dict) else None

        if not isinstance(root_hash, str) or not root_hash.strip():
            display.error("--set-ref requires --root when the import has no root")
            raise typer.Exit(1)

        try:
            target = Hash.from_hex(root_hash)
        except Exception:
            display.error(f"Invalid root hash: {root_hash}")
            raise typer.Exit(1)
        ws.set_ref(set_ref, target)
        display.success(f"Set {set_ref} -> {target.short()}")
