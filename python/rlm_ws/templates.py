"""
Template system for new workspaces.

Templates are directories containing:
  template.json     ← {"name": "...", "description": "..."}
  ...               ← any files/dirs to copy into the workspace

Search order for templates:
  1. --templates /explicit/path    (CLI argument)
  2. $RLM_TEMPLATES_DIR            (environment variable)
  3. <package>/templates/          (bundled with rlm-ws)

Text files (.md, .txt, .toml, .json, .yaml, .yml, .cfg, .ini, .rst, .html)
have {{course_name}} placeholders replaced during copy.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Template:
    """A discovered template."""

    key: str  # directory name (used as --template value)
    name: str  # human-readable name from template.json
    description: str  # shown during init
    path: Path  # absolute path to the template directory


# File extensions that get placeholder substitution.
_TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".toml",
    ".json",
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
    """Path to the _template_data/ directory shipped with the package."""
    return Path(__file__).parent / "_template_data"


def _template_search_dirs(extra: Path | None = None) -> list[Path]:
    """Return template search directories in priority order."""
    dirs: list[Path] = []

    # 1. Explicit path (highest priority).
    if extra is not None:
        p = extra.resolve()
        if p.is_dir():
            dirs.append(p)

    # 2. Environment variable.
    env_dir = os.environ.get("RLM_TEMPLATES_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.is_dir():
            dirs.append(p)

    # 3. Bundled templates (lowest priority).
    bundled = _bundled_templates_dir()
    if bundled.is_dir():
        dirs.append(bundled)

    return dirs


def discover_templates(extra_dir: Path | None = None) -> dict[str, Template]:
    """Scan template directories and return all available templates.

    Templates in earlier search paths shadow later ones with the same key.
    """
    templates: dict[str, Template] = {}

    for search_dir in _template_search_dirs(extra_dir):
        if not search_dir.is_dir():
            continue

        for entry in sorted(search_dir.iterdir()):
            if not entry.is_dir():
                continue

            meta_path = entry / "template.json"
            if not meta_path.exists():
                continue

            key = entry.name
            if key in templates:
                continue  # higher-priority source already found

            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            templates[key] = Template(
                key=key,
                name=meta.get("name", key),
                description=meta.get("description", ""),
                path=entry,
            )

    return templates


def apply_template(
    template: Template,
    target_dir: Path,
    course_name: str,
) -> list[Path]:
    """Copy a template's files into the target directory.

    Text files have {{course_name}} replaced. Binary files are copied as-is.
    template.json itself is not copied.

    Returns the list of files written.
    """
    written: list[Path] = []

    for src in sorted(template.path.rglob("*")):
        if not src.is_file():
            continue

        # Skip the metadata file.
        rel = src.relative_to(template.path)
        if rel.name == "template.json":
            continue

        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        if src.suffix.lower() in _TEXT_EXTENSIONS:
            # Text file: substitute placeholders.
            try:
                content = src.read_text(encoding="utf-8")
                content = content.replace("{{course_name}}", course_name)
                dest.write_text(content, encoding="utf-8")
            except UnicodeDecodeError:
                # Fall back to binary copy.
                shutil.copy2(src, dest)
        else:
            shutil.copy2(src, dest)

        written.append(dest)

    return written
