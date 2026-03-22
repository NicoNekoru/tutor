// ============================================================================
// PyO3 bridge: exposes the Rust core to Python as native classes.
//
// Written against PyO3 0.28 (Bound<'py, T> API).
// ============================================================================

use pyo3::exceptions::{PyIOError, PyKeyError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyModule};
use std::path::PathBuf;

use crate::error::Error as RlmError;
use crate::types;

/// Convert our error type to a Python exception.
#[allow(clippy::needless_pass_by_value)]
fn to_pyerr(e: RlmError) -> PyErr {
    match &e {
        RlmError::NotFound(_) => PyKeyError::new_err(e.to_string()),
        RlmError::TypeMismatch { .. } => PyTypeError::new_err(e.to_string()),
        RlmError::InvalidHash(_) | RlmError::RefConflict { .. } => {
            PyValueError::new_err(e.to_string())
        }
        RlmError::WorkspaceExists(_) | RlmError::WorkspaceNotFound(_) => {
            PyIOError::new_err(e.to_string())
        }
        _ => PyIOError::new_err(e.to_string()),
    }
}

// ============================================================================
// PyHash
// ============================================================================

#[pyclass(name = "Hash", frozen, eq, hash, from_py_object)]
#[derive(Clone, PartialEq, Eq, std::hash::Hash)]
pub struct PyHash {
    pub(crate) inner: crate::hash::Hash,
}

#[pymethods]
impl PyHash {
    #[staticmethod]
    fn compute(data: &[u8]) -> Self {
        PyHash {
            inner: crate::hash::Hash::compute(data),
        }
    }

    #[staticmethod]
    fn from_hex(hex: &str) -> PyResult<Self> {
        crate::hash::Hash::from_hex(hex)
            .map(|h| PyHash { inner: h })
            .map_err(to_pyerr)
    }

    #[staticmethod]
    fn zero() -> Self {
        PyHash {
            inner: crate::hash::Hash::zero(),
        }
    }

    fn to_hex(&self) -> String {
        self.inner.to_hex()
    }

    fn short(&self) -> String {
        self.inner.short()
    }

    fn to_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.as_bytes())
    }

    fn __str__(&self) -> String {
        self.inner.to_hex()
    }

    fn __repr__(&self) -> String {
        format!("Hash({})", self.inner.short())
    }
}

// ============================================================================
// PyAtom
// ============================================================================

#[pyclass(name = "Atom", from_py_object)]
#[derive(Clone)]
pub struct PyAtom {
    pub(crate) inner: types::Atom,
}

#[pymethods]
impl PyAtom {
    #[new]
    #[pyo3(signature = (kind, text, tags=None, structured=None, binary=None, mime_type=None))]
    fn new(
        py: Python<'_>,
        kind: &str,
        text: &str,
        tags: Option<Vec<String>>,
        structured: Option<Bound<'_, PyDict>>,
        binary: Option<Vec<u8>>,
        mime_type: Option<String>,
    ) -> PyResult<Self> {
        let kind = parse_atom_kind(kind)?;
        let structured_val = match structured {
            Some(d) => {
                let json_str = pythonize_dict_to_json(py, &d)?;
                Some(
                    serde_json::from_str(&json_str)
                        .map_err(|e| PyValueError::new_err(e.to_string()))?,
                )
            }
            None => None,
        };
        Ok(PyAtom {
            inner: types::Atom {
                kind,
                content: types::AtomContent {
                    text: text.to_string(),
                    structured: structured_val,
                    binary,
                    mime_type,
                },
                metadata: types::AtomMetadata {
                    created_at: chrono::Utc::now(),
                    tags: tags.unwrap_or_default(),
                },
            },
        })
    }

    #[getter]
    fn kind(&self) -> String {
        format!("{:?}", self.inner.kind)
    }

    #[getter]
    fn text(&self) -> &str {
        &self.inner.content.text
    }

    #[getter]
    fn tags(&self) -> Vec<String> {
        self.inner.metadata.tags.clone()
    }

    #[getter]
    fn created_at(&self) -> String {
        self.inner.metadata.created_at.to_rfc3339()
    }

    #[getter]
    fn structured(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.inner.content.structured {
            Some(v) => json_to_py(py, v),
            None => Ok(py.None()),
        }
    }

    #[getter]
    fn binary<'py>(&self, py: Python<'py>) -> Py<PyAny> {
        match &self.inner.content.binary {
            Some(b) => PyBytes::new(py, b).into_any().unbind(),
            None => py.None(),
        }
    }

    #[getter]
    fn mime_type(&self) -> Option<String> {
        self.inner.content.mime_type.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "Atom(kind={:?}, text={:?})",
            format!("{:?}", self.inner.kind),
            truncate(&self.inner.content.text, 50)
        )
    }
}

// ============================================================================
// PyEdge
// ============================================================================

#[pyclass(name = "Edge", from_py_object)]
#[derive(Clone)]
pub struct PyEdge {
    pub(crate) inner: types::Edge,
}

#[pymethods]
impl PyEdge {
    #[new]
    #[pyo3(signature = (label, target, weight=None, annotation=None))]
    fn new(
        py: Python<'_>,
        label: &str,
        target: &PyHash,
        weight: Option<f64>,
        annotation: Option<Bound<'_, PyDict>>,
    ) -> PyResult<Self> {
        let label = parse_edge_label(label)?;
        let annotation_val = match annotation {
            Some(d) => {
                let json_str = pythonize_dict_to_json(py, &d)?;
                Some(
                    serde_json::from_str(&json_str)
                        .map_err(|e| PyValueError::new_err(e.to_string()))?,
                )
            }
            None => None,
        };
        Ok(PyEdge {
            inner: types::Edge {
                label,
                target: target.inner,
                weight,
                annotation: annotation_val,
            },
        })
    }

    #[getter]
    fn label(&self) -> String {
        format!("{:?}", self.inner.label)
    }

    #[getter]
    fn target(&self) -> PyHash {
        PyHash {
            inner: self.inner.target,
        }
    }

    #[getter]
    fn weight(&self) -> Option<f64> {
        self.inner.weight
    }

    #[getter]
    fn annotation(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match &self.inner.annotation {
            Some(v) => json_to_py(py, v),
            None => Ok(py.None()),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Edge(label={:?}, target={})",
            format!("{:?}", self.inner.label),
            self.inner.target.short()
        )
    }
}

// ============================================================================
// PyFrame
// ============================================================================

#[pyclass(name = "Frame", from_py_object)]
#[derive(Clone)]
pub struct PyFrame {
    pub(crate) inner: types::Frame,
}

#[pymethods]
impl PyFrame {
    #[new]
    #[pyo3(signature = (kind, edges, tags=None, label=None, label_in_hash=false))]
    fn new(
        kind: &str,
        edges: Vec<PyEdge>,
        tags: Option<Vec<String>>,
        label: Option<String>,
        label_in_hash: bool,
    ) -> PyResult<Self> {
        let kind = parse_frame_kind(kind)?;
        let edges: Vec<types::Edge> = edges.into_iter().map(|e| e.inner).collect();
        Ok(PyFrame {
            inner: types::Frame {
                kind,
                edges,
                metadata: types::FrameMetadata {
                    created_at: chrono::Utc::now(),
                    tags: tags.unwrap_or_default(),
                    label,
                    label_in_hash,
                },
            },
        })
    }

    #[getter]
    fn kind(&self) -> String {
        format!("{:?}", self.inner.kind)
    }

    #[getter]
    fn edges(&self) -> Vec<PyEdge> {
        self.inner
            .edges
            .iter()
            .map(|e| PyEdge { inner: e.clone() })
            .collect()
    }

    #[getter]
    fn tags(&self) -> Vec<String> {
        self.inner.metadata.tags.clone()
    }

    #[getter]
    fn label(&self) -> Option<String> {
        self.inner.metadata.label.clone()
    }

    #[getter]
    fn created_at(&self) -> String {
        self.inner.metadata.created_at.to_rfc3339()
    }

    fn __repr__(&self) -> String {
        format!(
            "Frame(kind={:?}, edges={}, label={:?})",
            format!("{:?}", self.inner.kind),
            self.inner.edges.len(),
            self.inner.metadata.label
        )
    }
}

// ============================================================================
// PyEventRef
// ============================================================================

#[pyclass(name = "EventRef", from_py_object)]
#[derive(Clone)]
pub struct PyEventRef {
    pub(crate) inner: types::EventRef,
}

#[pymethods]
impl PyEventRef {
    #[new]
    fn new(hash: &PyHash, role: &str) -> Self {
        PyEventRef {
            inner: types::EventRef {
                hash: hash.inner,
                role: role.to_string(),
            },
        }
    }

    #[getter]
    fn hash(&self) -> PyHash {
        PyHash {
            inner: self.inner.hash,
        }
    }

    #[getter]
    fn role(&self) -> &str {
        &self.inner.role
    }
}

// ============================================================================
// PyCallTrace
// ============================================================================

#[pyclass(name = "CallTrace", from_py_object)]
#[derive(Clone)]
pub struct PyCallTrace {
    pub(crate) inner: types::CallTrace,
}

#[pymethods]
impl PyCallTrace {
    #[new]
    #[pyo3(signature = (
        call_depth=0,
        model=None,
        prompt_template=None,
        input_tokens=None,
        output_tokens=None,
        latency_ms=None,
        retrieval_scope=None,
        parent_call=None,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        call_depth: u32,
        model: Option<String>,
        prompt_template: Option<String>,
        input_tokens: Option<u64>,
        output_tokens: Option<u64>,
        latency_ms: Option<u64>,
        retrieval_scope: Option<PyHash>,
        parent_call: Option<PyHash>,
    ) -> Self {
        PyCallTrace {
            inner: types::CallTrace {
                model,
                prompt_template,
                input_tokens,
                output_tokens,
                latency_ms,
                retrieval_scope: retrieval_scope.map(|h| h.inner),
                call_depth,
                parent_call: parent_call.map(|h| h.inner),
                extra: None,
            },
        }
    }

    #[getter]
    fn call_depth(&self) -> u32 {
        self.inner.call_depth
    }

    #[getter]
    fn model(&self) -> Option<String> {
        self.inner.model.clone()
    }

    #[getter]
    fn input_tokens(&self) -> Option<u64> {
        self.inner.input_tokens
    }

    #[getter]
    fn output_tokens(&self) -> Option<u64> {
        self.inner.output_tokens
    }

    #[getter]
    fn latency_ms(&self) -> Option<u64> {
        self.inner.latency_ms
    }
}

// ============================================================================
// PyEvent
// ============================================================================

#[pyclass(name = "Event", from_py_object)]
#[derive(Clone)]
pub struct PyEvent {
    pub(crate) inner: types::Event,
}

#[pymethods]
impl PyEvent {
    #[new]
    #[pyo3(signature = (kind, parents=None, inputs=None, outputs=None, trace=None, tags=None))]
    fn new(
        kind: &str,
        parents: Option<Vec<PyHash>>,
        inputs: Option<Vec<PyEventRef>>,
        outputs: Option<Vec<PyEventRef>>,
        trace: Option<PyCallTrace>,
        tags: Option<Vec<String>>,
    ) -> PyResult<Self> {
        let kind = parse_event_kind(kind)?;
        Ok(PyEvent {
            inner: types::Event {
                kind,
                parents: parents
                    .unwrap_or_default()
                    .into_iter()
                    .map(|h| h.inner)
                    .collect(),
                inputs: inputs
                    .unwrap_or_default()
                    .into_iter()
                    .map(|r| r.inner)
                    .collect(),
                outputs: outputs
                    .unwrap_or_default()
                    .into_iter()
                    .map(|r| r.inner)
                    .collect(),
                trace: trace.map_or_else(types::CallTrace::empty, |t| t.inner),
                metadata: types::EventMetadata {
                    timestamp: chrono::Utc::now(),
                    tags: tags.unwrap_or_default(),
                },
            },
        })
    }

    #[getter]
    fn kind(&self) -> String {
        format!("{:?}", self.inner.kind)
    }

    #[getter]
    fn parents(&self) -> Vec<PyHash> {
        self.inner
            .parents
            .iter()
            .map(|h| PyHash { inner: *h })
            .collect()
    }

    #[getter]
    fn inputs(&self) -> Vec<PyEventRef> {
        self.inner
            .inputs
            .iter()
            .map(|r| PyEventRef { inner: r.clone() })
            .collect()
    }

    #[getter]
    fn outputs(&self) -> Vec<PyEventRef> {
        self.inner
            .outputs
            .iter()
            .map(|r| PyEventRef { inner: r.clone() })
            .collect()
    }

    #[getter]
    fn trace(&self) -> PyCallTrace {
        PyCallTrace {
            inner: self.inner.trace.clone(),
        }
    }

    #[getter]
    fn timestamp(&self) -> String {
        self.inner.metadata.timestamp.to_rfc3339()
    }

    #[getter]
    fn tags(&self) -> Vec<String> {
        self.inner.metadata.tags.clone()
    }

    fn __repr__(&self) -> String {
        format!("Event(kind={:?})", format!("{:?}", self.inner.kind))
    }
}

// ============================================================================
// PyWorkspace
// ============================================================================

/// `unsendable` because rusqlite::Connection is !Sync.
/// This restricts the object to the thread that created it, which is fine
/// since Python has the GIL.
#[pyclass(name = "Workspace", unsendable)]
pub struct PyWorkspace {
    inner: crate::workspace::Workspace,
}

#[pymethods]
impl PyWorkspace {
    #[staticmethod]
    fn init(path: &str) -> PyResult<Self> {
        let ws = crate::workspace::Workspace::init(&PathBuf::from(path)).map_err(to_pyerr)?;
        Ok(PyWorkspace { inner: ws })
    }

    #[staticmethod]
    fn open(path: &str) -> PyResult<Self> {
        let ws = crate::workspace::Workspace::open(&PathBuf::from(path)).map_err(to_pyerr)?;
        Ok(PyWorkspace { inner: ws })
    }

    fn put_atom(&self, atom: &PyAtom) -> PyResult<PyHash> {
        let h = self.inner.put(&atom.inner).map_err(to_pyerr)?;
        Ok(PyHash { inner: h })
    }

    fn put_frame(&self, frame: &PyFrame) -> PyResult<PyHash> {
        let h = self.inner.put(&frame.inner).map_err(to_pyerr)?;
        Ok(PyHash { inner: h })
    }

    fn put_event(&self, event: &PyEvent) -> PyResult<PyHash> {
        let h = self.inner.put(&event.inner).map_err(to_pyerr)?;
        Ok(PyHash { inner: h })
    }

    fn get_atom(&self, hash: &PyHash) -> PyResult<Option<PyAtom>> {
        self.inner
            .get::<types::Atom>(&hash.inner)
            .map(|o| o.map(|a| PyAtom { inner: a }))
            .map_err(to_pyerr)
    }

    fn get_frame(&self, hash: &PyHash) -> PyResult<Option<PyFrame>> {
        self.inner
            .get::<types::Frame>(&hash.inner)
            .map(|o| o.map(|f| PyFrame { inner: f }))
            .map_err(to_pyerr)
    }

    fn get_event(&self, hash: &PyHash) -> PyResult<Option<PyEvent>> {
        self.inner
            .get::<types::Event>(&hash.inner)
            .map(|o| o.map(|e| PyEvent { inner: e }))
            .map_err(to_pyerr)
    }

    fn exists(&self, hash: &PyHash) -> bool {
        self.inner.store.exists(&hash.inner)
    }

    fn get_ref_hash(&self, name: &str) -> PyResult<Option<PyHash>> {
        self.inner
            .get_ref_hash(name)
            .map(|o| o.map(|h| PyHash { inner: h }))
            .map_err(to_pyerr)
    }

    fn set_ref(&self, name: &str, hash: &PyHash) -> PyResult<()> {
        self.inner.set_ref(name, &hash.inner).map_err(to_pyerr)
    }

    fn delete_ref(&self, name: &str) -> PyResult<bool> {
        self.inner.refs.delete(name).map_err(to_pyerr)
    }

    fn cas_ref(&self, name: &str, expected: &PyHash, new: &PyHash) -> PyResult<()> {
        self.inner
            .refs
            .cas(name, &expected.inner, &new.inner)
            .map_err(to_pyerr)
    }

    fn list_refs(&self, prefix: &str) -> PyResult<Vec<(String, PyHash)>> {
        let refs = self.inner.refs.list(prefix).map_err(to_pyerr)?;
        Ok(refs
            .into_iter()
            .map(|r| (r.name, PyHash { inner: r.target }))
            .collect())
    }

    fn commit_mutation(
        &self,
        event: &PyEvent,
        ref_updates: Vec<(String, PyHash, PyHash)>,
    ) -> PyResult<PyHash> {
        let updates: Vec<(&str, crate::hash::Hash, crate::hash::Hash)> = ref_updates
            .iter()
            .map(|(name, exp, new)| (name.as_str(), exp.inner, new.inner))
            .collect();
        let h = self
            .inner
            .commit_mutation(&event.inner, &updates)
            .map_err(to_pyerr)?;
        Ok(PyHash { inner: h })
    }

    // --- Graph ---

    #[pyo3(signature = (root, kind=None))]
    fn collect_atoms(&self, root: &PyHash, kind: Option<&str>) -> PyResult<Vec<(PyHash, PyAtom)>> {
        let graph = self.inner.graph();
        let filter = match kind {
            Some(k) => Some(vec![parse_atom_kind(k)?]),
            None => None,
        };
        let results = graph
            .collect_atoms(&root.inner, filter.as_deref())
            .map_err(to_pyerr)?;
        Ok(results
            .into_iter()
            .map(|(h, a)| (PyHash { inner: h }, PyAtom { inner: a }))
            .collect())
    }

    #[pyo3(signature = (root, kind=None))]
    fn collect_frames(
        &self,
        root: &PyHash,
        kind: Option<&str>,
    ) -> PyResult<Vec<(PyHash, PyFrame)>> {
        let graph = self.inner.graph();
        let filter = match kind {
            Some(k) => Some(vec![parse_frame_kind(k)?]),
            None => None,
        };
        let results = graph
            .collect_frames(&root.inner, filter.as_deref())
            .map_err(to_pyerr)?;
        Ok(results
            .into_iter()
            .map(|(h, f)| (PyHash { inner: h }, PyFrame { inner: f }))
            .collect())
    }

    #[pyo3(signature = (frame_hash, label=None))]
    fn edges_from(&self, frame_hash: &PyHash, label: Option<&str>) -> PyResult<Vec<PyEdge>> {
        let graph = self.inner.graph();
        let filter = match label {
            Some(l) => Some(vec![parse_edge_label(l)?]),
            None => None,
        };
        let results = graph
            .edges_from(&frame_hash.inner, filter.as_deref())
            .map_err(to_pyerr)?;
        Ok(results.into_iter().map(|e| PyEdge { inner: e }).collect())
    }

    fn student_mastery_map(&self, model_hash: &PyHash) -> PyResult<Vec<(PyHash, f64)>> {
        let graph = self.inner.graph();
        let results = graph
            .student_mastery_map(&model_hash.inner)
            .map_err(to_pyerr)?;
        Ok(results
            .into_iter()
            .map(|(h, w)| (PyHash { inner: h }, w))
            .collect())
    }

    fn shortest_path(
        &self,
        from: &PyHash,
        to: &PyHash,
        max_depth: usize,
    ) -> PyResult<Option<Vec<PyHash>>> {
        let graph = self.inner.graph();
        let path = graph
            .shortest_path(&from.inner, &to.inner, max_depth)
            .map_err(to_pyerr)?;
        Ok(path.map(|p| p.into_iter().map(|h| PyHash { inner: h }).collect()))
    }

    fn session_events(&self, session_tip: &PyHash) -> PyResult<Vec<(PyHash, PyEvent)>> {
        let graph = self.inner.graph();
        let results = graph.session_events(&session_tip.inner).map_err(to_pyerr)?;
        Ok(results
            .into_iter()
            .map(|(h, e)| (PyHash { inner: h }, PyEvent { inner: e }))
            .collect())
    }

    // --- Index ---

    fn atoms_by_kind(&self, kind: &str) -> PyResult<Vec<PyHash>> {
        let k = parse_atom_kind(kind)?;
        Ok(self
            .inner
            .index
            .atoms_by_kind(k)
            .map_err(to_pyerr)?
            .into_iter()
            .map(|h| PyHash { inner: h })
            .collect())
    }

    fn frames_by_kind(&self, kind: &str) -> PyResult<Vec<PyHash>> {
        let k = parse_frame_kind(kind)?;
        Ok(self
            .inner
            .index
            .frames_by_kind(k)
            .map_err(to_pyerr)?
            .into_iter()
            .map(|h| PyHash { inner: h })
            .collect())
    }

    fn events_by_kind(&self, kind: &str) -> PyResult<Vec<PyHash>> {
        let k = parse_event_kind(kind)?;
        Ok(self
            .inner
            .index
            .events_by_kind(k)
            .map_err(to_pyerr)?
            .into_iter()
            .map(|h| PyHash { inner: h })
            .collect())
    }

    fn by_tag(&self, tag: &str) -> PyResult<Vec<PyHash>> {
        Ok(self
            .inner
            .index
            .by_tag(tag)
            .map_err(to_pyerr)?
            .into_iter()
            .map(|h| PyHash { inner: h })
            .collect())
    }

    fn reverse_edges(&self, target: &PyHash) -> PyResult<Vec<(PyHash, String)>> {
        Ok(self
            .inner
            .index
            .reverse_edges(&target.inner)
            .map_err(to_pyerr)?
            .into_iter()
            .map(|(h, l)| (PyHash { inner: h }, l))
            .collect())
    }

    #[pyo3(signature = (n, kind=None))]
    fn recent_events(&self, n: usize, kind: Option<&str>) -> PyResult<Vec<PyHash>> {
        let k = match kind {
            Some(s) => Some(parse_event_kind(s)?),
            None => None,
        };
        Ok(self
            .inner
            .index
            .recent_events(n, k)
            .map_err(to_pyerr)?
            .into_iter()
            .map(|h| PyHash { inner: h })
            .collect())
    }

    fn events_in_range(&self, after: &str, before: &str) -> PyResult<Vec<PyHash>> {
        Ok(self
            .inner
            .index
            .events_in_range(after, before)
            .map_err(to_pyerr)?
            .into_iter()
            .map(|h| PyHash { inner: h })
            .collect())
    }

    // --- Maintenance ---

    fn gc(&self) -> PyResult<(usize, usize, usize)> {
        let r = self.inner.gc().map_err(to_pyerr)?;
        Ok((r.total_objects, r.reachable_objects, r.removed_objects))
    }

    fn rebuild_index(&self) -> PyResult<usize> {
        self.inner.rebuild_index().map_err(to_pyerr)
    }

    fn export_json(&self, root: &PyHash) -> PyResult<String> {
        let mut buf = Vec::new();
        self.inner
            .export_json(&root.inner, &mut buf)
            .map_err(to_pyerr)?;
        String::from_utf8(buf).map_err(|e| PyValueError::new_err(e.to_string()))
    }

    fn object_counts(&self) -> PyResult<(usize, usize, usize)> {
        self.inner.index.object_counts().map_err(to_pyerr)
    }

    fn __repr__(&self) -> String {
        format!("Workspace({:?})", self.inner.root().display())
    }
}

// ============================================================================
// Module
// ============================================================================

#[pymodule]
pub fn rlm_ws(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyHash>()?;
    m.add_class::<PyAtom>()?;
    m.add_class::<PyEdge>()?;
    m.add_class::<PyFrame>()?;
    m.add_class::<PyEventRef>()?;
    m.add_class::<PyCallTrace>()?;
    m.add_class::<PyEvent>()?;
    m.add_class::<PyWorkspace>()?;
    Ok(())
}

// ============================================================================
// Helpers
// ============================================================================

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}...", &s[..max])
    }
}

fn parse_atom_kind(s: &str) -> PyResult<types::AtomKind> {
    match s {
        "ConceptDefinition" => Ok(types::AtomKind::ConceptDefinition),
        "LessonBody" => Ok(types::AtomKind::LessonBody),
        "ProblemStatement" => Ok(types::AtomKind::ProblemStatement),
        "WorkedExample" => Ok(types::AtomKind::WorkedExample),
        "StudentResponse" => Ok(types::AtomKind::StudentResponse),
        "ModelOutput" => Ok(types::AtomKind::ModelOutput),
        "Annotation" => Ok(types::AtomKind::Annotation),
        "Config" => Ok(types::AtomKind::Config),
        "Blob" => Ok(types::AtomKind::Blob),
        _ => Err(PyValueError::new_err(format!("Unknown AtomKind: {s}"))),
    }
}

fn parse_frame_kind(s: &str) -> PyResult<types::FrameKind> {
    match s {
        "Lesson" => Ok(types::FrameKind::Lesson),
        "Module" => Ok(types::FrameKind::Module),
        "Course" => Ok(types::FrameKind::Course),
        "StudentModel" => Ok(types::FrameKind::StudentModel),
        "SessionSnapshot" => Ok(types::FrameKind::SessionSnapshot),
        "RetrievalScope" => Ok(types::FrameKind::RetrievalScope),
        "CallContext" => Ok(types::FrameKind::CallContext),
        "Collection" => Ok(types::FrameKind::Collection),
        _ => Err(PyValueError::new_err(format!("Unknown FrameKind: {s}"))),
    }
}

fn parse_edge_label(s: &str) -> PyResult<types::EdgeLabel> {
    match s {
        "Prerequisite" => Ok(types::EdgeLabel::Prerequisite),
        "CoversConcept" => Ok(types::EdgeLabel::CoversConcept),
        "Contains" => Ok(types::EdgeLabel::Contains),
        "IncludesProblem" => Ok(types::EdgeLabel::IncludesProblem),
        "IncludesExample" => Ok(types::EdgeLabel::IncludesExample),
        "MasteryEstimate" => Ok(types::EdgeLabel::MasteryEstimate),
        "Misconception" => Ok(types::EdgeLabel::Misconception),
        "InteractionRecord" => Ok(types::EdgeLabel::InteractionRecord),
        "ProducedOutput" => Ok(types::EdgeLabel::ProducedOutput),
        "ReceivedInput" => Ok(types::EdgeLabel::ReceivedInput),
        "UsedScope" => Ok(types::EdgeLabel::UsedScope),
        "SpawnedChild" => Ok(types::EdgeLabel::SpawnedChild),
        "InScope" => Ok(types::EdgeLabel::InScope),
        "RetrievalPolicy" => Ok(types::EdgeLabel::RetrievalPolicy),
        "Custom" => Ok(types::EdgeLabel::Custom),
        _ => Err(PyValueError::new_err(format!("Unknown EdgeLabel: {s}"))),
    }
}

fn parse_event_kind(s: &str) -> PyResult<types::EventKind> {
    match s {
        "SessionStart" => Ok(types::EventKind::SessionStart),
        "SessionEnd" => Ok(types::EventKind::SessionEnd),
        "ModelCall" => Ok(types::EventKind::ModelCall),
        "StudentInput" => Ok(types::EventKind::StudentInput),
        "StudentModelUpdate" => Ok(types::EventKind::StudentModelUpdate),
        "RetrievalPerformed" => Ok(types::EventKind::RetrievalPerformed),
        "Merge" => Ok(types::EventKind::Merge),
        "Admin" => Ok(types::EventKind::Admin),
        _ => Err(PyValueError::new_err(format!("Unknown EventKind: {s}"))),
    }
}

fn pythonize_dict_to_json(py: Python<'_>, dict: &Bound<'_, PyDict>) -> PyResult<String> {
    let json_mod = py.import("json")?;
    let json_str: String = json_mod.call_method1("dumps", (dict,))?.extract()?;
    Ok(json_str)
}

/// Convert a `serde_json::Value` to a Python object.
fn json_to_py(py: Python<'_>, value: &serde_json::Value) -> PyResult<Py<PyAny>> {
    let json_mod = py.import("json")?;
    let json_str =
        serde_json::to_string(value).map_err(|e| PyValueError::new_err(e.to_string()))?;
    let result = json_mod.call_method1("loads", (json_str,))?;
    Ok(result.unbind())
}
