use std::collections::{HashSet, VecDeque};

use crate::envelope::Storable;
use crate::error::Result;
use crate::hash::Hash;
use crate::store::ObjectStore;
use crate::types::{Atom, AtomKind, Edge, EdgeLabel, Event, Frame, FrameKind, ObjectType};

/// Traversal direction for graph walks.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    /// Follow edges/links from parent to child.
    Forward,
    /// Follow reverse edges (requires the index). Not available here —
    /// use `Index::reverse_edges` for reverse lookups.
    Reverse,
}

/// A node in a reconstructed call tree.
#[derive(Debug)]
pub struct CallTreeNode {
    pub event_hash: Hash,
    pub event: Event,
    pub children: Vec<CallTreeNode>,
}

/// Graph traversal operations over the object store.
///
/// These are pure read-only traversals. They don't require the index —
/// they walk objects directly. For reverse lookups (find all frames
/// pointing to X), use the Index.
pub struct Graph<'a> {
    store: &'a ObjectStore,
}

impl<'a> Graph<'a> {
    pub fn new(store: &'a ObjectStore) -> Self {
        Graph { store }
    }

    /// Collect all Atoms reachable from a Frame (or any starting hash),
    /// optionally filtered by `AtomKind`. BFS through Frames, collecting Atoms.
    pub fn collect_atoms(
        &self,
        root: &Hash,
        kind_filter: Option<&[AtomKind]>,
    ) -> Result<Vec<(Hash, Atom)>> {
        let mut results = Vec::new();
        let mut visited = HashSet::new();
        let mut queue = VecDeque::new();
        queue.push_back(*root);

        while let Some(hash) = queue.pop_front() {
            if !visited.insert(hash) {
                continue;
            }

            if let Some(env) = self.store.read_raw(&hash)? {
                match env.object_type {
                    ObjectType::Atom => {
                        let atom = Atom::from_hashable_bytes(&env.content)?;
                        let include = match kind_filter {
                            Some(kinds) => kinds.contains(&atom.kind),
                            None => true,
                        };
                        if include {
                            results.push((hash, atom));
                        }
                    }
                    ObjectType::Frame => {
                        let frame = Frame::from_hashable_bytes(&env.content)?;
                        for edge in &frame.edges {
                            queue.push_back(edge.target);
                        }
                    }
                    ObjectType::Event => {
                        // Events encountered during atom collection — skip but
                        // follow their output references (they may point to atoms).
                        let event = Event::from_hashable_bytes(&env.content)?;
                        for output in &event.outputs {
                            queue.push_back(output.hash);
                        }
                    }
                }
            }
        }

        Ok(results)
    }

    /// Collect all Frames reachable from a root, optionally filtered by kind.
    pub fn collect_frames(
        &self,
        root: &Hash,
        kind_filter: Option<&[FrameKind]>,
    ) -> Result<Vec<(Hash, Frame)>> {
        let mut results = Vec::new();
        let mut visited = HashSet::new();
        let mut queue = VecDeque::new();
        queue.push_back(*root);

        while let Some(hash) = queue.pop_front() {
            if !visited.insert(hash) {
                continue;
            }
            if let Some(env) = self.store.read_raw(&hash)? {
                if env.object_type == ObjectType::Frame {
                    let frame = Frame::from_hashable_bytes(&env.content)?;
                    for edge in &frame.edges {
                        queue.push_back(edge.target);
                    }
                    let include = match kind_filter {
                        Some(kinds) => kinds.contains(&frame.kind),
                        None => true,
                    };
                    if include {
                        results.push((hash, frame));
                    }
                }
            }
        }

        Ok(results)
    }

    /// Walk all hashes reachable from a start hash (BFS, forward direction).
    /// Returns every visited hash with its object type.
    pub fn walk_all(&self, start: &Hash) -> Result<Vec<(Hash, ObjectType)>> {
        let mut results = Vec::new();
        let mut visited = HashSet::new();
        let mut queue = VecDeque::new();
        queue.push_back(*start);

        while let Some(hash) = queue.pop_front() {
            if !visited.insert(hash) {
                continue;
            }
            if let Some(env) = self.store.read_raw(&hash)? {
                results.push((hash, env.object_type));
                match env.object_type {
                    ObjectType::Atom => {}
                    ObjectType::Frame => {
                        let frame = Frame::from_hashable_bytes(&env.content)?;
                        for edge in &frame.edges {
                            queue.push_back(edge.target);
                        }
                    }
                    ObjectType::Event => {
                        let event = Event::from_hashable_bytes(&env.content)?;
                        for p in &event.parents {
                            queue.push_back(*p);
                        }
                        for i in &event.inputs {
                            queue.push_back(i.hash);
                        }
                        for o in &event.outputs {
                            queue.push_back(o.hash);
                        }
                        if let Some(s) = &event.trace.retrieval_scope {
                            queue.push_back(*s);
                        }
                        if let Some(pc) = &event.trace.parent_call {
                            queue.push_back(*pc);
                        }
                    }
                }
            }
        }

        Ok(results)
    }

    /// Collect all Events in a session by walking parent links backwards
    /// from the given event to the `SessionStart`. Returns events in
    /// chronological order (`SessionStart` first).
    pub fn session_events(&self, session_tip: &Hash) -> Result<Vec<(Hash, Event)>> {
        let mut events = Vec::new();
        let mut visited = HashSet::new();
        let mut queue = VecDeque::new();
        queue.push_back(*session_tip);

        while let Some(hash) = queue.pop_front() {
            if !visited.insert(hash) {
                continue;
            }
            if let Some(event) = self.store.read::<Event>(&hash)? {
                for parent in &event.parents {
                    queue.push_back(*parent);
                }
                events.push((hash, event));
            }
        }

        // Reverse to get chronological order (parents before children).
        events.reverse();
        Ok(events)
    }

    /// Build the recursive call tree from a root `ModelCall` event.
    /// Follows `SpawnedChild` edges and `parent_call` links in traces.
    pub fn call_tree(&self, root_event: &Hash) -> Result<Option<CallTreeNode>> {
        let Some(event) = self.store.read::<Event>(root_event)? else {
            return Ok(None);
        };

        // Find child events: look at outputs with role containing "child_call",
        // or trace.parent_call matching this event in descendant events.
        let mut children = Vec::new();
        for output in &event.outputs {
            if output.role == "child_call" {
                if let Some(child_node) = self.call_tree(&output.hash)? {
                    children.push(child_node);
                }
            }
        }

        Ok(Some(CallTreeNode {
            event_hash: *root_event,
            event,
            children,
        }))
    }

    /// Find all edges from a specific frame that match a label filter.
    pub fn edges_from(
        &self,
        frame_hash: &Hash,
        label_filter: Option<&[EdgeLabel]>,
    ) -> Result<Vec<Edge>> {
        let Some(frame) = self.store.read::<Frame>(frame_hash)? else {
            return Ok(Vec::new());
        };

        match label_filter {
            Some(labels) => Ok(frame
                .edges
                .into_iter()
                .filter(|e| labels.contains(&e.label))
                .collect()),
            None => Ok(frame.edges),
        }
    }

    /// Find all concept atoms that a `StudentModel` frame tracks mastery for.
    /// Returns (`concept_hash`, `mastery_level`) pairs.
    pub fn student_mastery_map(&self, student_model_hash: &Hash) -> Result<Vec<(Hash, f64)>> {
        let Some(frame) = self.store.read::<Frame>(student_model_hash)? else {
            return Ok(Vec::new());
        };

        Ok(frame
            .edges
            .iter()
            .filter(|e| e.label == EdgeLabel::MasteryEstimate)
            .filter_map(|e| e.weight.map(|w| (e.target, w)))
            .collect())
    }

    /// Find the shortest path between two hashes (BFS, forward only).
    /// Returns None if no path exists within `max_depth`.
    pub fn shortest_path(
        &self,
        from: &Hash,
        to: &Hash,
        max_depth: usize,
    ) -> Result<Option<Vec<Hash>>> {
        if from == to {
            return Ok(Some(vec![*from]));
        }

        let mut visited = HashSet::new();
        // BFS with parent tracking.
        let mut queue: VecDeque<(Hash, usize)> = VecDeque::new();
        let mut parent_map: std::collections::HashMap<Hash, Hash> =
            std::collections::HashMap::new();

        queue.push_back((*from, 0));
        visited.insert(*from);

        while let Some((hash, depth)) = queue.pop_front() {
            if depth >= max_depth {
                continue;
            }

            let neighbors = self.forward_neighbors(&hash)?;
            for neighbor in neighbors {
                if !visited.insert(neighbor) {
                    continue;
                }
                parent_map.insert(neighbor, hash);
                if neighbor == *to {
                    // Reconstruct path.
                    let mut path = vec![neighbor];
                    let mut current = neighbor;
                    while let Some(&parent) = parent_map.get(&current) {
                        path.push(parent);
                        current = parent;
                    }
                    path.reverse();
                    return Ok(Some(path));
                }
                queue.push_back((neighbor, depth + 1));
            }
        }

        Ok(None)
    }

    /// Get all direct forward neighbors of a hash (edge targets for Frames,
    /// parent/input/output refs for Events, nothing for Atoms).
    fn forward_neighbors(&self, hash: &Hash) -> Result<Vec<Hash>> {
        let Some(env) = self.store.read_raw(hash)? else {
            return Ok(Vec::new());
        };

        match env.object_type {
            ObjectType::Atom => Ok(Vec::new()),
            ObjectType::Frame => {
                let frame = Frame::from_hashable_bytes(&env.content)?;
                Ok(frame.edges.iter().map(|e| e.target).collect())
            }
            ObjectType::Event => {
                let event = Event::from_hashable_bytes(&env.content)?;
                let mut neighbors = Vec::new();
                for p in &event.parents {
                    neighbors.push(*p);
                }
                for i in &event.inputs {
                    neighbors.push(i.hash);
                }
                for o in &event.outputs {
                    neighbors.push(o.hash);
                }
                if let Some(s) = &event.trace.retrieval_scope {
                    neighbors.push(*s);
                }
                if let Some(pc) = &event.trace.parent_call {
                    neighbors.push(*pc);
                }
                Ok(neighbors)
            }
        }
    }
}

#[cfg(test)]
#[allow(clippy::doc_markdown)]
mod tests {
    use super::*;
    use crate::types::{
        AtomContent, AtomMetadata, CallTrace, EventKind, EventMetadata, EventRef, FrameMetadata,
    };
    use chrono::{DateTime, Utc};
    use std::fs;
    use tempfile::TempDir;

    fn fixed_ts() -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
    }

    fn make_concept(text: &str) -> Atom {
        Atom {
            kind: AtomKind::ConceptDefinition,
            content: AtomContent::text(text),
            metadata: AtomMetadata {
                created_at: fixed_ts(),
                tags: vec![],
            },
        }
    }

    fn make_problem(text: &str) -> Atom {
        Atom {
            kind: AtomKind::ProblemStatement,
            content: AtomContent::text(text),
            metadata: AtomMetadata {
                created_at: fixed_ts(),
                tags: vec![],
            },
        }
    }

    fn setup() -> (TempDir, ObjectStore) {
        let dir = TempDir::new().unwrap();
        let rlm_root = dir.path().join(".rlm");
        fs::create_dir_all(&rlm_root).unwrap();
        let store = ObjectStore::open(&rlm_root).unwrap();
        store.init_dirs().unwrap();
        (dir, store)
    }

    /// Build a small course graph for testing:
    ///
    /// Course
    ///  └─ Contains → Lesson (binary search)
    ///       ├─ CoversConcept → Concept: "binary search"
    ///       ├─ CoversConcept → Concept: "sorted arrays"
    ///       ├─ IncludesProblem → Problem: "find element"
    ///       └─ Prerequisite → Lesson (arrays)
    ///            └─ CoversConcept → Concept: "arrays"
    fn build_test_course(store: &ObjectStore) -> (Hash, Hash, Hash, Vec<Hash>) {
        let c_arrays = store.write(&make_concept("arrays")).unwrap();
        let c_binary = store.write(&make_concept("binary search")).unwrap();
        let c_sorted = store.write(&make_concept("sorted arrays")).unwrap();
        let p_find = store
            .write(&make_problem("find element in sorted array"))
            .unwrap();

        let lesson_arrays = store
            .write(&Frame {
                kind: FrameKind::Lesson,
                edges: vec![Edge {
                    label: EdgeLabel::CoversConcept,
                    target: c_arrays,
                    weight: None,
                    annotation: None,
                }],
                metadata: FrameMetadata {
                    created_at: fixed_ts(),
                    tags: vec![],
                    label: Some("arrays".into()),
                    label_in_hash: true,
                },
            })
            .unwrap();

        let lesson_bs = store
            .write(&Frame {
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
                        label: EdgeLabel::IncludesProblem,
                        target: p_find,
                        weight: None,
                        annotation: None,
                    },
                    Edge {
                        label: EdgeLabel::Prerequisite,
                        target: lesson_arrays,
                        weight: None,
                        annotation: None,
                    },
                ],
                metadata: FrameMetadata {
                    created_at: fixed_ts(),
                    tags: vec![],
                    label: Some("binary-search".into()),
                    label_in_hash: true,
                },
            })
            .unwrap();

        let course = store
            .write(&Frame {
                kind: FrameKind::Course,
                edges: vec![Edge {
                    label: EdgeLabel::Contains,
                    target: lesson_bs,
                    weight: None,
                    annotation: None,
                }],
                metadata: FrameMetadata {
                    created_at: fixed_ts(),
                    tags: vec![],
                    label: None,
                    label_in_hash: false,
                },
            })
            .unwrap();

        (
            course,
            lesson_bs,
            lesson_arrays,
            vec![c_arrays, c_binary, c_sorted, p_find],
        )
    }

    #[test]
    fn test_collect_atoms_all() {
        let (_dir, store) = setup();
        let (course, _, _, _) = build_test_course(&store);
        let graph = Graph::new(&store);

        let atoms = graph.collect_atoms(&course, None).unwrap();
        assert_eq!(
            atoms.len(),
            4,
            "Should find all 4 atoms (3 concepts + 1 problem)"
        );
    }

    #[test]
    fn test_collect_atoms_filtered() {
        let (_dir, store) = setup();
        let (course, _, _, _) = build_test_course(&store);
        let graph = Graph::new(&store);

        let concepts = graph
            .collect_atoms(&course, Some(&[AtomKind::ConceptDefinition]))
            .unwrap();
        assert_eq!(concepts.len(), 3);

        let problems = graph
            .collect_atoms(&course, Some(&[AtomKind::ProblemStatement]))
            .unwrap();
        assert_eq!(problems.len(), 1);

        let examples = graph
            .collect_atoms(&course, Some(&[AtomKind::WorkedExample]))
            .unwrap();
        assert_eq!(examples.len(), 0);
    }

    #[test]
    fn test_collect_frames() {
        let (_dir, store) = setup();
        let (course, _, _, _) = build_test_course(&store);
        let graph = Graph::new(&store);

        let all_frames = graph.collect_frames(&course, None).unwrap();
        assert_eq!(all_frames.len(), 3, "Course + 2 lessons");

        let lessons = graph
            .collect_frames(&course, Some(&[FrameKind::Lesson]))
            .unwrap();
        assert_eq!(lessons.len(), 2);

        let courses = graph
            .collect_frames(&course, Some(&[FrameKind::Course]))
            .unwrap();
        assert_eq!(courses.len(), 1);
    }

    #[test]
    fn test_walk_all() {
        let (_dir, store) = setup();
        let (course, _, _, _) = build_test_course(&store);
        let graph = Graph::new(&store);

        let all = graph.walk_all(&course).unwrap();
        // 3 frames + 4 atoms = 7
        assert_eq!(all.len(), 7);
    }

    #[test]
    fn test_edges_from() {
        let (_dir, store) = setup();
        let (_, lesson_bs, _, _) = build_test_course(&store);
        let graph = Graph::new(&store);

        let all_edges = graph.edges_from(&lesson_bs, None).unwrap();
        assert_eq!(all_edges.len(), 4);

        let concept_edges = graph
            .edges_from(&lesson_bs, Some(&[EdgeLabel::CoversConcept]))
            .unwrap();
        assert_eq!(concept_edges.len(), 2);

        let prereq_edges = graph
            .edges_from(&lesson_bs, Some(&[EdgeLabel::Prerequisite]))
            .unwrap();
        assert_eq!(prereq_edges.len(), 1);
    }

    #[test]
    fn test_student_mastery_map() {
        let (_dir, store) = setup();
        let c1 = store.write(&make_concept("recursion")).unwrap();
        let c2 = store.write(&make_concept("loops")).unwrap();

        let model = store
            .write(&Frame {
                kind: FrameKind::StudentModel,
                edges: vec![
                    Edge {
                        label: EdgeLabel::MasteryEstimate,
                        target: c1,
                        weight: Some(0.3),
                        annotation: None,
                    },
                    Edge {
                        label: EdgeLabel::MasteryEstimate,
                        target: c2,
                        weight: Some(0.9),
                        annotation: None,
                    },
                ],
                metadata: FrameMetadata {
                    created_at: fixed_ts(),
                    tags: vec![],
                    label: None,
                    label_in_hash: false,
                },
            })
            .unwrap();

        let graph = Graph::new(&store);
        let mastery = graph.student_mastery_map(&model).unwrap();
        assert_eq!(mastery.len(), 2);

        let r = mastery.iter().find(|(h, _)| *h == c1).unwrap();
        assert!((r.1 - 0.3).abs() < f64::EPSILON);
        let l = mastery.iter().find(|(h, _)| *h == c2).unwrap();
        assert!((l.1 - 0.9).abs() < f64::EPSILON);
    }

    #[test]
    fn test_shortest_path() {
        let (_dir, store) = setup();
        let (course, _lesson_bs, lesson_arrays, atoms) = build_test_course(&store);
        let graph = Graph::new(&store);

        // Course → lesson_bs → concept (depth 2)
        let c_binary = atoms[1]; // "binary search"
        let path = graph.shortest_path(&course, &c_binary, 10).unwrap();
        assert!(path.is_some());
        let path = path.unwrap();
        assert_eq!(path[0], course);
        assert_eq!(*path.last().unwrap(), c_binary);
        assert!(path.len() <= 3, "Should be at most 3 hops");

        // Course → lesson_bs → lesson_arrays → concept_arrays (depth 3)
        let c_arrays = atoms[0];
        let path = graph.shortest_path(&course, &c_arrays, 10).unwrap();
        assert!(path.is_some());
        let path = path.unwrap();
        assert!(path.contains(&lesson_arrays));

        // No path with insufficient depth
        let path = graph.shortest_path(&course, &c_arrays, 1).unwrap();
        assert!(path.is_none());
    }

    #[test]
    fn test_session_events() {
        let (_dir, store) = setup();

        let e_start = store
            .write(&Event {
                kind: EventKind::SessionStart,
                parents: vec![],
                inputs: vec![],
                outputs: vec![],
                trace: CallTrace::empty(),
                metadata: EventMetadata {
                    timestamp: fixed_ts(),
                    tags: vec![],
                },
            })
            .unwrap();

        let e_input = store
            .write(&Event {
                kind: EventKind::StudentInput,
                parents: vec![e_start],
                inputs: vec![],
                outputs: vec![],
                trace: CallTrace::empty(),
                metadata: EventMetadata {
                    timestamp: fixed_ts(),
                    tags: vec![],
                },
            })
            .unwrap();

        let e_call = store
            .write(&Event {
                kind: EventKind::ModelCall,
                parents: vec![e_input],
                inputs: vec![],
                outputs: vec![],
                trace: CallTrace {
                    call_depth: 0,
                    ..CallTrace::empty()
                },
                metadata: EventMetadata {
                    timestamp: fixed_ts(),
                    tags: vec![],
                },
            })
            .unwrap();

        let graph = Graph::new(&store);
        let events = graph.session_events(&e_call).unwrap();
        assert_eq!(events.len(), 3);
        assert_eq!(events[0].1.kind, EventKind::SessionStart);
        assert_eq!(events[1].1.kind, EventKind::StudentInput);
        assert_eq!(events[2].1.kind, EventKind::ModelCall);
    }

    #[test]
    fn test_call_tree() {
        let (_dir, store) = setup();

        let child_output = store.write(&make_concept("child output")).unwrap();
        let child_event = store
            .write(&Event {
                kind: EventKind::ModelCall,
                parents: vec![],
                inputs: vec![],
                outputs: vec![EventRef {
                    hash: child_output,
                    role: "model_output".into(),
                }],
                trace: CallTrace {
                    call_depth: 1,
                    ..CallTrace::empty()
                },
                metadata: EventMetadata {
                    timestamp: fixed_ts(),
                    tags: vec![],
                },
            })
            .unwrap();

        let root_event = store
            .write(&Event {
                kind: EventKind::ModelCall,
                parents: vec![],
                inputs: vec![],
                outputs: vec![EventRef {
                    hash: child_event,
                    role: "child_call".into(),
                }],
                trace: CallTrace {
                    call_depth: 0,
                    ..CallTrace::empty()
                },
                metadata: EventMetadata {
                    timestamp: fixed_ts(),
                    tags: vec![],
                },
            })
            .unwrap();

        let graph = Graph::new(&store);
        let tree = graph.call_tree(&root_event).unwrap().unwrap();
        assert_eq!(tree.event.kind, EventKind::ModelCall);
        assert_eq!(tree.children.len(), 1);
        assert_eq!(tree.children[0].event.trace.call_depth, 1);
    }
}
