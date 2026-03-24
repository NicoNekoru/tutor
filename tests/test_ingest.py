"""Tests for the markdown ingestion pipeline."""

import tempfile
from pathlib import Path

import rlm_ws
from rlm_ws.ingest import parse_markdown, ingest_file, ingest_directory


SAMPLE_MD = """\
# Algorithms

## Linear Search

A simple search algorithm.

### Concept: Linear Search
Linear search examines each element sequentially until the target is found or the array ends. O(n) time.

### Problem: Find Element
Given an unsorted array and a target value, return the index of the target.

## Binary Search

A faster search for sorted arrays.

<!-- prerequisite: Linear Search -->

### Concept: Binary Search
Binary search halves the search space each step. Requires sorted input. O(log n) time.

### Problem: Search Sorted Array
Given a sorted array and target, return whether the target exists.

### Example: Binary Search Steps
Array: [1,3,5,7,9]. Target: 7.
mid=5 < 7 → search right. mid=7 → found!
"""


def test_parse_markdown():
    modules = parse_markdown(SAMPLE_MD, filename="test.md")

    assert len(modules) == 1
    mod = modules[0]
    assert mod.name == "Algorithms"
    assert len(mod.lessons) == 2

    # Linear Search lesson
    ls = mod.lessons[0]
    assert ls.name == "Linear Search"
    assert ls.body  # has body text
    assert len(ls.atoms) == 2
    assert ls.atoms[0].kind == "ConceptDefinition"
    assert ls.atoms[0].name == "Linear Search"
    assert ls.atoms[1].kind == "ProblemStatement"
    assert ls.prerequisites == []

    # Binary Search lesson
    bs = mod.lessons[1]
    assert bs.name == "Binary Search"
    assert len(bs.atoms) == 3
    assert bs.atoms[0].kind == "ConceptDefinition"
    assert bs.atoms[1].kind == "ProblemStatement"
    assert bs.atoms[2].kind == "WorkedExample"
    assert bs.prerequisites == ["Linear Search"]

    print("  PASS: test_parse_markdown")


def test_parse_multiple_modules():
    md = """\
# Module One

## Lesson A

### Concept: Foo
Foo definition.

# Module Two

## Lesson B

### Concept: Bar
Bar definition.
"""
    modules = parse_markdown(md)
    assert len(modules) == 2
    assert modules[0].name == "Module One"
    assert modules[1].name == "Module Two"
    assert len(modules[0].lessons) == 1
    assert len(modules[1].lessons) == 1

    print("  PASS: test_parse_multiple_modules")


def test_ingest_file():
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        # Write sample markdown to a temp file.
        md_path = Path(d) / "course.md"
        md_path.write_text(SAMPLE_MD)

        course_hash = ingest_file(ws, md_path, course_name="Test Course")

        assert course_hash != rlm_ws.Hash.zero()
        assert ws.get_ref_hash("course/structure") == course_hash

        # Verify course structure.
        course = ws.get_frame(course_hash)
        assert course is not None
        assert course.kind == "Course"
        assert course.label == "Test Course"

        # Verify concepts are stored.
        concepts = ws.collect_atoms(course_hash, "ConceptDefinition")
        assert len(concepts) == 2  # Linear Search, Binary Search

        # Verify problems.
        problems = ws.collect_atoms(course_hash, "ProblemStatement")
        assert len(problems) == 2

        # Verify examples.
        examples = ws.collect_atoms(course_hash, "WorkedExample")
        assert len(examples) == 1

        print("  PASS: test_ingest_file")


def test_ingest_directory():
    with tempfile.TemporaryDirectory() as d:
        ws_dir = Path(d) / "workspace"
        content_dir = Path(d) / "content"
        content_dir.mkdir()

        # Write two markdown files.
        (content_dir / "01-basics.md").write_text("""\
# Basics

## Intro

### Concept: Hello World
The first program you write in any language.
""")
        (content_dir / "02-advanced.md").write_text("""\
# Advanced

## Recursion

### Concept: Recursion
A function that calls itself. Requires a base case.

### Problem: Fibonacci
Implement a recursive function to compute the nth Fibonacci number.
""")

        ws = rlm_ws.Workspace.init(str(ws_dir))
        course_hash = ingest_directory(ws, content_dir, course_name="Full Course")

        assert course_hash != rlm_ws.Hash.zero()

        # Should have 2 modules, 2 concepts, 1 problem.
        all_concepts = ws.collect_atoms(course_hash, "ConceptDefinition")
        assert len(all_concepts) == 2

        problems = ws.collect_atoms(course_hash, "ProblemStatement")
        assert len(problems) == 1

        print("  PASS: test_ingest_directory")


def test_ingest_example_file():
    """Test ingestion of the example data-structures.md file."""
    example_path = Path(__file__).parent.parent / "examples" / "data-structures.md"
    if not example_path.exists():
        print("  SKIP: test_ingest_example_file (example file not found)")
        return

    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        course_hash = ingest_file(ws, example_path, course_name="Data Structures")

        assert course_hash != rlm_ws.Hash.zero()

        concepts = ws.collect_atoms(course_hash, "ConceptDefinition")
        assert (
            len(concepts) >= 7
        )  # arrays, indexing, comparison sort, stability, binary search, invariants, linked list nodes, tradeoffs

        problems = ws.collect_atoms(course_hash, "ProblemStatement")
        assert len(problems) >= 4

        examples = ws.collect_atoms(course_hash, "WorkedExample")
        assert len(examples) >= 3

        atoms, frames, events = ws.object_counts()
        print(f"       Ingested: {atoms} atoms, {frames} frames, {events} events")

        print("  PASS: test_ingest_example_file")


if __name__ == "__main__":
    print("Running ingestion tests...")
    test_parse_markdown()
    test_parse_multiple_modules()
    test_ingest_file()
    test_ingest_directory()
    test_ingest_example_file()
    print(f"\nAll 5 tests passed!")
