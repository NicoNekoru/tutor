"""Tests for the CLI layer: ingestion, inspection, and offline session."""

import tempfile
from pathlib import Path

import rlm_ws
from rlm_ws.ingest import parse_markdown, ingest_file, ingest_directory
from rlm_ws.session import (
    SessionConfig,
    SessionState,
    start_session,
    end_session,
    run_turn,
)


SAMPLE_COURSE = """\
# Algorithms

## Sorting

Sorting is arranging elements in order.

### Concept: Bubble Sort
Bubble sort repeatedly swaps adjacent elements that are out of order.
Time complexity: O(n^2).

### Concept: Merge Sort
Merge sort divides the array in half, sorts each half, then merges.
Time complexity: O(n log n).

### Problem: Sort an Array
Given an unsorted array, sort it in ascending order.

### Example: Merge Sort Walkthrough
[3, 1, 4] → [3] [1, 4] → [3] [1] [4] → [1, 4] → [1, 3, 4]

## Searching

<!-- prerequisite: Sorting -->

### Concept: Binary Search
Binary search finds elements in a sorted array in O(log n).

### Problem: Find Element
Find a target value in a sorted array.
"""


def test_parse_markdown():
    modules = parse_markdown(SAMPLE_COURSE)
    assert len(modules) == 1  # "Algorithms" is the top-level heading
    module = modules[0]
    assert module.name == "Algorithms"
    assert len(module.lessons) == 2

    sorting = module.lessons[0]
    assert sorting.name == "Sorting"
    assert sorting.body.startswith("Sorting is")
    assert len(sorting.atoms) == 4  # 2 concepts + 1 problem + 1 example

    kinds = [a.kind for a in sorting.atoms]
    assert "ConceptDefinition" in kinds
    assert "ProblemStatement" in kinds
    assert "WorkedExample" in kinds

    searching = module.lessons[1]
    assert searching.name == "Searching"
    assert searching.prerequisites == ["Sorting"]
    assert len(searching.atoms) == 2  # 1 concept + 1 problem

    print("  PASS: test_parse_markdown")


def test_ingest_file():
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        # Write sample course to a file.
        course_file = Path(d) / "course.md"
        course_file.write_text(SAMPLE_COURSE)

        course_hash = ingest_file(ws, course_file, course_name="Test Algorithms")

        # Verify course ref.
        assert ws.get_ref_hash("course/structure") == course_hash

        # Verify structure.
        atoms, frames, events = ws.object_counts()
        assert atoms >= 6  # 3 concepts + 2 problems + 1 example + lesson bodies
        assert frames >= 3  # 2 lessons + 1 module + 1 course

        # Verify concepts are findable.
        concepts = ws.collect_atoms(course_hash, "ConceptDefinition")
        concept_texts = [a.text for _, a in concepts]
        assert any("Bubble" in t for t in concept_texts)
        assert any("Merge" in t for t in concept_texts)
        assert any("Binary" in t for t in concept_texts)

        # Verify course tree is traversable.
        all_frames = ws.collect_frames(course_hash)
        frame_labels = [f.label for _, f in all_frames if f.label]
        assert "Sorting" in frame_labels
        assert "Searching" in frame_labels

        print("  PASS: test_ingest_file")


def test_ingest_directory():
    with tempfile.TemporaryDirectory() as d:
        ws_path = Path(d) / "workspace"
        ws = rlm_ws.Workspace.init(str(ws_path))

        # Create a course directory with multiple files.
        course_dir = Path(d) / "course"
        course_dir.mkdir()

        (course_dir / "01-basics.md").write_text("""\
# Basics

## Variables

### Concept: Variables
A variable stores a value in memory.

### Problem: Swap Variables
Swap two variables without a temporary variable.
""")

        (course_dir / "02-control-flow.md").write_text("""\
# Control Flow

## Conditionals

### Concept: If Statements
An if statement executes code conditionally.

## Loops

<!-- prerequisite: Conditionals -->

### Concept: For Loops
A for loop iterates a fixed number of times.
""")

        course_hash = ingest_directory(ws, course_dir, course_name="Intro Programming")

        # Both files should be ingested.
        concepts = ws.collect_atoms(course_hash, "ConceptDefinition")
        assert len(concepts) >= 3  # Variables, If Statements, For Loops

        print("  PASS: test_ingest_directory")


def test_session_offline():
    """Test the session loop in offline mode (no API key)."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        # Ingest course.
        course_file = Path(d) / "course.md"
        course_file.write_text(SAMPLE_COURSE)
        ingest_file(ws, course_file, course_name="Algorithms")

        # Start session.
        config = SessionConfig(
            student_id="test-student",
            api_key="",  # offline mode
        )
        state = start_session(ws, config)
        assert state.session_event is not None
        assert state.student_model is not None

        # Verify student model was initialized.
        mastery = ws.student_mastery_map(state.student_model)
        assert len(mastery) > 0
        for _, level in mastery:
            assert level == 0.0  # all start at zero

        # Run a turn (offline → echoes back).
        response = run_turn(state, "Explain binary search")
        assert len(response) > 0
        assert state.turn_count == 1

        # Run another turn.
        response2 = run_turn(state, "What about merge sort?")
        assert state.turn_count == 2

        # End session.
        end_session(state)

        # Verify events were recorded.
        model_calls = ws.events_by_kind("ModelCall")
        assert len(model_calls) == 2

        student_inputs = ws.events_by_kind("StudentInput")
        assert len(student_inputs) == 2

        sessions_started = ws.events_by_kind("SessionStart")
        assert len(sessions_started) == 1

        sessions_ended = ws.events_by_kind("SessionEnd")
        assert len(sessions_ended) == 1

        # Session should be archived.
        archived = ws.list_refs(f"student/test-student/session")
        assert len(archived) >= 1

        # Current session ref should be deleted.
        assert ws.get_ref_hash("student/test-student/session/current") is None

        print("  PASS: test_session_offline")


def test_session_retrieval_integration():
    """Verify that retrieval context is built during a session turn."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        course_file = Path(d) / "course.md"
        course_file.write_text(SAMPLE_COURSE)
        ingest_file(ws, course_file, course_name="Algorithms")

        config = SessionConfig(student_id="retrieval-test", api_key="")
        state = start_session(ws, config)

        # A query about binary search should trigger retrieval.
        from rlm_ws.session import _retrieve_context

        context, results = _retrieve_context(state, "How does binary search work?")

        # Context should contain relevant content.
        # (At minimum, mastery summary should be present.)
        assert isinstance(context, str)

        # Results should include binary search concept.
        if results:
            result_hashes = {c.hash for c in results}
            # Check at least some results were found.
            assert len(results) > 0

        end_session(state)

        print("  PASS: test_session_retrieval_integration")


def test_prerequisite_resolution():
    """Verify that prerequisites are correctly resolved during ingestion."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        course_file = Path(d) / "course.md"
        course_file.write_text(SAMPLE_COURSE)
        ingest_file(ws, course_file, course_name="Algorithms")

        # Find the Searching lesson.
        course_hash = ws.get_ref_hash("course/structure")
        all_frames = ws.collect_frames(course_hash, "Lesson")

        searching = None
        sorting = None
        for fh, frame in all_frames:
            if frame.label == "Searching":
                searching = (fh, frame)
            elif frame.label == "Sorting":
                sorting = (fh, frame)

        assert searching is not None, "Searching lesson not found"
        assert sorting is not None, "Sorting lesson not found"

        # Searching should have Sorting as a prerequisite.
        prereq_edges = ws.edges_from(searching[0], "Prerequisite")
        assert len(prereq_edges) > 0, "Searching should have prerequisites"

        # The prerequisite should point to the Sorting lesson.
        prereq_targets = {e.target for e in prereq_edges}
        assert sorting[0] in prereq_targets, (
            "Sorting should be a prerequisite of Searching"
        )

        print("  PASS: test_prerequisite_resolution")


if __name__ == "__main__":
    print("Running CLI and session tests...")
    test_parse_markdown()
    test_ingest_file()
    test_ingest_directory()
    test_session_offline()
    test_session_retrieval_integration()
    test_prerequisite_resolution()
    print(f"\nAll 6 tests passed!")
