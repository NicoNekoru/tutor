"""
Template system for new workspaces.

Templates are directories containing:
  template.toml     ← metadata, prompts, system prompt template
  COURSE_FORMAT.md  ← (optional) format guide copied to workspace
  content/          ← (optional) course markdown, auto-ingested

Search order:
  1. --templates-dir / $RLM_TEMPLATES_DIR
  2. <package>/_template_data/  (bundled)

template.toml format:

  [template]
  name = "..."
  description = "..."

  [[prompts]]
  key = "student_identity"
  question = "Who am I?"
  type = "text"           # text | confirm | choice
  help = "..."            # shown as hint
  default = ""            # optional default
  required = true         # optional
  choices = [...]         # for type = "choice"

  [system_prompt]
  template = "...{{key}}..."
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]


@dataclass
class PromptSpec:
    """A single prompt to ask during init."""

    key: str
    question: str
    type: str = "text"  # text | confirm | choice
    help: str = ""
    default: str | bool | None = None
    required: bool = False
    choices: list[str] = field(default_factory=list)


@dataclass
class Template:
    """A discovered template."""

    key: str
    name: str
    description: str
    path: Path
    prompts: list[PromptSpec] = field(default_factory=list)
    system_prompt_template: str = ""


# File extensions that get {{placeholder}} substitution.
_TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".cfg",
    ".ini",
    ".rst",
    ".html",
    ".py",
    ".rs",
}


def _bundled_templates_dir() -> Path:
    return Path(__file__).parent / "_template_data"


def _template_search_dirs(extra: Path | None = None) -> list[Path]:
    dirs: list[Path] = []
    if extra is not None:
        p = extra.resolve()
        if p.is_dir():
            dirs.append(p)
    env_dir = os.environ.get("RLM_TEMPLATES_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.is_dir():
            dirs.append(p)
    bundled = _bundled_templates_dir()
    if bundled.is_dir():
        dirs.append(bundled)
    return dirs


def _parse_template_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _load_template(key: str, directory: Path) -> Template | None:
    """Load a template from a directory. Returns None if invalid."""
    toml_path = directory / "template.toml"
    json_path = directory / "template.json"

    if toml_path.exists():
        try:
            data = _parse_template_toml(toml_path)
        except Exception:
            return None

        meta = data.get("template", {})
        prompts = []
        for p in data.get("prompts", []):
            prompts.append(
                PromptSpec(
                    key=p["key"],
                    question=p["question"],
                    type=p.get("type", "text"),
                    help=p.get("help", ""),
                    default=p.get("default"),
                    required=p.get("required", False),
                    choices=p.get("choices", []),
                )
            )

        sys_prompt = data.get("system_prompt", {}).get("template", "")

        return Template(
            key=key,
            name=meta.get("name", key),
            description=meta.get("description", ""),
            path=directory,
            prompts=prompts,
            system_prompt_template=sys_prompt,
        )

    elif json_path.exists():
        # Legacy JSON support.
        import json

        try:
            meta = json.loads(json_path.read_text())
        except Exception:
            return None
        return Template(
            key=key,
            name=meta.get("name", key),
            description=meta.get("description", ""),
            path=directory,
        )

    return None


def discover_templates(extra_dir: Path | None = None) -> dict[str, Template]:
    """Scan template directories and return all available templates."""
    templates: dict[str, Template] = {}

    for search_dir in _template_search_dirs(extra_dir):
        for entry in sorted(search_dir.iterdir()):
            if not entry.is_dir():
                continue
            key = entry.name
            if key in templates:
                continue  # higher-priority source already found
            tmpl = _load_template(key, entry)
            if tmpl is not None:
                templates[key] = tmpl

    return templates


def run_prompts(
    template: Template,
    course_name: str,
) -> dict[str, str]:
    """Interactively run a template's prompts. Returns answers keyed by prompt key."""
    from rich.prompt import Prompt, Confirm

    from . import display

    answers: dict[str, str] = {"course_name": course_name}

    if not template.prompts:
        return answers

    display.console.print()
    display.console.print("[bold]Configure your workspace:[/bold]")
    display.console.print()

    for spec in template.prompts:
        if spec.help:
            display.console.print(f"  [dim]{spec.help}[/dim]")

        if spec.type == "confirm":
            default = spec.default if isinstance(spec.default, bool) else True
            result = Confirm.ask(f"  {spec.question}", default=default)
            answers[spec.key] = "yes" if result else "no"

        elif spec.type == "choice":
            display.console.print(f"  {spec.question}")
            for i, choice in enumerate(spec.choices, 1):
                display.console.print(f"    [cyan]{i}[/cyan]  {choice}")
            default_idx = "1"
            if spec.default and spec.default in spec.choices:
                default_idx = str(spec.choices.index(spec.default) + 1)
            idx = Prompt.ask(
                "  Select",
                choices=[str(i) for i in range(1, len(spec.choices) + 1)],
                default=default_idx,
            )
            answers[spec.key] = spec.choices[int(idx) - 1]

        else:  # text
            default = str(spec.default) if spec.default else ""
            while True:
                result = Prompt.ask(
                    f"  {spec.question}",
                    default=default or None,
                )
                if result or not spec.required:
                    break
                display.warn("This field is required.")
            answers[spec.key] = result or ""

        display.console.print()

    return answers


def build_system_prompt(template: Template, answers: dict[str, str]) -> str:
    """Interpolate answers into the template's system prompt."""
    prompt = template.system_prompt_template
    for key, value in answers.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", value)
    return prompt


def save_workspace_config(
    ws_dir: Path,
    template_key: str,
    answers: dict[str, str],
    system_prompt: str,
) -> Path:
    """Save workspace configuration to workspace.toml."""
    config = {
        "workspace": {
            "template": template_key,
            "course_name": answers.get("course_name", ""),
        },
        "identity": {k: v for k, v in answers.items() if k != "course_name"},
        "system_prompt": {"content": system_prompt},
    }

    config_path = ws_dir / "workspace.toml"

    if tomli_w is not None:
        with open(config_path, "wb") as f:
            tomli_w.dump(config, f)
    else:
        # Fallback: write manually.
        lines = []
        lines.append("[workspace]")
        lines.append(f'template = "{template_key}"')
        lines.append(f'course_name = "{answers.get("course_name", "")}"')
        lines.append("")
        lines.append("[identity]")
        for k, v in answers.items():
            if k != "course_name":
                # Escape for TOML.
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                if "\n" in v:
                    lines.append(f'{k} = """')
                    lines.append(v)
                    lines.append('"""')
                else:
                    lines.append(f'{k} = "{escaped}"')
        lines.append("")
        lines.append("[system_prompt]")
        lines.append('content = """')
        lines.append(system_prompt)
        lines.append('"""')
        config_path.write_text("\n".join(lines), encoding="utf-8")

    return config_path


def load_workspace_config(ws_dir: Path) -> dict:
    """Load workspace.toml. Returns empty dict if not found."""
    config_path = ws_dir / "workspace.toml"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def apply_template(
    template: Template,
    target_dir: Path,
    course_name: str,
) -> list[Path]:
    """Copy a template's files into the target directory.

    Text files have {{course_name}} replaced. template.toml is not copied.
    """
    written: list[Path] = []

    for src in sorted(template.path.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(template.path)
        if rel.name in ("template.toml", "template.json"):
            continue

        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        if src.suffix.lower() in _TEXT_EXTENSIONS:
            try:
                content = src.read_text(encoding="utf-8")
                content = content.replace("{{course_name}}", course_name)
                dest.write_text(content, encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(src, dest)
        else:
            shutil.copy2(src, dest)

        written.append(dest)

    return written
