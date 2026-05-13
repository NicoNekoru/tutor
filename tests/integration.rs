/// Integration test: a complete tutoring session lifecycle.
///
/// This test simulates what the Python orchestration layer would do:
/// 1. Initialize a workspace and ingest a small course.
/// 2. Start a session.
/// 3. Simulate student interaction → model response → mastery update.
/// 4. End the session.
/// 5. Verify the entire graph, event chain, index, and GC behavior.
use rlm_ws::*;

use chrono::{DateTime, Utc};
use tempfile::TempDir;

fn ts(rfc: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(rfc)
        .unwrap()
        .with_timezone(&Utc)
}

/// Build a small course: "Intro to Algorithms"
///   Module: Searching
///     Lesson: Linear Search
///       CoversConcept → "linear search"
///       IncludesProblem → "find max element"
///     Lesson: Binary Search
///       CoversConcept → "binary search"
///       CoversConcept → "sorted arrays"
///       Prerequisite → Linear Search lesson
///       IncludesProblem → "find element in sorted array"
///       IncludesExample → "binary search step-by-step"
fn ingest_course(ws: &Workspace) -> (Hash, Vec<Hash>) {
    // Concept atoms
    let c_linear = ws
        .put(&Atom {
            kind: AtomKind::ConceptDefinition,
            content: AtomContent::text(
                "Linear search examines each element sequentially. Time complexity O(n).",
            ),
            metadata: AtomMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec!["algorithms".into(), "search".into()],
            },
        })
        .unwrap();

    let c_binary = ws
        .put(&Atom {
            kind: AtomKind::ConceptDefinition,
            content: AtomContent::text(
                "Binary search halves the search space each step. Requires sorted input. O(log n).",
            ),
            metadata: AtomMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec!["algorithms".into(), "search".into()],
            },
        })
        .unwrap();

    let c_sorted = ws
        .put(&Atom {
            kind: AtomKind::ConceptDefinition,
            content: AtomContent::text("A sorted array has elements in non-decreasing order."),
            metadata: AtomMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec!["data-structures".into()],
            },
        })
        .unwrap();

    // Problems
    let p_max = ws
        .put(&Atom {
            kind: AtomKind::ProblemStatement,
            content: AtomContent::text("Given an unsorted array, find the maximum element."),
            metadata: AtomMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec!["practice".into()],
            },
        })
        .unwrap();

    let p_find = ws
        .put(&Atom {
            kind: AtomKind::ProblemStatement,
            content: AtomContent::text(
                "Given a sorted array and target value, return the index of the target.",
            ),
            metadata: AtomMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec!["practice".into()],
            },
        })
        .unwrap();

    // Worked example
    let ex_bs = ws
        .put(&Atom {
            kind: AtomKind::WorkedExample,
            content: AtomContent::text(
                "Array: [2, 5, 8, 12, 16, 23]. Target: 12.\n\
                Step 1: mid=8, 12>8, search right half.\n\
                Step 2: mid=16, 12<16, search left half.\n\
                Step 3: mid=12, found at index 3.",
            ),
            metadata: AtomMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec!["example".into()],
            },
        })
        .unwrap();

    // Lessons
    let lesson_linear = ws
        .put(&Frame {
            kind: FrameKind::Lesson,
            edges: vec![
                Edge {
                    label: EdgeLabel::CoversConcept,
                    target: c_linear,
                    weight: None,
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::IncludesProblem,
                    target: p_max,
                    weight: None,
                    annotation: None,
                },
            ],
            metadata: FrameMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec![],
                label: Some("Linear Search".into()),
                label_in_hash: true,
            },
        })
        .unwrap();

    let lesson_binary = ws
        .put(&Frame {
            kind: FrameKind::Lesson,
            edges: vec![
                Edge {
                    label: EdgeLabel::CoversConcept,
                    target: c_binary,
                    weight: None,
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::CoversConcept,
                    target: c_sorted,
                    weight: None,
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::Prerequisite,
                    target: lesson_linear,
                    weight: None,
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::IncludesProblem,
                    target: p_find,
                    weight: None,
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::IncludesExample,
                    target: ex_bs,
                    weight: None,
                    annotation: None,
                },
            ],
            metadata: FrameMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec![],
                label: Some("Binary Search".into()),
                label_in_hash: true,
            },
        })
        .unwrap();

    // Module
    let module_search = ws
        .put(&Frame {
            kind: FrameKind::Module,
            edges: vec![
                Edge {
                    label: EdgeLabel::Contains,
                    target: lesson_linear,
                    weight: None,
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::Contains,
                    target: lesson_binary,
                    weight: None,
                    annotation: None,
                },
            ],
            metadata: FrameMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec![],
                label: Some("Searching".into()),
                label_in_hash: true,
            },
        })
        .unwrap();

    // Course
    let course = ws
        .put(&Frame {
            kind: FrameKind::Course,
            edges: vec![Edge {
                label: EdgeLabel::Contains,
                target: module_search,
                weight: None,
                annotation: None,
            }],
            metadata: FrameMetadata {
                created_at: ts("2026-01-01T00:00:00Z"),
                tags: vec![],
                label: Some("Intro to Algorithms".into()),
                label_in_hash: true,
            },
        })
        .unwrap();

    // Set course ref.
    ws.set_ref("course/structure", &course).unwrap();

    let concepts = vec![c_linear, c_binary, c_sorted];
    (course, concepts)
}

/// Create initial student model (all mastery at 0.0).
fn init_student_model(ws: &Workspace, student_id: &str, concepts: &[Hash]) -> Hash {
    let model = Frame {
        kind: FrameKind::StudentModel,
        edges: concepts
            .iter()
            .map(|c| Edge {
                label: EdgeLabel::MasteryEstimate,
                target: *c,
                weight: Some(0.0),
                annotation: None,
            })
            .collect(),
        metadata: FrameMetadata {
            created_at: ts("2026-03-20T09:00:00Z"),
            tags: vec![],
            label: Some(format!("{}-model", student_id)),
            label_in_hash: false,
        },
    };
    let hash = ws.put(&model).unwrap();
    ws.set_ref(&format!("student/{}/mastery", student_id), &hash)
        .unwrap();
    hash
}

#[test]
fn test_full_tutoring_session() {
    let dir = TempDir::new().unwrap();
    let ws = Workspace::init(dir.path()).unwrap();

    // =========================================================
    // Phase 1: Course ingestion
    // =========================================================
    let (course_hash, concepts) = ingest_course(&ws);
    let c_linear = concepts[0];
    let c_binary = concepts[1];
    let c_sorted = concepts[2];

    // Verify graph traversal from course root.
    let graph = ws.graph();
    let all_atoms = graph.collect_atoms(&course_hash, None).unwrap();
    assert_eq!(all_atoms.len(), 6, "3 concepts + 2 problems + 1 example");

    let concept_atoms = graph
        .collect_atoms(&course_hash, Some(&[AtomKind::ConceptDefinition]))
        .unwrap();
    assert_eq!(concept_atoms.len(), 3);

    let all_frames = graph.collect_frames(&course_hash, None).unwrap();
    assert_eq!(all_frames.len(), 4, "course + module + 2 lessons");

    // Verify index was populated during put().
    let indexed_concepts = ws.index.atoms_by_kind(AtomKind::ConceptDefinition).unwrap();
    assert_eq!(indexed_concepts.len(), 3);

    let algo_tagged = ws.index.by_tag("algorithms").unwrap();
    assert_eq!(
        algo_tagged.len(),
        2,
        "linear search + binary search concepts"
    );

    // Verify reverse edge index.
    let who_covers_binary = ws.index.reverse_edges(&c_binary).unwrap();
    assert!(!who_covers_binary.is_empty());
    assert!(who_covers_binary
        .iter()
        .any(|(_, label)| label == "CoversConcept"));

    // =========================================================
    // Phase 2: Student model initialization
    // =========================================================
    let student_id = "alice";
    let model_v1 = init_student_model(&ws, student_id, &concepts);

    let mastery = graph.student_mastery_map(&model_v1).unwrap();
    assert_eq!(mastery.len(), 3);
    for (_concept, level) in &mastery {
        assert!(
            (*level - 0.0).abs() < f64::EPSILON,
            "All mastery should start at 0.0"
        );
    }

    // =========================================================
    // Phase 3: Session start
    // =========================================================
    let session_start = ws
        .put(&Event {
            kind: EventKind::SessionStart,
            parents: vec![],
            inputs: vec![
                EventRef {
                    hash: model_v1,
                    role: "student_model".into(),
                },
                EventRef {
                    hash: course_hash,
                    role: "course".into(),
                },
            ],
            outputs: vec![],
            trace: CallTrace::empty(),
            metadata: EventMetadata {
                timestamp: ts("2026-03-20T10:00:00Z"),
                tags: vec!["session".into()],
            },
        })
        .unwrap();
    ws.set_ref(
        &format!("student/{}/session/current", student_id),
        &session_start,
    )
    .unwrap();

    // =========================================================
    // Phase 4: Student asks about binary search
    // =========================================================
    let student_input_atom = ws
        .put(&Atom {
            kind: AtomKind::StudentResponse,
            content: AtomContent::text("Can you explain how binary search works?"),
            metadata: AtomMetadata {
                created_at: ts("2026-03-20T10:01:00Z"),
                tags: vec![],
            },
        })
        .unwrap();

    let student_input_event = ws
        .put(&Event {
            kind: EventKind::StudentInput,
            parents: vec![session_start],
            inputs: vec![],
            outputs: vec![EventRef {
                hash: student_input_atom,
                role: "student_message".into(),
            }],
            trace: CallTrace::empty(),
            metadata: EventMetadata {
                timestamp: ts("2026-03-20T10:01:00Z"),
                tags: vec![],
            },
        })
        .unwrap();

    // =========================================================
    // Phase 5: Model generates explanation (simulated)
    // =========================================================
    let model_output_atom = ws
        .put(&Atom {
            kind: AtomKind::ModelOutput,
            content: AtomContent::text(
                "Binary search works by repeatedly dividing the search interval in half. \
                You start with the middle element. If it matches, you're done. \
                If the target is less, search the left half. If greater, search the right half.",
            ),
            metadata: AtomMetadata {
                created_at: ts("2026-03-20T10:01:05Z"),
                tags: vec![],
            },
        })
        .unwrap();

    // The model call also spawned a child call for retrieval.
    let retrieval_scope = ws
        .put(&Frame {
            kind: FrameKind::RetrievalScope,
            edges: vec![
                Edge {
                    label: EdgeLabel::InScope,
                    target: c_binary,
                    weight: None,
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::InScope,
                    target: c_sorted,
                    weight: None,
                    annotation: None,
                },
            ],
            metadata: FrameMetadata {
                created_at: ts("2026-03-20T10:01:02Z"),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        })
        .unwrap();

    let child_call_event = ws
        .put(&Event {
            kind: EventKind::ModelCall,
            parents: vec![],
            inputs: vec![EventRef {
                hash: retrieval_scope,
                role: "scope".into(),
            }],
            outputs: vec![],
            trace: CallTrace {
                model: Some("gpt-5.4-nano".into()),
                call_depth: 1,
                input_tokens: Some(500),
                output_tokens: Some(100),
                latency_ms: Some(300),
                retrieval_scope: Some(retrieval_scope),
                ..CallTrace::empty()
            },
            metadata: EventMetadata {
                timestamp: ts("2026-03-20T10:01:03Z"),
                tags: vec![],
            },
        })
        .unwrap();

    let root_call_event = ws
        .put(&Event {
            kind: EventKind::ModelCall,
            parents: vec![student_input_event],
            inputs: vec![
                EventRef {
                    hash: student_input_atom,
                    role: "student_message".into(),
                },
                EventRef {
                    hash: model_v1,
                    role: "student_model".into(),
                },
            ],
            outputs: vec![
                EventRef {
                    hash: model_output_atom,
                    role: "model_output".into(),
                },
                EventRef {
                    hash: child_call_event,
                    role: "child_call".into(),
                },
            ],
            trace: CallTrace {
                model: Some("gpt-5.4-mini".into()),
                call_depth: 0,
                input_tokens: Some(2000),
                output_tokens: Some(500),
                latency_ms: Some(1500),
                ..CallTrace::empty()
            },
            metadata: EventMetadata {
                timestamp: ts("2026-03-20T10:01:05Z"),
                tags: vec![],
            },
        })
        .unwrap();

    // =========================================================
    // Phase 6: Mastery update via commit_mutation
    // =========================================================
    // The model assessed that the student now understands binary search at 0.4
    // and sorted arrays at 0.3.
    let model_v2 = ws
        .put(&Frame {
            kind: FrameKind::StudentModel,
            edges: vec![
                Edge {
                    label: EdgeLabel::MasteryEstimate,
                    target: c_linear,
                    weight: Some(0.0),
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::MasteryEstimate,
                    target: c_binary,
                    weight: Some(0.4),
                    annotation: Some(
                        serde_json::json!({"reason": "explained concept, student engaged"}),
                    ),
                },
                Edge {
                    label: EdgeLabel::MasteryEstimate,
                    target: c_sorted,
                    weight: Some(0.3),
                    annotation: Some(
                        serde_json::json!({"reason": "prerequisite mentioned in explanation"}),
                    ),
                },
                Edge {
                    label: EdgeLabel::InteractionRecord,
                    target: root_call_event,
                    weight: None,
                    annotation: None,
                },
            ],
            metadata: FrameMetadata {
                created_at: ts("2026-03-20T10:01:06Z"),
                tags: vec![],
                label: Some("alice-model".into()),
                label_in_hash: false,
            },
        })
        .unwrap();

    let mastery_event = Event {
        kind: EventKind::StudentModelUpdate,
        parents: vec![root_call_event],
        inputs: vec![EventRef {
            hash: model_v1,
            role: "prior_model".into(),
        }],
        outputs: vec![EventRef {
            hash: model_v2,
            role: "updated_model".into(),
        }],
        trace: CallTrace::empty(),
        metadata: EventMetadata {
            timestamp: ts("2026-03-20T10:01:06Z"),
            tags: vec![],
        },
    };

    let mastery_ref = format!("student/{}/mastery", student_id);
    let mastery_event_hash = ws
        .commit_mutation(&mastery_event, &[(&mastery_ref, model_v1, model_v2)])
        .unwrap();

    // Verify mastery was updated.
    let current_model_hash = ws.get_ref_hash(&mastery_ref).unwrap().unwrap();
    assert_eq!(current_model_hash, model_v2);

    let new_mastery = graph.student_mastery_map(&model_v2).unwrap();
    let binary_mastery = new_mastery.iter().find(|(h, _)| *h == c_binary).unwrap().1;
    assert!((binary_mastery - 0.4).abs() < f64::EPSILON);

    // =========================================================
    // Phase 7: Session end
    // =========================================================
    let session_end = ws
        .put(&Event {
            kind: EventKind::SessionEnd,
            parents: vec![mastery_event_hash],
            inputs: vec![],
            outputs: vec![],
            trace: CallTrace::empty(),
            metadata: EventMetadata {
                timestamp: ts("2026-03-20T10:15:00Z"),
                tags: vec!["session".into()],
            },
        })
        .unwrap();

    let session_ref = format!("student/{}/session/2026-03-20-001", student_id);
    ws.set_ref(&session_ref, &session_end).unwrap();
    ws.refs
        .delete(&format!("student/{}/session/current", student_id))
        .unwrap();

    // =========================================================
    // Phase 8: Verify session event chain
    // =========================================================
    let session_events = graph.session_events(&session_end).unwrap();
    assert!(
        session_events.len() >= 4,
        "At least: start, input, call, mastery_update, end"
    );

    let kinds: Vec<EventKind> = session_events.iter().map(|(_, e)| e.kind).collect();
    assert_eq!(kinds[0], EventKind::SessionStart);
    assert_eq!(*kinds.last().unwrap(), EventKind::SessionEnd);

    // =========================================================
    // Phase 9: Verify call tree
    // =========================================================
    let tree = graph.call_tree(&root_call_event).unwrap().unwrap();
    assert_eq!(tree.event.trace.call_depth, 0);
    assert_eq!(tree.children.len(), 1, "One child call");
    assert_eq!(tree.children[0].event.trace.call_depth, 1);
    assert_eq!(
        tree.children[0].event.trace.model.as_deref(),
        Some("gpt-5.4-nano")
    );

    // =========================================================
    // Phase 10: Verify index queries
    // =========================================================
    let model_calls = ws.index.events_by_kind(EventKind::ModelCall).unwrap();
    assert_eq!(model_calls.len(), 2, "root call + child call");

    let recent = ws.index.recent_events(3, None).unwrap();
    assert_eq!(recent.len(), 3);

    let session_events_idx = ws.index.events_by_kind(EventKind::SessionStart).unwrap();
    assert_eq!(session_events_idx.len(), 1);

    let session_tagged = ws.index.by_tag("session").unwrap();
    assert_eq!(session_tagged.len(), 2, "SessionStart + SessionEnd");

    // =========================================================
    // Phase 11: Verify shortest path
    // =========================================================
    let path = graph
        .shortest_path(&course_hash, &c_binary, 10)
        .unwrap()
        .unwrap();
    assert!(path.len() >= 3, "course → module → lesson → concept");
    assert_eq!(path[0], course_hash);
    assert_eq!(*path.last().unwrap(), c_binary);

    // =========================================================
    // Phase 12: Export and inspect
    // =========================================================
    let mut export_buf = Vec::new();
    ws.export_json(&course_hash, &mut export_buf).unwrap();
    let export: serde_json::Value = serde_json::from_slice(&export_buf).unwrap();
    let objects = export["objects"].as_array().unwrap();
    // Course subgraph: 4 frames + 6 atoms = 10
    assert_eq!(objects.len(), 10);

    // Verify types in export.
    let atom_count = objects.iter().filter(|o| o["type"] == "Atom").count();
    let frame_count = objects.iter().filter(|o| o["type"] == "Frame").count();
    assert_eq!(atom_count, 6);
    assert_eq!(frame_count, 4);

    // =========================================================
    // Phase 13: GC (nothing should be collected — everything is reachable)
    // =========================================================
    let gc_report = ws.gc().unwrap();
    assert_eq!(
        gc_report.removed_objects, 0,
        "No orphans — everything is reachable from refs"
    );

    // Now create an orphan and verify GC removes it.
    let orphan = ws
        .put(&Atom {
            kind: AtomKind::Blob,
            content: AtomContent::text("I am unreachable"),
            metadata: AtomMetadata {
                created_at: ts("2026-03-20T12:00:00Z"),
                tags: vec![],
            },
        })
        .unwrap();
    assert!(ws.store.exists(&orphan));
    let gc_report = ws.gc().unwrap();
    assert_eq!(gc_report.removed_objects, 1);
    assert!(!ws.store.exists(&orphan));

    // =========================================================
    // Phase 14: Persistence — close and reopen
    // =========================================================
    drop(ws);
    let ws2 = Workspace::open(dir.path()).unwrap();

    // Course ref still works.
    let course_ref = ws2.get_ref_hash("course/structure").unwrap().unwrap();
    assert_eq!(course_ref, course_hash);

    // Student mastery still correct.
    let mastery_hash = ws2.get_ref_hash(&mastery_ref).unwrap().unwrap();
    assert_eq!(mastery_hash, model_v2);

    // Graph traversal still works after reopen.
    let graph2 = ws2.graph();
    let atoms2 = graph2.collect_atoms(&course_hash, None).unwrap();
    assert_eq!(atoms2.len(), 6);

    // Index persisted and queries still work.
    let concepts_after = ws2
        .index
        .atoms_by_kind(AtomKind::ConceptDefinition)
        .unwrap();
    assert_eq!(concepts_after.len(), 3);

    // Rebuild index from scratch and verify consistency.
    let rebuild_count = ws2.rebuild_index().unwrap();
    let (atoms_count, frames_count, events_count) = ws2.index.object_counts().unwrap();
    assert!(atoms_count >= 6);
    assert!(frames_count >= 4);
    assert!(events_count >= 5);
    assert_eq!(rebuild_count, atoms_count + frames_count + events_count);
}

#[test]
fn test_concurrent_student_namespaces() {
    let dir = TempDir::new().unwrap();
    let ws = Workspace::init(dir.path()).unwrap();
    let (_, concepts) = ingest_course(&ws);

    // Two students, independent mastery tracking.
    let alice_v1 = init_student_model(&ws, "alice", &concepts);
    let bob_v1 = init_student_model(&ws, "bob", &concepts);

    // Update Alice's mastery.
    let alice_v2 = ws
        .put(&Frame {
            kind: FrameKind::StudentModel,
            edges: vec![
                Edge {
                    label: EdgeLabel::MasteryEstimate,
                    target: concepts[0],
                    weight: Some(0.8),
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::MasteryEstimate,
                    target: concepts[1],
                    weight: Some(0.5),
                    annotation: None,
                },
                Edge {
                    label: EdgeLabel::MasteryEstimate,
                    target: concepts[2],
                    weight: Some(0.6),
                    annotation: None,
                },
            ],
            metadata: FrameMetadata {
                created_at: ts("2026-03-20T11:00:00Z"),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        })
        .unwrap();

    ws.refs
        .cas("student/alice/mastery", &alice_v1, &alice_v2)
        .unwrap();

    // Bob's mastery should be unaffected.
    let bob_current = ws.get_ref_hash("student/bob/mastery").unwrap().unwrap();
    assert_eq!(bob_current, bob_v1);

    let alice_current = ws.get_ref_hash("student/alice/mastery").unwrap().unwrap();
    assert_eq!(alice_current, alice_v2);

    // CAS conflict: try to update alice from v1 (stale) → should fail.
    let alice_v3 = ws
        .put(&Frame {
            kind: FrameKind::StudentModel,
            edges: vec![],
            metadata: FrameMetadata {
                created_at: ts("2026-03-20T12:00:00Z"),
                tags: vec![],
                label: None,
                label_in_hash: false,
            },
        })
        .unwrap();

    let result = ws.refs.cas("student/alice/mastery", &alice_v1, &alice_v3);
    assert!(result.is_err(), "CAS from stale ref should fail");

    // Alice's mastery should still be v2.
    assert_eq!(
        ws.get_ref_hash("student/alice/mastery").unwrap().unwrap(),
        alice_v2
    );

    // Enumerate all student refs.
    let student_refs = ws.refs.list("student").unwrap();
    assert_eq!(student_refs.len(), 2);
}

#[test]
fn test_old_student_models_preserved() {
    let dir = TempDir::new().unwrap();
    let ws = Workspace::init(dir.path()).unwrap();
    let (_, concepts) = ingest_course(&ws);

    let v1 = init_student_model(&ws, "alice", &concepts);

    // Update mastery 3 times.
    let mut current = v1;
    let mut versions = vec![v1];
    for i in 1..=3 {
        let new = ws
            .put(&Frame {
                kind: FrameKind::StudentModel,
                edges: concepts
                    .iter()
                    .map(|c| Edge {
                        label: EdgeLabel::MasteryEstimate,
                        target: *c,
                        weight: Some(i as f64 * 0.2),
                        annotation: None,
                    })
                    .collect(),
                metadata: FrameMetadata {
                    created_at: ts(&format!("2026-03-20T1{}:00:00Z", i)),
                    tags: vec![],
                    label: None,
                    label_in_hash: false,
                },
            })
            .unwrap();
        ws.refs
            .cas("student/alice/mastery", &current, &new)
            .unwrap();
        current = new;
        versions.push(new);
    }

    // Current ref points to v4.
    assert_eq!(
        ws.get_ref_hash("student/alice/mastery").unwrap().unwrap(),
        versions[3]
    );

    // All old versions still exist in the store (immutable objects).
    for v in &versions {
        assert!(ws.store.exists(v), "Old model version should still exist");
        let frame: Frame = ws.get(v).unwrap().unwrap();
        assert_eq!(frame.kind, FrameKind::StudentModel);
    }

    // Mastery trajectory: read each version's mastery for concepts[0].
    let graph = ws.graph();
    for (i, v) in versions.iter().enumerate() {
        let mastery = graph.student_mastery_map(v).unwrap();
        let level = mastery.iter().find(|(h, _)| *h == concepts[0]).unwrap().1;
        let expected = i as f64 * 0.2;
        assert!(
            (level - expected).abs() < f64::EPSILON,
            "Version {} mastery should be {}, got {}",
            i,
            expected,
            level
        );
    }
}
