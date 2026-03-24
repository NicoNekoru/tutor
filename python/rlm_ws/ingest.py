"""
Course material ingestion: parse markdown files into workspace objects.

Convention for markdown course files:

    ---
    title: Course Name
    ---

    # Module Name

    ## Lesson Name

    Lesson body text becomes a LessonBody atom.

    ### Concept: Name
    Concept definition text becomes a ConceptDefinition atom.

    ### Problem: Name
    Problem statement text becomes a ProblemStatement atom.

    ### Example: Name
    Worked example text becomes a WorkedExample atom.

    <!-- prerequisite: Lesson Name -->

Files are processed alphabetically. Module/lesson ordering follows
file and heading order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .rlm_ws import Atom, Edge, Frame, Hash, Workspace
from . import display


@dataclass
class ParsedAtom:
    kind: str
    name: str
    text: str
    tags: list[str] = field(default_factory=list)


@dataclass
class ParsedLesson:
    name: str
    body: str = ""
    atoms: list[ParsedAtom] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class ParsedModule:
    name: str
    lessons: list[ParsedLesson] = field(default_factory=list)


@dataclass
class ParsedCourse:
    name: str
    modules: list[ParsedModule] = field(default_factory=list)


def parse_markdown(text: str, filename: str = "") -> list[ParsedModule]:
    """Parse a single markdown file into modules."""
    modules: list[ParsedModule] = []
    current_module: ParsedModule | None = None
    current_lesson: ParsedLesson | None = None
    current_atom: ParsedAtom | None = None
    buffer: list[str] = []

    def flush_buffer() -> str:
        result = "\n".join(buffer).strip()
        buffer.clear()
        return result

    def flush_atom():
        nonlocal current_atom
        if current_atom:
            current_atom.text = flush_buffer()
            if current_lesson:
                current_lesson.atoms.append(current_atom)
            current_atom = None

    def flush_lesson_body():
        if current_lesson and not current_lesson.body and buffer:
            current_lesson.body = flush_buffer()

    for line in text.splitlines():
        # Check for prerequisite comments.
        prereq_match = re.match(r"<!--\s*prerequisite:\s*(.+?)\s*-->", line)
        if prereq_match and current_lesson:
            current_lesson.prerequisites.append(prereq_match.group(1).strip())
            continue

        # Module heading (# ...)
        if line.startswith("# ") and not line.startswith("## "):
            flush_atom()
            flush_lesson_body()
            name = line[2:].strip()
            current_module = ParsedModule(name=name)
            modules.append(current_module)
            current_lesson = None
            current_atom = None
            buffer.clear()
            continue

        # Lesson heading (## ...)
        if line.startswith("## ") and not line.startswith("### "):
            flush_atom()
            flush_lesson_body()
            name = line[3:].strip()
            current_lesson = ParsedLesson(name=name)
            if current_module is None:
                current_module = ParsedModule(name=Path(filename).stem or "Main")
                modules.append(current_module)
            current_module.lessons.append(current_lesson)
            current_atom = None
            buffer.clear()
            continue

        # Atom heading (### Concept:/Problem:/Example: ...)
        if line.startswith("### "):
            flush_atom()
            flush_lesson_body()
            heading = line[4:].strip()

            kind = "Blob"
            name = heading
            for prefix, atom_kind in [
                ("Concept:", "ConceptDefinition"),
                ("Problem:", "ProblemStatement"),
                ("Example:", "WorkedExample"),
            ]:
                if heading.startswith(prefix):
                    kind = atom_kind
                    name = heading[len(prefix) :].strip()
                    break

            current_atom = ParsedAtom(kind=kind, name=name)
            buffer.clear()
            continue

        # Regular content line.
        buffer.append(line)

    # Flush remaining.
    flush_atom()
    flush_lesson_body()

    return modules


def ingest_directory(ws: Workspace, path: Path, course_name: str = "") -> Hash:
    """Ingest all markdown files from a directory into the workspace.

    Returns the course frame hash.
    """
    md_files = sorted(path.glob("**/*.md"))
    if not md_files:
        display.warn(f"No .md files found in {path}")
        return Hash.zero()

    display.info(f"Found {len(md_files)} markdown file(s)")

    all_modules: list[ParsedModule] = []
    for f in md_files:
        display.info(f"Parsing {f.name}")
        text = f.read_text(encoding="utf-8")
        modules = parse_markdown(text, filename=f.name)
        all_modules.extend(modules)

    if not all_modules:
        display.warn("No modules found in the markdown files")
        return Hash.zero()

    if not course_name:
        course_name = all_modules[0].name if all_modules else path.name

    return _build_course(ws, course_name, all_modules)


def ingest_file(ws: Workspace, path: Path, course_name: str = "") -> Hash:
    """Ingest a single markdown file."""
    text = path.read_text(encoding="utf-8")
    modules = parse_markdown(text, filename=path.name)

    if not course_name:
        course_name = modules[0].name if modules else path.stem

    return _build_course(ws, course_name, modules)


def _build_course(
    ws: Workspace,
    course_name: str,
    modules: list[ParsedModule],
) -> Hash:
    """Build workspace objects from parsed course structure."""
    # Track lesson names → hashes for prerequisite resolution.
    lesson_hashes: dict[str, Hash] = {}
    module_hashes: list[Hash] = []

    total_atoms = 0
    total_lessons = 0

    for module in modules:
        lesson_frame_hashes: list[Hash] = []

        for lesson in module.lessons:
            edges: list[Edge] = []

            # Lesson body atom.
            if lesson.body:
                body_hash = ws.put_atom(
                    Atom(
                        "LessonBody",
                        lesson.body,
                        tags=["lesson-body"],
                    )
                )
                edges.append(Edge("Contains", body_hash))
                total_atoms += 1

            # Content atoms.
            for atom in lesson.atoms:
                atom_hash = ws.put_atom(
                    Atom(
                        atom.kind,
                        atom.text,
                        tags=atom.tags or [atom.kind.lower()],
                    )
                )
                total_atoms += 1

                label = {
                    "ConceptDefinition": "CoversConcept",
                    "ProblemStatement": "IncludesProblem",
                    "WorkedExample": "IncludesExample",
                }.get(atom.kind, "Contains")
                edges.append(Edge(label, atom_hash))

            # Build the lesson frame (prerequisites resolved in a second pass).
            lesson_hash = ws.put_frame(
                Frame(
                    "Lesson",
                    edges,
                    label=lesson.name,
                    tags=lesson.tags,
                )
            )
            lesson_hashes[lesson.name] = lesson_hash
            lesson_frame_hashes.append(lesson_hash)
            total_lessons += 1

        # Module frame.
        module_edges = [Edge("Contains", lh) for lh in lesson_frame_hashes]
        module_hash = ws.put_frame(
            Frame(
                "Module",
                module_edges,
                label=module.name,
            )
        )
        module_hashes.append(module_hash)

    # Second pass: resolve prerequisites by rebuilding lesson frames.
    for module in modules:
        for lesson in module.lessons:
            if not lesson.prerequisites:
                continue

            old_hash = lesson_hashes[lesson.name]
            old_frame = ws.get_frame(old_hash)
            if old_frame is None:
                continue

            new_edges = list(old_frame.edges)
            for prereq_name in lesson.prerequisites:
                prereq_hash = lesson_hashes.get(prereq_name)
                if prereq_hash:
                    new_edges.append(Edge("Prerequisite", prereq_hash))
                else:
                    display.warn(
                        f"Prerequisite '{prereq_name}' not found for lesson '{lesson.name}'"
                    )

            if len(new_edges) > len(old_frame.edges):
                new_hash = ws.put_frame(
                    Frame(
                        "Lesson",
                        new_edges,
                        label=lesson.name,
                        tags=old_frame.tags,
                    )
                )
                lesson_hashes[lesson.name] = new_hash

    # Course frame.
    course_edges = [Edge("Contains", mh) for mh in module_hashes]
    course_hash = ws.put_frame(
        Frame(
            "Course",
            course_edges,
            label=course_name,
        )
    )
    ws.set_ref("course/structure", course_hash)

    display.success(f"Ingested course '{course_name}'")
    display.info(
        f"  {len(modules)} module(s), {total_lessons} lesson(s), {total_atoms} atom(s)"
    )

    return course_hash
