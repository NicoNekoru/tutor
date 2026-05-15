"""Tests for templates, ingestion, session, and prerequisites."""

import json
import tempfile
from pathlib import Path

import rlm_ws
from rlm_ws.ingest import parse_markdown, ingest_file, ingest_directory
from rlm_ws.session import (
    SessionConfig,
    end_session,
    mastery_judgment_trace_rows,
    run_turn,
    session_trace_rows,
    start_session,
)
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
        course_hash = ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")
        binary_hash = next(
            concept_hash
            for concept_hash, atom in ws.collect_atoms(
                course_hash,
                "ConceptDefinition",
            )
            if "Binary search" in atom.text
        )

        config = SessionConfig(student_id="test-student", api_key="")
        state = start_session(ws, config)
        assert state.session_event is not None
        assert state.student_model is not None

        response = run_turn(state, "Explain binary search")
        assert len(response) > 0
        assert state.turn_count == 1

        end_session(state)

        assert len(ws.events_by_kind("ModelCall")) == 1
        assert len(ws.events_by_kind("RetrievalPerformed")) == 1
        assert len(ws.events_by_kind("StudentModelUpdate")) == 1
        assert len(ws.events_by_kind("Admin")) == 1
        assert len(ws.events_by_kind("SessionStart")) == 1
        assert len(ws.events_by_kind("SessionEnd")) == 1
        assert len(ws.frames_by_kind("CallContext")) == 1
        mastery = dict(ws.student_mastery_map(state.student_model))
        assert mastery[binary_hash] > 0.0

        evidence_event = ws.get_event(ws.events_by_kind("Admin")[0])
        assert evidence_event is not None
        assert "turn-evidence" in evidence_event.tags

        model_call = ws.get_event(ws.events_by_kind("ModelCall")[0])
        assert model_call is not None
        input_roles = {ref.role for ref in model_call.inputs}
        assert "call_context" in input_roles
        assert "retrieval_event" in input_roles

        context_ref = next(
            ref.hash for ref in model_call.inputs if ref.role == "call_context"
        )
        context_frame = ws.get_frame(context_ref)
        assert context_frame is not None
        assert context_frame.kind == "CallContext"
        edge_labels = {edge.label for edge in context_frame.edges}
        assert "ReceivedInput" in edge_labels
        assert "UsedScope" in edge_labels

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


def test_session_mastery_update_command():
    from rlm_ws import session as session_mod

    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        course_hash = ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")

        binary_hash = None
        for concept_hash, atom in ws.collect_atoms(course_hash, "ConceptDefinition"):
            if "Binary search" in atom.text:
                binary_hash = concept_hash
                break
        assert binary_hash is not None

        config = SessionConfig(student_id="cmd-test", api_key="")
        state = start_session(ws, config)

        old_call_model = session_mod._call_model
        try:
            session_mod._call_model = lambda _state, _system: (
                "Tutor prose that should not be shown.\n\n"
                "```json\n"
                "{\n"
                '  "visible_text": "Good, binary search is getting clearer.",\n'
                '  "commands": [\n'
                "    {\n"
                '      "kind": "mastery_update",\n'
                '      "arguments": {\n'
                f'        "concept": "{binary_hash.to_hex()}",\n'
                '        "level": 0.7,\n'
                '        "reason": "student explained the halving invariant"\n'
                "      }\n"
                "    }\n"
                "  ]\n"
                "}\n"
                "```"
            )
            response = run_turn(state, "Binary search halves the search space.")
        finally:
            session_mod._call_model = old_call_model

        assert response == "Good, binary search is getting clearer."
        assert len(ws.events_by_kind("RetrievalPerformed")) == 1
        assert len(ws.frames_by_kind("CallContext")) == 1
        assert len(ws.events_by_kind("StudentModelUpdate")) == 1

        mastery_ref = ws.get_ref_hash("student/cmd-test/mastery")
        assert mastery_ref == state.student_model
        mastery = dict(ws.student_mastery_map(mastery_ref))
        assert abs(mastery[binary_hash] - 0.7) < 1e-9

        update_event = ws.get_event(ws.events_by_kind("StudentModelUpdate")[0])
        assert update_event is not None
        assert any(ref.role == "model_output" for ref in update_event.inputs)
        assert any(ref.role == "turn_evidence" for ref in update_event.inputs)
        assert any(ref.role == "updated" for ref in update_event.outputs)

        end_session(state)

        print("  PASS: test_session_mastery_update_command")


def test_session_subcall_command_records_child_call():
    from rlm_ws import session as session_mod

    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        course_hash = ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")

        binary_hash = None
        for concept_hash, atom in ws.collect_atoms(course_hash, "ConceptDefinition"):
            if "Binary search" in atom.text:
                binary_hash = concept_hash
                break
        assert binary_hash is not None

        config = SessionConfig(student_id="subcall-test", api_key="")
        state = start_session(ws, config)

        calls = []
        old_call_model = session_mod._call_model

        def fake_call_model(fake_state, _system):
            calls.append(list(fake_state.messages))
            if len(calls) == 1:
                return (
                    "```json\n"
                    "{\n"
                    '  "visible_text": "Let me check the invariant separately.",\n'
                    '  "commands": [\n'
                    "    {\n"
                    '      "kind": "subcall",\n'
                    '      "arguments": {\n'
                    '        "intent": "explain_concept",\n'
                    f'        "concepts": ["{binary_hash.to_hex()}"],\n'
                    '        "prompt": "Explain the binary search invariant."\n'
                    "      }\n"
                    "    }\n"
                    "  ]\n"
                    "}\n"
                    "```"
                )
            if len(calls) == 2:
                return "Child explanation of the invariant."
            return (
                "```json\n"
                "{\n"
                '  "visible_text": "Final answer composed from the child invariant explanation.",\n'
                '  "commands": [\n'
                "    {\n"
                '      "kind": "mastery_update",\n'
                '      "arguments": {\n'
                f'        "concept": "{binary_hash.to_hex()}",\n'
                '        "level": 0.6,\n'
                '        "reason": "student followed the recursive invariant check"\n'
                "      }\n"
                "    }\n"
                "  ]\n"
                "}\n"
                "```"
            )

        try:
            session_mod._call_model = fake_call_model
            response = run_turn(state, "Can you explain binary search?")
        finally:
            session_mod._call_model = old_call_model

        assert response == "Final answer composed from the child invariant explanation."
        assert len(calls) == 3
        assert calls[1][0]["content"] == "Explain the binary search invariant."
        assert "Child explanation of the invariant." in calls[2][-1]["content"]

        model_calls = [
            (h, ws.get_event(h)) for h in ws.events_by_kind("ModelCall")
        ]
        root_hash, root_call = next(
            (h, e)
            for h, e in model_calls
            if e.trace.call_depth == 0
            and any(ref.role == "child_call" for ref in e.outputs)
        )
        child_hash, child_call = next(
            (h, e) for h, e in model_calls if e.trace.call_depth == 1
        )
        continuation_hash, continuation_call = next(
            (h, e)
            for h, e in model_calls
            if e.trace.call_depth == 0 and root_hash in e.parents
        )

        assert root_hash != child_hash
        assert continuation_hash != root_hash
        assert child_call.trace.model == "gpt-5.4-nano"
        assert any(
            ref.role == "child_call" and ref.hash == child_hash
            for ref in root_call.outputs
        )
        assert any(ref.role == "parent_draft" for ref in continuation_call.inputs)
        assert any(ref.role == "child_output" for ref in continuation_call.inputs)
        continuation_output = ws.get_atom(continuation_call.outputs[0].hash)
        assert continuation_output.structured["merge_rule"] == (
            "compose_parent_draft_with_child_outputs"
        )
        assert len(ws.events_by_kind("RetrievalPerformed")) == 2
        assert len(ws.frames_by_kind("CallContext")) == 2

        update_events = ws.events_by_kind("StudentModelUpdate")
        assert len(update_events) == 1
        assert state.last_event == update_events[0]
        mastery = dict(ws.student_mastery_map(state.student_model))
        assert abs(mastery[binary_hash] - 0.6) < 1e-9
        assert (
            ws.get_ref_hash("student/subcall-test/session/current")
            == state.last_event
        )

        child_input_roles = {ref.role for ref in child_call.inputs}
        assert "call_context" in child_input_roles
        assert "subcall_request" in child_input_roles
        assert "retrieval_event" in child_input_roles

        end_session(state)
        session_tip = ws.get_ref_hash("student/subcall-test/session/session-1t")
        assert session_tip is not None
        rows = session_trace_rows(ws, session_tip)
        assert rows[0].kind == "SessionStart"
        assert rows[-1].kind == "SessionEnd"
        assert any(
            row.kind == "ModelCall"
            and row.depth == 1
            and row.model == "gpt-5.4-nano"
            for row in rows
        )
        assert any("child_call" in row.output_roles for row in rows)
        assert any("child_output" in row.input_roles for row in rows)

        print("  PASS: test_session_subcall_command_records_child_call")


def test_session_subcall_budget_records_engine_notice():
    from rlm_ws import session as session_mod

    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")

        config = SessionConfig(
            student_id="budget-test",
            api_key="",
            max_subcalls_per_turn=0,
        )
        state = start_session(ws, config)

        old_call_model = session_mod._call_model
        try:
            session_mod._call_model = lambda _state, _system: (
                "```json\n"
                "{\n"
                '  "visible_text": "I will answer directly.",\n'
                '  "commands": [\n'
                "    {\n"
                '      "kind": "subcall",\n'
                '      "arguments": {\n'
                '        "prompt": "Explain this separately."\n'
                "      }\n"
                "    }\n"
                "  ]\n"
                "}\n"
                "```"
            )
            response = run_turn(state, "Explain binary search")
        finally:
            session_mod._call_model = old_call_model

        assert response == "I will answer directly."
        assert len(ws.events_by_kind("ModelCall")) == 1
        root_call = ws.get_event(ws.events_by_kind("ModelCall")[0])
        assert root_call is not None
        notice_refs = [
            ref for ref in root_call.outputs if ref.role == "engine_notice"
        ]
        assert len(notice_refs) == 1
        notice_event = ws.get_event(notice_refs[0].hash)
        assert notice_event is not None
        assert "subcall_budget_exceeded" in notice_event.tags
        notice_atom = ws.get_atom(notice_event.outputs[0].hash)
        assert notice_atom.structured["kind"] == "subcall_budget_exceeded"
        assert not any(ref.role == "child_call" for ref in root_call.outputs)

        end_session(state)
        session_tip = ws.get_ref_hash("student/budget-test/session/session-1t")
        rows = session_trace_rows(ws, session_tip)
        assert any("engine_notice" in row.output_roles for row in rows)

        print("  PASS: test_session_subcall_budget_records_engine_notice")


def test_responses_text_extraction():
    from rlm_ws.session import _extract_responses_text, _parse_model_output

    concept_hash = rlm_ws.Hash.compute(b"concept").to_hex()
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

    parsed = _parse_model_output(
        {
            "id": "resp_test",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "visible"}],
                },
                {
                    "type": "function_call",
                    "name": "mastery_update",
                    "arguments": (
                        '{"concept":"' + concept_hash + '","level":0.4}'
                    ),
                },
            ],
        }
    )
    assert parsed.visible_text == "visible"
    assert len(parsed.commands) == 1
    assert parsed.commands[0].source_response_id == "resp_test"
    assert parsed.commands[0].arguments["level"] == 0.4

    parsed_subcall = _parse_model_output(
        {
            "id": "resp_subcall",
            "output": [
                {
                    "type": "function_call",
                    "name": "subcall",
                    "arguments": '{"prompt":"check this","intent":"general"}',
                }
            ],
        }
    )
    assert len(parsed_subcall.commands) == 1
    assert parsed_subcall.commands[0].kind == "subcall"

    parsed_invalid = _parse_model_output(
        {
            "id": "resp_invalid",
            "output": [
                {
                    "type": "function_call",
                    "name": "mastery_update",
                    "arguments": '{"concept":"not-a-hash"}',
                }
            ],
        }
    )
    assert parsed_invalid.commands == []
    assert len(parsed_invalid.command_errors) == 1
    assert "numeric level" in parsed_invalid.command_errors[0].message

    print("  PASS: test_responses_text_extraction")


def test_command_validation_records_engine_notice():
    from rlm_ws import session as session_mod

    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")

        state = start_session(
            ws,
            SessionConfig(student_id="validation-test", api_key=""),
        )

        old_call_model = session_mod._call_model
        try:
            session_mod._call_model = lambda _state, _system: (
                "```json\n"
                "{\n"
                '  "visible_text": "I will continue without that command.",\n'
                '  "commands": [\n'
                "    {\n"
                '      "kind": "mastery_update",\n'
                '      "arguments": {"concept": "not-a-hash"}\n'
                "    }\n"
                "  ]\n"
                "}\n"
                "```"
            )
            response = run_turn(state, "Explain binary search")
        finally:
            session_mod._call_model = old_call_model

        assert response == "I will continue without that command."
        root_call = ws.get_event(ws.events_by_kind("ModelCall")[0])
        assert root_call is not None
        notice_refs = [
            ref for ref in root_call.outputs if ref.role == "engine_notice"
        ]
        assert len(notice_refs) == 1
        notice_event = ws.get_event(notice_refs[0].hash)
        assert notice_event is not None
        assert "command_validation_failed" in notice_event.tags
        notice_atom = ws.get_atom(notice_event.outputs[0].hash)
        assert "valid concept hash" in notice_atom.structured["message"]

        end_session(state)

        print("  PASS: test_command_validation_records_engine_notice")


def test_model_judged_mastery_update_records_judgment_call():
    from rlm_ws import session as session_mod

    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        course_hash = ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")
        binary_hash = next(
            concept_hash
            for concept_hash, atom in ws.collect_atoms(
                course_hash,
                "ConceptDefinition",
            )
            if "Binary search" in atom.text
        )

        state = start_session(
            ws,
            SessionConfig(student_id="judge-test", api_key="sk-test"),
        )

        calls = []
        old_call_model = session_mod._call_model

        def fake_call_model(fake_state, system):
            calls.append((fake_state.config.model, system, list(fake_state.messages)))
            if "Mastery Judgment Protocol" in system:
                payload = json.loads(fake_state.messages[0]["content"])
                assert payload["candidate_concepts"][0]["concept"] == (
                    binary_hash.to_hex()
                )
                return json.dumps(
                    {
                        "judgments": [
                            {
                                "concept": binary_hash.to_hex(),
                                "level": 0.9,
                                "confidence": 0.92,
                                "evidence": "student explained the halving invariant",
                                "reason": "student connected interval halving to search",
                            }
                        ]
                    }
                )
            return "Binary search halves the remaining interval."

        try:
            session_mod._call_model = fake_call_model
            response = run_turn(
                state,
                "I can explain why binary search halves the interval.",
            )
        finally:
            session_mod._call_model = old_call_model

        assert response == "Binary search halves the remaining interval."
        assert len(calls) == 2
        assert calls[1][0] == "gpt-5.4-nano"

        mastery = dict(ws.student_mastery_map(state.student_model))
        assert abs(mastery[binary_hash] - 0.08) < 1e-9

        judgment_calls = [
            (event_hash, ws.get_event(event_hash))
            for event_hash in ws.events_by_kind("ModelCall")
            if "mastery-judgment" in ws.get_event(event_hash).tags
        ]
        assert len(judgment_calls) == 1
        judgment_hash, judgment_call = judgment_calls[0]
        assert judgment_call.trace.model == "gpt-5.4-nano"
        assert any(ref.role == "turn_evidence" for ref in judgment_call.inputs)
        output_atom = ws.get_atom(judgment_call.outputs[0].hash)
        assert output_atom.structured["usable"] is True
        assert output_atom.structured["accepted_commands"][0]["arguments"][
            "source"
        ] == "model_judgment"

        update_event = ws.get_event(ws.events_by_kind("StudentModelUpdate")[0])
        assert update_event.parents == [judgment_hash]

        end_session(state)
        session_tip = ws.get_ref_hash("student/judge-test/session/session-1t")
        assert session_tip is not None
        rows = mastery_judgment_trace_rows(ws, session_tip)
        assert len(rows) == 1
        assert rows[0].event_hash == judgment_hash
        assert rows[0].concept_hash == binary_hash
        assert rows[0].status == "accepted"
        assert rows[0].fallback is False
        assert abs(rows[0].current_level - 0.0) < 1e-9
        assert abs(rows[0].judged_level - 0.9) < 1e-9
        assert abs(rows[0].bounded_level - 0.08) < 1e-9
        assert abs(rows[0].delta - 0.08) < 1e-9
        assert abs(rows[0].confidence - 0.92) < 1e-9
        assert "halving invariant" in rows[0].evidence

        print("  PASS: test_model_judged_mastery_update_records_judgment_call")


def test_invalid_model_judgment_falls_back_to_heuristic():
    from rlm_ws import session as session_mod

    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        (Path(d) / "course.md").write_text(SAMPLE_COURSE)
        course_hash = ingest_file(ws, Path(d) / "course.md", course_name="Algorithms")
        binary_hash = next(
            concept_hash
            for concept_hash, atom in ws.collect_atoms(
                course_hash,
                "ConceptDefinition",
            )
            if "Binary search" in atom.text
        )

        state = start_session(
            ws,
            SessionConfig(student_id="fallback-test", api_key="sk-test"),
        )

        old_call_model = session_mod._call_model

        def fake_call_model(_fake_state, system):
            if "Mastery Judgment Protocol" in system:
                return "not json"
            return "Good progress."

        try:
            session_mod._call_model = fake_call_model
            response = run_turn(state, "I understand binary search now.")
        finally:
            session_mod._call_model = old_call_model

        assert response == "Good progress."
        mastery = dict(ws.student_mastery_map(state.student_model))
        assert mastery[binary_hash] > 0.0

        judgment_call = next(
            ws.get_event(event_hash)
            for event_hash in ws.events_by_kind("ModelCall")
            if "mastery-judgment" in ws.get_event(event_hash).tags
        )
        output_atom = ws.get_atom(judgment_call.outputs[0].hash)
        assert output_atom.structured["usable"] is False
        assert output_atom.structured["fallback"] is True
        assert "strict JSON" in output_atom.structured["errors"][0]

        model = ws.get_frame(state.student_model)
        assert any(
            edge.label == "InteractionRecord"
            and edge.annotation
            and edge.annotation.get("source") == "turn_evidence"
            for edge in model.edges
        )

        end_session(state)
        session_tip = ws.get_ref_hash("student/fallback-test/session/session-1t")
        assert session_tip is not None
        rows = mastery_judgment_trace_rows(ws, session_tip)
        assert len(rows) == 1
        assert rows[0].fallback is True
        assert rows[0].status == "error -> fallback"
        assert "strict JSON" in rows[0].errors[0]

        print("  PASS: test_invalid_model_judgment_falls_back_to_heuristic")


def test_provider_adapters_shape_http_requests():
    import rlm_ws.providers as providers
    from rlm_ws.providers import ModelRequest, adapter_for

    posts = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, headers, json, timeout):
        posts.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        if url.endswith("/responses"):
            return FakeResponse({"output_text": "responses ok"})
        return FakeResponse({"choices": [{"message": {"content": "chat ok"}}]})

    old_post = providers.httpx.post
    providers.httpx.post = fake_post

    try:
        openai_request = ModelRequest(
            provider="openai",
            model="gpt-5.4-mini",
            api_base="https://api.openai.com/v1",
            api_key="sk-test",
            system="system prompt",
            messages=[{"role": "user", "content": "question"}],
        )
        openai_adapter = adapter_for("openai", openai_request.api_base, "sk-test")
        assert openai_adapter.api_mode == "responses"
        assert openai_adapter.call(openai_request) == {
            "output_text": "responses ok"
        }

        chat_request = ModelRequest(
            provider="openrouter",
            model="openai/gpt-5.4-mini",
            api_base="https://openrouter.ai/api/v1",
            api_key="sk-or-test",
            system="system prompt",
            messages=[{"role": "user", "content": "question"}],
        )
        chat_adapter = adapter_for("openrouter", chat_request.api_base, "sk-or-test")
        assert chat_adapter.api_mode == "chat_completions"
        assert chat_adapter.call(chat_request) == "chat ok"

        offline_adapter = adapter_for("openai", openai_request.api_base, "")
        assert offline_adapter.api_mode == "offline"
        assert "question" in offline_adapter.call(
            ModelRequest(
                provider="openai",
                model="gpt-5.4-mini",
                api_base=openai_request.api_base,
                api_key="",
                system="system prompt",
                messages=[{"role": "user", "content": "question"}],
            )
        )

        assert posts[0]["url"] == "https://api.openai.com/v1/responses"
        assert posts[0]["headers"]["Authorization"] == "Bearer sk-test"
        assert posts[0]["json"]["instructions"] == "system prompt"
        assert posts[0]["json"]["input"] == [
            {"role": "user", "content": "question"}
        ]
        assert posts[0]["json"]["max_output_tokens"] == 2048
        assert posts[0]["json"]["store"] is False

        assert (
            posts[1]["url"]
            == "https://openrouter.ai/api/v1/chat/completions"
        )
        assert posts[1]["headers"]["Authorization"] == "Bearer sk-or-test"
        assert posts[1]["json"]["messages"][0] == {
            "role": "system",
            "content": "system prompt",
        }
        assert posts[1]["json"]["max_tokens"] == 2048
    finally:
        providers.httpx.post = old_post

    print("  PASS: test_provider_adapters_shape_http_requests")


def test_session_model_command_helpers():
    from rlm_ws.session import (
        EngineCommand,
        SessionState,
        _provider_models,
        _resolve_mastery_judgment_mode,
        _resolve_model_selection,
        _set_mastery_judgment_mode,
        _set_session_model,
        _subcall_model,
    )

    with tempfile.TemporaryDirectory() as d:
        state = SessionState(
            ws=rlm_ws.Workspace.init(d),
            config=SessionConfig(
                provider="openrouter",
                model="openai/gpt-5.4-mini",
            ),
        )
        models = _provider_models("openrouter")

        assert _resolve_model_selection("2", models) == "openai/gpt-5.4-nano"
        assert _resolve_model_selection("99", models) is None
        assert (
            _resolve_model_selection("anthropic/claude-sonnet-4", models)
            == "anthropic/claude-sonnet-4"
        )
        assert (
            _subcall_model(state, EngineCommand("subcall", {}), 1)
            == "openai/gpt-5.4-nano"
        )

        _set_session_model(state, "anthropic/claude-sonnet-4")
        assert state.config.model == "anthropic/claude-sonnet-4"
        assert (
            _subcall_model(state, EngineCommand("subcall", {}), 1)
            == "anthropic/claude-sonnet-4"
        )

        assert _resolve_mastery_judgment_mode("model-judged") == "model"
        assert _resolve_mastery_judgment_mode("rules") == "heuristic"
        assert _resolve_mastery_judgment_mode("unknown") is None

        _set_mastery_judgment_mode(state, "heuristic")
        assert state.config.mastery_judgment == "heuristic"

    print("  PASS: test_session_model_command_helpers")


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
    test_session_mastery_update_command()
    test_session_subcall_command_records_child_call()
    test_session_subcall_budget_records_engine_notice()
    test_responses_text_extraction()
    test_command_validation_records_engine_notice()
    test_model_judged_mastery_update_records_judgment_call()
    test_invalid_model_judgment_falls_back_to_heuristic()
    test_provider_adapters_shape_http_requests()
    test_session_model_command_helpers()
    print("\nAll 20 tests passed!")
