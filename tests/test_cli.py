"""Tests for templates, ingestion, session, and prerequisites."""

import json
import tempfile
from pathlib import Path

import rlm_ws
from rlm_ws.ingest import parse_markdown, ingest_file, ingest_directory
from rlm_ws.session import SessionConfig, start_session, end_session, run_turn
from rlm_ws.templates import discover_templates, apply_template


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


# ============================================================================
# Template discovery tests
# ============================================================================


def test_discover_bundled_templates():
    templates = discover_templates()
    assert "starter" in templates
    for key, tmpl in templates.items():
        assert tmpl.name
        assert tmpl.description
        assert tmpl.path.is_dir()
        assert (tmpl.path / "template.json").exists()
    print("  PASS: test_discover_bundled_templates")


def test_discover_custom_template():
    with tempfile.TemporaryDirectory() as d:
        custom_dir = Path(d) / "my-templates" / "calculus"
        custom_dir.mkdir(parents=True)
        (custom_dir / "template.json").write_text(
            json.dumps(
                {
                    "name": "Calculus",
                    "description": "Intro to calculus",
                }
            )
        )
        content_dir = custom_dir / "content"
        content_dir.mkdir()
        (content_dir / "course.md").write_text("""\
# Calculus

## Limits

### Concept: Limits
A limit describes the value a function approaches.
""")

        # Discover from the custom directory.
        templates = discover_templates(Path(d) / "my-templates")
        assert "calculus" in templates
        assert templates["calculus"].name == "Calculus"
        assert templates["calculus"].path.resolve() == custom_dir.resolve()

        # Bundled templates should still be present.
        assert "starter" in templates

        print("  PASS: test_discover_custom_template")


def test_custom_template_shadows_bundled():
    """A custom template with the same key as a bundled one should win."""
    with tempfile.TemporaryDirectory() as d:
        custom_dir = Path(d) / "templates" / "starter"
        custom_dir.mkdir(parents=True)
        (custom_dir / "template.json").write_text(
            json.dumps(
                {
                    "name": "My Custom Starter",
                    "description": "Overrides the bundled starter",
                }
            )
        )

        templates = discover_templates(Path(d) / "templates")
        assert templates["starter"].name == "My Custom Starter"

        print("  PASS: test_custom_template_shadows_bundled")


def test_apply_template_substitution():
    """{{course_name}} in text files should be replaced."""
    with tempfile.TemporaryDirectory() as d:
        templates = discover_templates()
        starter = templates["starter"]

        target = Path(d) / "workspace"
        target.mkdir()

        written = apply_template(starter, target, "My Cool Course")
        assert len(written) > 0

        # The starter template's course.md should have the course name.
        course_md = target / "content" / "course.md"
        assert course_md.exists()
        content = course_md.read_text()
        assert "My Cool Course" in content
        assert "{{course_name}}" not in content

        # template.json should NOT be copied.
        assert not (target / "template.json").exists()

        print("  PASS: test_apply_template_substitution")


def test_starter_template_ingestable():
    with tempfile.TemporaryDirectory() as d:
        ws_dir = Path(d) / "starter"
        ws_dir.mkdir()
        ws = rlm_ws.Workspace.init(str(ws_dir))

        templates = discover_templates()
        apply_template(templates["starter"], ws_dir, "Starter")
        course_hash = ingest_directory(ws, ws_dir / "content", course_name="Starter")

        concepts = ws.collect_atoms(course_hash, "ConceptDefinition")
        problems = ws.collect_atoms(course_hash, "ProblemStatement")
        examples = ws.collect_atoms(course_hash, "WorkedExample")

        assert len(concepts) >= 1, f"Expected >=1 concept, got {len(concepts)}"
        assert len(problems) >= 1, f"Expected >=1 problem, got {len(problems)}"
        assert len(examples) >= 1, f"Expected >=1 example, got {len(examples)}"

        print("  PASS: test_starter_template_ingestable")


# ============================================================================
# Ingestion tests
# ============================================================================


def test_parse_markdown():
    modules = parse_markdown(SAMPLE_COURSE)
    assert len(modules) == 1
    module = modules[0]
    assert module.name == "Algorithms"
    assert len(module.lessons) == 2

    sorting = module.lessons[0]
    assert sorting.name == "Sorting"
    assert sorting.body.startswith("Sorting is")
    assert len(sorting.atoms) == 4

    kinds = [a.kind for a in sorting.atoms]
    assert "ConceptDefinition" in kinds
    assert "ProblemStatement" in kinds
    assert "WorkedExample" in kinds

    searching = module.lessons[1]
    assert searching.prerequisites == ["Sorting"]

    print("  PASS: test_parse_markdown")


def test_ingest_file():
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        course_file = Path(d) / "course.md"
        course_file.write_text(SAMPLE_COURSE)
        course_hash = ingest_file(ws, course_file, course_name="Test")

        assert ws.get_ref_hash("course/structure") == course_hash

        concepts = ws.collect_atoms(course_hash, "ConceptDefinition")
        texts = [a.text for _, a in concepts]
        assert any("Bubble" in t for t in texts)
        assert any("Binary" in t for t in texts)

        print("  PASS: test_ingest_file")


def test_prerequisite_resolution():
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")

        course_hash = ws.get_ref_hash("course/structure")
        all_frames = ws.collect_frames(course_hash, "Lesson")

        searching = sorting = None
        for fh, frame in all_frames:
            if frame.label == "Searching":
                searching = (fh, frame)
            elif frame.label == "Sorting":
                sorting = (fh, frame)

        assert searching and sorting
        prereqs = ws.edges_from(searching[0], "Prerequisite")
        assert sorting[0] in {e.target for e in prereqs}

        print("  PASS: test_prerequisite_resolution")


# ============================================================================
# Session tests
# ============================================================================


def test_session_offline():
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")

        config = SessionConfig(student_id="test-student", api_key="")
        state = start_session(ws, config)
        assert state.session_event is not None
        assert state.student_model is not None

        response = run_turn(state, "Explain binary search")
        assert len(response) > 0
        assert state.turn_count == 1

        end_session(state)

        assert len(ws.events_by_kind("ModelCall")) == 1
        assert len(ws.events_by_kind("SessionStart")) == 1
        assert len(ws.events_by_kind("SessionEnd")) == 1

        print("  PASS: test_session_offline")


def test_session_retrieval_integration():
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")

        config = SessionConfig(student_id="retrieval-test", api_key="")
        state = start_session(ws, config)

        from rlm_ws.session import _retrieve_context

        context, results = _retrieve_context(state, "How does binary search work?")
        assert isinstance(context, str)
        assert isinstance(results, list)

        end_session(state)

        print("  PASS: test_session_retrieval_integration")


def test_workspace_toml_system_prompt():
    """Verify workspace.toml system prompt flows into the session."""
    from rlm_ws.templates import (
        discover_templates,
        apply_template,
        build_system_prompt,
        save_workspace_config,
    )

    with tempfile.TemporaryDirectory() as d:
        ws_dir = Path(d) / "ws"
        ws_dir.mkdir()
        ws = rlm_ws.Workspace.init(str(ws_dir))

        # Simulate what init does: apply template, build and save system prompt.
        templates = discover_templates()
        tmpl = templates["starter"]
        apply_template(tmpl, ws_dir, "Test Course")

        # Simulate answers (normally interactive).
        answers = {
            "course_name": "Test Course",
            "student_identity": "A beginner",
            "tutor_identity": "A professor",
            "relationship": "Casual",
            "syllabus": "no",
            "formal_assignments": "no",
            "focus": "Understanding basics",
            "context": "",
        }
        system_prompt = build_system_prompt(tmpl, answers)
        save_workspace_config(ws_dir, "starter", answers, system_prompt)

        # Verify workspace.toml was written.
        assert (ws_dir / "workspace.toml").exists()

        # Ingest content.
        from rlm_ws.ingest import ingest_directory

        ingest_directory(ws, ws_dir / "content", course_name="Test Course")

        # Start session — should load from workspace.toml.
        config = SessionConfig(student_id="toml-test", api_key="", ws_dir=ws_dir)
        state = start_session(ws, config)

        # The system prompt should contain our configured identities.
        assert "A beginner" in state.config.system_prompt
        assert "A professor" in state.config.system_prompt
        assert "Understanding basics" in state.config.system_prompt

        end_session(state)

        print("  PASS: test_workspace_toml_system_prompt")


def test_responses_text_extraction():
    from rlm_ws.session import _extract_responses_text

    assert _extract_responses_text({"output_text": "hello"}) == "hello"
    assert (
        _extract_responses_text(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "hello "},
                            {"type": "output_text", "text": "world"},
                        ],
                    }
                ]
            }
        )
        == "hello world"
    )

    print("  PASS: test_responses_text_extraction")


if __name__ == "__main__":
    print("Running CLI and session tests...")
    test_discover_bundled_templates()
    test_discover_custom_template()
    test_custom_template_shadows_bundled()
    test_apply_template_substitution()
    test_starter_template_ingestable()
    test_parse_markdown()
    test_ingest_file()
    test_prerequisite_resolution()
    test_session_offline()
    test_session_retrieval_integration()
    test_workspace_toml_system_prompt()
    test_responses_text_extraction()
    print("\nAll 12 tests passed!")
