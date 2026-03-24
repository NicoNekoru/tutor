"""
rlm_ws: Content-addressable object store for RLM workspaces.

The native types (Hash, Atom, Edge, Frame, EventRef, CallTrace, Event,
Workspace) are provided by the Rust extension module built via maturin.

This package layers the Python retrieval system, ingestion, session
management, and CLI on top.
"""

# Re-export from the native module.
from .rlm_ws import (  # noqa: F401
    Hash,
    Atom,
    Edge,
    Frame,
    EventRef,
    CallTrace,
    Event,
    Workspace,
)

from .retrieval import (  # noqa: F401
    RetrievalQuery,
    RetrievalIntent,
    ScoredCandidate,
    RetrievalPolicy,
    GraphProximity,
    MasteryAware,
    TemporalRecency,
    PrerequisiteChain,
    InteractionHistory,
    DEFAULT_POLICIES,
    retrieve,
)
