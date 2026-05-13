"""End-to-end tests for the rlm_ws Python bindings."""

import tempfile
import rlm_ws


def test_hash():
    """Hash basics: compute, hex roundtrip, equality, hashing."""
    h1 = rlm_ws.Hash.compute(b"hello")
    h2 = rlm_ws.Hash.compute(b"hello")
    h3 = rlm_ws.Hash.compute(b"world")
    assert h1 == h2
    assert h1 != h3
    assert len(h1.to_hex()) == 64
    assert h1.short() == h1.to_hex()[:8]

    # Hex roundtrip
    h4 = rlm_ws.Hash.from_hex(h1.to_hex())
    assert h1 == h4

    # Usable as dict key
    d = {h1: "hello", h3: "world"}
    assert d[h1] == "hello"

    # str/repr
    assert str(h1) == h1.to_hex()
    assert "Hash(" in repr(h1)

    # Zero
    z = rlm_ws.Hash.zero()
    assert z.to_hex() == "0" * 64

    print("  PASS: test_hash")


def test_atom_lifecycle():
    """Create, store, read an atom."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        atom = rlm_ws.Atom(
            "ConceptDefinition",
            "Binary search is O(log n)",
            tags=["algorithms", "search"],
            structured={"difficulty": "intermediate"},
        )
        assert atom.kind == "ConceptDefinition"
        assert atom.text == "Binary search is O(log n)"
        assert atom.tags == ["algorithms", "search"]
        assert atom.structured == {"difficulty": "intermediate"}
        assert atom.binary is None

        h = ws.put_atom(atom)
        assert ws.exists(h)

        retrieved = ws.get_atom(h)
        assert retrieved is not None
        assert retrieved.text == "Binary search is O(log n)"
        assert retrieved.kind == "ConceptDefinition"
        assert retrieved.tags == ["algorithms", "search"]
        assert retrieved.structured == {"difficulty": "intermediate"}

        # Idempotent
        h2 = ws.put_atom(atom)
        assert h == h2

        print("  PASS: test_atom_lifecycle")


def test_frame_and_edges():
    """Build a frame with edges, verify graph traversal."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        c1 = ws.put_atom(rlm_ws.Atom("ConceptDefinition", "arrays"))
        c2 = ws.put_atom(rlm_ws.Atom("ConceptDefinition", "binary search"))
        p1 = ws.put_atom(rlm_ws.Atom("ProblemStatement", "find element"))

        e1 = rlm_ws.Edge("CoversConcept", c1)
        e2 = rlm_ws.Edge("CoversConcept", c2)
        e3 = rlm_ws.Edge("IncludesProblem", p1)

        frame = rlm_ws.Frame("Lesson", [e1, e2, e3], label="Searching")
        assert frame.kind == "Lesson"
        assert len(frame.edges) == 3
        assert frame.label == "Searching"

        fh = ws.put_frame(frame)

        # Collect all atoms
        atoms = ws.collect_atoms(fh)
        assert len(atoms) == 3

        # Filter by kind
        concepts = ws.collect_atoms(fh, "ConceptDefinition")
        assert len(concepts) == 2

        problems = ws.collect_atoms(fh, "ProblemStatement")
        assert len(problems) == 1

        # Edges from frame
        all_edges = ws.edges_from(fh)
        assert len(all_edges) == 3

        concept_edges = ws.edges_from(fh, "CoversConcept")
        assert len(concept_edges) == 2

        print("  PASS: test_frame_and_edges")


def test_refs():
    """Ref CRUD and CAS."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        h1 = ws.put_atom(rlm_ws.Atom("Blob", "v1"))
        h2 = ws.put_atom(rlm_ws.Atom("Blob", "v2"))

        # Write and read
        ws.set_ref("HEAD", h1)
        assert ws.get_ref_hash("HEAD") == h1

        # Nested refs
        ws.set_ref("student/alice/mastery", h1)
        ws.set_ref("student/bob/mastery", h2)
        refs = ws.list_refs("student")
        assert len(refs) == 2

        # CAS success
        ws.cas_ref("HEAD", h1, h2)
        assert ws.get_ref_hash("HEAD") == h2

        # CAS failure
        try:
            ws.cas_ref("HEAD", h1, h2)  # stale expected
            assert False, "Should have raised"
        except ValueError:
            pass

        # Delete
        assert ws.delete_ref("HEAD")
        assert ws.get_ref_hash("HEAD") is None

        print("  PASS: test_refs")


def test_events_and_session():
    """Event creation, session chain, index queries."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        # Session start
        start = ws.put_event(rlm_ws.Event("SessionStart", tags=["session"]))

        # Student input
        input_atom = ws.put_atom(rlm_ws.Atom("StudentResponse", "What is recursion?"))
        input_ref = rlm_ws.EventRef(input_atom, "student_message")
        input_ev = ws.put_event(
            rlm_ws.Event(
                "StudentInput",
                parents=[start],
                outputs=[input_ref],
            )
        )

        # Model call with trace
        output_atom = ws.put_atom(rlm_ws.Atom("ModelOutput", "Recursion is..."))
        trace = rlm_ws.CallTrace(
            call_depth=0,
            model="gpt-5.4-mini",
            input_tokens=1000,
            output_tokens=200,
            latency_ms=1500,
        )
        call_ev = ws.put_event(
            rlm_ws.Event(
                "ModelCall",
                parents=[input_ev],
                inputs=[input_ref],
                outputs=[rlm_ws.EventRef(output_atom, "model_output")],
                trace=trace,
            )
        )

        # Session end
        end = ws.put_event(
            rlm_ws.Event(
                "SessionEnd",
                parents=[call_ev],
                tags=["session"],
            )
        )

        # Walk session chain
        events = ws.session_events(end)
        assert len(events) >= 3
        kinds = [e.kind for _, e in events]
        assert kinds[0] == "SessionStart"
        assert kinds[-1] == "SessionEnd"

        # Index: by kind
        model_calls = ws.events_by_kind("ModelCall")
        assert len(model_calls) == 1

        # Index: by tag
        session_tagged = ws.by_tag("session")
        assert len(session_tagged) == 2

        # Index: recent
        recent = ws.recent_events(2)
        assert len(recent) == 2

        print("  PASS: test_events_and_session")


def test_mastery_and_commit_mutation():
    """Student model mastery tracking with three-step mutation."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        c1 = ws.put_atom(rlm_ws.Atom("ConceptDefinition", "recursion"))
        c2 = ws.put_atom(rlm_ws.Atom("ConceptDefinition", "loops"))

        # Initial model
        model_v1 = ws.put_frame(
            rlm_ws.Frame(
                "StudentModel",
                [
                    rlm_ws.Edge("MasteryEstimate", c1, weight=0.0),
                    rlm_ws.Edge("MasteryEstimate", c2, weight=0.0),
                ],
            )
        )
        ws.set_ref("student/alice/mastery", model_v1)

        mastery = ws.student_mastery_map(model_v1)
        assert len(mastery) == 2
        for h, level in mastery:
            assert level == 0.0

        # Update via commit_mutation
        model_v2 = ws.put_frame(
            rlm_ws.Frame(
                "StudentModel",
                [
                    rlm_ws.Edge(
                        "MasteryEstimate",
                        c1,
                        weight=0.7,
                        annotation={"reason": "quiz passed"},
                    ),
                    rlm_ws.Edge("MasteryEstimate", c2, weight=0.3),
                ],
            )
        )

        event = rlm_ws.Event(
            "StudentModelUpdate",
            inputs=[rlm_ws.EventRef(model_v1, "prior")],
            outputs=[rlm_ws.EventRef(model_v2, "updated")],
        )
        ws.commit_mutation(
            event,
            [
                ("student/alice/mastery", model_v1, model_v2),
            ],
        )

        assert ws.get_ref_hash("student/alice/mastery") == model_v2

        new_mastery = dict(ws.student_mastery_map(model_v2))
        assert abs(new_mastery[c1] - 0.7) < 1e-9
        assert abs(new_mastery[c2] - 0.3) < 1e-9

        # Old model still readable (immutable)
        old_mastery = dict(ws.student_mastery_map(model_v1))
        assert old_mastery[c1] == 0.0

        print("  PASS: test_mastery_and_commit_mutation")


def test_index_queries():
    """Index: reverse edges, kind queries, tags."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        c = ws.put_atom(rlm_ws.Atom("ConceptDefinition", "graphs", tags=["cs"]))
        p = ws.put_atom(
            rlm_ws.Atom("ProblemStatement", "BFS problem", tags=["practice"])
        )

        fh = ws.put_frame(
            rlm_ws.Frame(
                "Lesson",
                [
                    rlm_ws.Edge("CoversConcept", c),
                    rlm_ws.Edge("IncludesProblem", p),
                ],
            )
        )

        # Reverse edges
        rev = ws.reverse_edges(c)
        assert len(rev) == 1
        assert rev[0][0] == fh
        assert rev[0][1] == "CoversConcept"

        # Kind queries
        concepts = ws.atoms_by_kind("ConceptDefinition")
        assert len(concepts) == 1
        lessons = ws.frames_by_kind("Lesson")
        assert len(lessons) == 1

        # Tag queries
        cs = ws.by_tag("cs")
        assert len(cs) == 1
        assert cs[0] == c

        print("  PASS: test_index_queries")


def test_gc():
    """Garbage collection removes orphans."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        rooted = ws.put_atom(rlm_ws.Atom("Blob", "I'm rooted"))
        ws.set_ref("HEAD", rooted)

        orphan = ws.put_atom(rlm_ws.Atom("Blob", "I'm an orphan"))
        assert ws.exists(orphan)

        total, reachable, removed = ws.gc()
        assert removed == 1
        assert not ws.exists(orphan)
        assert ws.exists(rooted)

        print("  PASS: test_gc")


def test_export_json():
    """JSON export of a subgraph."""
    import json

    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        c = ws.put_atom(rlm_ws.Atom("ConceptDefinition", "test"))
        fh = ws.put_frame(
            rlm_ws.Frame(
                "Lesson",
                [
                    rlm_ws.Edge("CoversConcept", c),
                ],
            )
        )

        export_str = ws.export_json(fh)
        data = json.loads(export_str)
        assert "objects" in data
        assert len(data["objects"]) == 2  # frame + atom

        print("  PASS: test_export_json")


def test_persistence():
    """Workspace persists across open/close."""
    with tempfile.TemporaryDirectory() as d:
        # Create and write
        ws = rlm_ws.Workspace.init(d)
        h = ws.put_atom(rlm_ws.Atom("Blob", "persistent"))
        ws.set_ref("HEAD", h)
        del ws

        # Reopen and verify
        ws2 = rlm_ws.Workspace.open(d)
        assert ws2.get_ref_hash("HEAD") == h
        atom = ws2.get_atom(h)
        assert atom.text == "persistent"

        print("  PASS: test_persistence")


def test_shortest_path():
    """Shortest path through the graph."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)

        c = ws.put_atom(rlm_ws.Atom("ConceptDefinition", "target"))
        lesson = ws.put_frame(
            rlm_ws.Frame(
                "Lesson",
                [
                    rlm_ws.Edge("CoversConcept", c),
                ],
            )
        )
        course = ws.put_frame(
            rlm_ws.Frame(
                "Course",
                [
                    rlm_ws.Edge("Contains", lesson),
                ],
            )
        )

        path = ws.shortest_path(course, c, 10)
        assert path is not None
        assert path[0] == course
        assert path[-1] == c
        assert len(path) == 3

        # No path with depth 0
        assert ws.shortest_path(course, c, 1) is None

        print("  PASS: test_shortest_path")


def test_object_counts():
    """Object count diagnostics."""
    with tempfile.TemporaryDirectory() as d:
        ws = rlm_ws.Workspace.init(d)
        ws.put_atom(rlm_ws.Atom("Blob", "one"))
        ws.put_atom(rlm_ws.Atom("Blob", "two"))
        ws.put_frame(rlm_ws.Frame("Collection", []))
        ws.put_event(rlm_ws.Event("Admin"))

        atoms, frames, events = ws.object_counts()
        assert atoms == 2
        assert frames == 1
        assert events == 1

        print("  PASS: test_object_counts")


if __name__ == "__main__":
    print("Running Python bridge tests...")
    test_hash()
    test_atom_lifecycle()
    test_frame_and_edges()
    test_refs()
    test_events_and_session()
    test_mastery_and_commit_mutation()
    test_index_queries()
    test_gc()
    test_export_json()
    test_persistence()
    test_shortest_path()
    test_object_counts()
    print("\nAll 12 tests passed!")
