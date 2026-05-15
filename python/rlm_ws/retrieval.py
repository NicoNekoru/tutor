"""
Retrieval system for RLM workspaces.

Retrieval is not a single function — it is a pipeline of composable
strategies, each producing scored candidates, which are then merged
and ranked by a RetrievalPolicy.

This module lives in Python (not Rust) per the plumbing/porcelain split:
the Rust core handles storage and graph traversal; Python handles retrieval
policies, strategy composition, and pedagogical logic.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from .rlm_ws import Hash, Workspace


# ============================================================================
# Core types
# ============================================================================


class RetrievalIntent(Enum):
    """Why the model is retrieving — determines strategy weighting."""

    GENERAL = "general"
    EXPLAIN_CONCEPT = "explain_concept"
    GENERATE_PROBLEM = "generate_problem"
    DIAGNOSE_MISCONCEPTION = "diagnose_misconception"
    ASSESS_MASTERY = "assess_mastery"
    PLAN_LESSON = "plan_lesson"
    REVIEW_SESSION_HISTORY = "review_session_history"


@dataclass
class RetrievalQuery:
    """A parameterized retrieval request.

    This is the input to the retrieval pipeline. It specifies what to
    retrieve, why, and with what constraints.
    """

    # What kind of content to retrieve (AtomKind/FrameKind strings).
    target_kinds: list[str] = field(default_factory=list)

    # Concept hashes to focus on.
    focus_concepts: list[Hash] = field(default_factory=list)

    # The intent of the retrieval.
    intent: RetrievalIntent = RetrievalIntent.GENERAL

    # Temporal weighting: higher = more recent content preferred.
    recency_weight: float = 0.5

    # Maximum number of results.
    max_results: int = 20

    # If provided, use this student model hash for mastery-aware filtering.
    student_model: Hash | None = None

    # Optional free-text query for semantic similarity (future use).
    text_query: str | None = None


@dataclass
class ScoredCandidate:
    """A retrieval result with a relevance score and provenance."""

    hash: Hash
    score: float  # [0.0, 1.0]
    source_strategy: str  # which strategy produced this candidate
    explanation: str  # why this candidate was selected


@dataclass(frozen=True)
class SparseTextEntry:
    """A text object represented as a sparse token vector."""

    hash: Hash
    kind: str
    vector: dict[str, float]
    norm: float


@dataclass(frozen=True)
class SparseTextIndex:
    """Rebuildable local text index used for semantic-style retrieval."""

    entries: tuple[SparseTextEntry, ...]

    @classmethod
    def from_workspace(
        cls,
        ws: Workspace,
        target_kinds: list[str] | None = None,
    ) -> "SparseTextIndex":
        entries: list[SparseTextEntry] = []
        seen: set[Hash] = set()
        kinds = set(target_kinds or _TEXT_ATOM_KINDS)

        course_hash = ws.get_ref_hash("course/structure")
        if course_hash:
            try:
                atoms = ws.collect_atoms(course_hash)
            except Exception:
                atoms = []
            for atom_hash, atom in atoms:
                if atom_hash in seen or atom.kind not in kinds:
                    continue
                seen.add(atom_hash)
                entry = _sparse_text_entry(atom_hash, atom.kind, atom.text)
                if entry is not None:
                    entries.append(entry)
        else:
            for kind in kinds:
                try:
                    hashes = ws.atoms_by_kind(kind)
                except Exception:
                    continue
                for atom_hash in hashes:
                    if atom_hash in seen:
                        continue
                    atom = ws.get_atom(atom_hash)
                    if atom is None:
                        continue
                    seen.add(atom_hash)
                    entry = _sparse_text_entry(atom_hash, atom.kind, atom.text)
                    if entry is not None:
                        entries.append(entry)

        return cls(entries=tuple(entries))

    def search(self, text: str, limit: int) -> list[tuple[SparseTextEntry, float]]:
        query_vector, query_norm = _sparse_vector(text)
        if query_norm == 0.0:
            return []

        scored: list[tuple[SparseTextEntry, float]] = []
        for entry in self.entries:
            dot = sum(
                query_weight * entry.vector.get(token, 0.0)
                for token, query_weight in query_vector.items()
            )
            if dot <= 0.0:
                continue
            scored.append((entry, dot / (query_norm * entry.norm)))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]


class EmbeddingProvider(Protocol):
    """Provider for optional derived embedding vectors."""

    @property
    def name(self) -> str:
        """Provider name for provenance."""
        ...

    def embed(self, text: str) -> list[float]:
        """Return an embedding vector for text."""
        ...


class HashingEmbeddingProvider:
    """Deterministic local embedding provider for offline derived indexes."""

    name = "HashingEmbeddingProvider"

    def __init__(self, dimensions: int = 64):
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        return vector


@dataclass(frozen=True)
class DerivedEmbeddingEntry:
    """A text object represented by a derived embedding vector."""

    hash: Hash
    kind: str
    vector: tuple[float, ...]
    norm: float


@dataclass(frozen=True)
class DerivedEmbeddingIndex:
    """Optional rebuildable embedding index derived from workspace text."""

    provider_name: str
    entries: tuple[DerivedEmbeddingEntry, ...]

    @classmethod
    def from_workspace(
        cls,
        ws: Workspace,
        provider: EmbeddingProvider,
        target_kinds: list[str] | None = None,
    ) -> "DerivedEmbeddingIndex":
        sparse = SparseTextIndex.from_workspace(ws, target_kinds)
        entries: list[DerivedEmbeddingEntry] = []
        for entry in sparse.entries:
            atom = ws.get_atom(entry.hash)
            if atom is None:
                continue
            vector = tuple(provider.embed(atom.text))
            norm = _vector_norm(vector)
            if norm == 0.0:
                continue
            entries.append(
                DerivedEmbeddingEntry(
                    hash=entry.hash,
                    kind=entry.kind,
                    vector=vector,
                    norm=norm,
                )
            )
        return cls(provider_name=provider.name, entries=tuple(entries))

    def search(
        self,
        text: str,
        provider: EmbeddingProvider,
        limit: int,
    ) -> list[tuple[DerivedEmbeddingEntry, float]]:
        query_vector = tuple(provider.embed(text))
        query_norm = _vector_norm(query_vector)
        if query_norm == 0.0:
            return []

        scored: list[tuple[DerivedEmbeddingEntry, float]] = []
        for entry in self.entries:
            score = _cosine(query_vector, query_norm, entry.vector, entry.norm)
            if score <= 0.0:
                continue
            scored.append((entry, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]


_TEXT_ATOM_KINDS = [
    "ConceptDefinition",
    "LessonBody",
    "ProblemStatement",
    "WorkedExample",
    "StudentResponse",
    "ModelOutput",
    "Annotation",
]

_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "can",
    "does",
    "for",
    "from",
    "how",
    "into",
    "the",
    "this",
    "what",
    "when",
    "where",
    "with",
    "would",
}


def _sparse_text_entry(
    atom_hash: Hash,
    kind: str,
    text: str,
) -> SparseTextEntry | None:
    vector, norm = _sparse_vector(text)
    if norm == 0.0:
        return None
    return SparseTextEntry(hash=atom_hash, kind=kind, vector=vector, norm=norm)


def _sparse_vector(text: str) -> tuple[dict[str, float], float]:
    counts = Counter(_tokenize(text))
    if not counts:
        return {}, 0.0
    vector = {token: 1.0 + math.log(count) for token, count in counts.items()}
    norm = math.sqrt(sum(weight * weight for weight in vector.values()))
    return vector, norm


def _vector_norm(vector: tuple[float, ...]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _cosine(
    left: tuple[float, ...],
    left_norm: float,
    right: tuple[float, ...],
    right_norm: float,
) -> float:
    if left_norm == 0.0 or right_norm == 0.0 or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        if len(raw) < 3 or raw in _STOPWORDS:
            continue
        token = _normalize_token(raw)
        if len(token) >= 3 and token not in _STOPWORDS:
            tokens.append(token)
    return tokens


def _normalize_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[: -len(suffix)]
    return token


# ============================================================================
# Strategy protocol
# ============================================================================


@runtime_checkable
class RetrievalStrategy(Protocol):
    """A single retrieval strategy that produces scored candidates.

    Strategies are composable: a RetrievalPolicy runs multiple strategies,
    merges their results, and returns a ranked list.
    """

    @property
    def name(self) -> str:
        """Human-readable strategy name for provenance tracking."""
        ...

    def retrieve(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        """Execute the strategy and return scored candidates."""
        ...


# ============================================================================
# Built-in strategies
# ============================================================================


class GraphProximity:
    """Score by graph distance from focus concepts.

    BFS from each focus concept, scoring inversely with distance.
    Objects closer in the graph score higher. This is the baseline
    strategy — it always runs.
    """

    name = "GraphProximity"

    def __init__(self, max_depth: int = 4, decay: float = 0.6):
        self.max_depth = max_depth
        self.decay = decay

    # Edge labels that represent curricular structure (not student state).
    _CURRICULAR_LABELS = {
        "CoversConcept",
        "Contains",
        "IncludesProblem",
        "IncludesExample",
        "Prerequisite",
    }

    def retrieve(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        if not query.focus_concepts:
            return []

        candidates: dict[Hash, ScoredCandidate] = {}

        for concept_hash in query.focus_concepts:
            # Use reverse edges to find frames that reference this concept.
            # Filter to curricular labels only — student model edges
            # (MasteryEstimate, InteractionRecord) should not drive graph
            # proximity, otherwise every concept the student has seen leaks
            # into the results.
            referencing = ws.reverse_edges(concept_hash)
            for frame_hash, label in referencing:
                if label not in self._CURRICULAR_LABELS:
                    continue
                score = self.decay  # distance 1
                self._add_candidate(
                    candidates,
                    frame_hash,
                    score,
                    f"references concept {concept_hash.short()} via {label}",
                )

                # Walk edges from the referencing frame to find related atoms.
                try:
                    atoms = ws.collect_atoms(frame_hash)
                except Exception:
                    continue
                for atom_hash, atom in atoms:
                    if atom_hash == concept_hash:
                        continue  # don't return the focus concept itself
                    atom_score = score * self.decay  # distance 2
                    if query.target_kinds and atom.kind not in query.target_kinds:
                        atom_score *= 0.5  # demote non-matching kinds
                    self._add_candidate(
                        candidates,
                        atom_hash,
                        atom_score,
                        f"{atom.kind} reachable from concept {concept_hash.short()}",
                    )

            # The concept itself gets score 1.0.
            self._add_candidate(
                candidates,
                concept_hash,
                1.0,
                "focus concept",
            )

        return list(candidates.values())

    @staticmethod
    def _add_candidate(
        candidates: dict[Hash, ScoredCandidate],
        h: Hash,
        score: float,
        explanation: str,
    ) -> None:
        if h in candidates:
            existing = candidates[h]
            if score > existing.score:
                existing.score = score
                existing.explanation = explanation
        else:
            candidates[h] = ScoredCandidate(
                hash=h,
                score=score,
                source_strategy="GraphProximity",
                explanation=explanation,
            )


class SemanticSimilarity:
    """Score text objects by sparse-vector similarity to ``query.text_query``.

    This is a local, rebuildable index. It gives the retrieval pipeline a
    semantic-style text path without requiring hosted embeddings or making
    derived data part of workspace correctness.
    """

    name = "SemanticSimilarity"

    def __init__(self, min_score: float = 0.08):
        self.min_score = min_score

    def retrieve(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        if not query.text_query:
            return []

        index = SparseTextIndex.from_workspace(ws, query.target_kinds or None)
        results: list[ScoredCandidate] = []
        for entry, score in index.search(query.text_query, query.max_results * 2):
            if score < self.min_score:
                continue
            results.append(
                ScoredCandidate(
                    hash=entry.hash,
                    score=min(1.0, score),
                    source_strategy=self.name,
                    explanation=f"text similarity {score:.2f} to query",
                )
            )
        return results


class EmbeddingSimilarity:
    """Score text objects with an optional derived embedding provider."""

    name = "EmbeddingSimilarity"

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        min_score: float = 0.08,
    ):
        self.provider = provider
        self.min_score = min_score

    def retrieve(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        if self.provider is None or not query.text_query:
            return []

        index = DerivedEmbeddingIndex.from_workspace(
            ws,
            self.provider,
            query.target_kinds or None,
        )
        results: list[ScoredCandidate] = []
        for entry, score in index.search(
            query.text_query,
            self.provider,
            query.max_results * 2,
        ):
            if score < self.min_score:
                continue
            results.append(
                ScoredCandidate(
                    hash=entry.hash,
                    score=min(1.0, score),
                    source_strategy=self.name,
                    explanation=(
                        f"embedding similarity {score:.2f} "
                        f"via {index.provider_name}"
                    ),
                )
            )
        return results


class MasteryAware:
    """Filter and boost based on student mastery levels.

    Low-mastery concepts are boosted (the student needs help).
    High-mastery concepts are deprioritized (already understood).
    Objects related to low-mastery concepts score higher.
    """

    name = "MasteryAware"

    def __init__(self, low_threshold: float = 0.4, high_threshold: float = 0.8):
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold

    def retrieve(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        if query.student_model is None:
            return []

        mastery_map = dict(ws.student_mastery_map(query.student_model))
        if not mastery_map:
            return []

        candidates: list[ScoredCandidate] = []

        for concept_hash, level in mastery_map.items():
            if level < self.low_threshold:
                # Low mastery: boost this concept and its related content.
                score = 1.0 - level  # lower mastery → higher score
                candidates.append(
                    ScoredCandidate(
                        hash=concept_hash,
                        score=score,
                        source_strategy="MasteryAware",
                        explanation=f"low mastery ({level:.2f}), needs attention",
                    )
                )

                # Find related content via reverse edges.
                for frame_hash, label in ws.reverse_edges(concept_hash):
                    candidates.append(
                        ScoredCandidate(
                            hash=frame_hash,
                            score=score * 0.8,
                            source_strategy="MasteryAware",
                            explanation=f"related to low-mastery concept ({level:.2f})",
                        )
                    )

            elif level > self.high_threshold:
                # High mastery: include but demote.
                candidates.append(
                    ScoredCandidate(
                        hash=concept_hash,
                        score=0.1,
                        source_strategy="MasteryAware",
                        explanation=f"high mastery ({level:.2f}), deprioritized",
                    )
                )

            else:
                # Medium mastery: moderate score.
                score = 0.5
                candidates.append(
                    ScoredCandidate(
                        hash=concept_hash,
                        score=score,
                        source_strategy="MasteryAware",
                        explanation=f"medium mastery ({level:.2f})",
                    )
                )

        return candidates


class TemporalRecency:
    """Score events by recency.

    Recent events and their associated objects score higher.
    Uses the index's temporal queries.
    """

    name = "TemporalRecency"

    def __init__(self, max_events: int = 20, decay_per_rank: float = 0.05):
        self.max_events = max_events
        self.decay_per_rank = decay_per_rank

    def retrieve(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        candidates: list[ScoredCandidate] = []

        recent = ws.recent_events(self.max_events)
        for rank, event_hash in enumerate(recent):
            score = max(0.0, 1.0 - rank * self.decay_per_rank)
            score *= query.recency_weight * 2  # scale by query's recency preference
            score = min(1.0, score)

            candidates.append(
                ScoredCandidate(
                    hash=event_hash,
                    score=score,
                    source_strategy="TemporalRecency",
                    explanation=f"event at recency rank {rank}",
                )
            )

            # Also include the event's input/output objects.
            event = ws.get_event(event_hash)
            if event is None:
                continue
            for ref in event.inputs + event.outputs:
                candidates.append(
                    ScoredCandidate(
                        hash=ref.hash,
                        score=score * 0.7,
                        source_strategy="TemporalRecency",
                        explanation=f"referenced by recent event (rank {rank}, role={ref.role})",
                    )
                )

        return candidates


class PrerequisiteChain:
    """Follow Prerequisite edges to find foundational content.

    Starting from focus concepts, walks Prerequisite edges backwards
    to surface content the student may need to review.
    """

    name = "PrerequisiteChain"

    def __init__(self, max_depth: int = 3, decay: float = 0.7):
        self.max_depth = max_depth
        self.decay = decay

    def retrieve(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        if not query.focus_concepts:
            return []

        candidates: list[ScoredCandidate] = []
        visited: set[Hash] = set()

        # Find frames covering the focus concepts, then walk prerequisites.
        for concept_hash in query.focus_concepts:
            referencing = ws.reverse_edges(concept_hash)
            for frame_hash, label in referencing:
                if label == "CoversConcept":
                    self._walk_prerequisites(
                        ws, frame_hash, 0, 1.0, candidates, visited
                    )

        return candidates

    def _walk_prerequisites(
        self,
        ws: Workspace,
        frame_hash: Hash,
        depth: int,
        score: float,
        candidates: list[ScoredCandidate],
        visited: set[Hash],
    ) -> None:
        if depth >= self.max_depth or frame_hash in visited:
            return
        visited.add(frame_hash)

        prereq_edges = ws.edges_from(frame_hash, "Prerequisite")
        for edge in prereq_edges:
            prereq_score = score * self.decay
            candidates.append(
                ScoredCandidate(
                    hash=edge.target,
                    score=prereq_score,
                    source_strategy="PrerequisiteChain",
                    explanation=f"prerequisite at depth {depth + 1}",
                )
            )

            # Also collect atoms from the prerequisite frame.
            try:
                atoms = ws.collect_atoms(edge.target)
                for atom_hash, atom in atoms:
                    candidates.append(
                        ScoredCandidate(
                            hash=atom_hash,
                            score=prereq_score * 0.8,
                            source_strategy="PrerequisiteChain",
                            explanation=f"content in prerequisite at depth {depth + 1}",
                        )
                    )
            except Exception:
                pass

            # Recurse.
            self._walk_prerequisites(
                ws, edge.target, depth + 1, prereq_score, candidates, visited
            )


class InteractionHistory:
    """Find objects the student has previously interacted with.

    Walks InteractionRecord edges from the student model to find
    past session events and their associated content.
    """

    name = "InteractionHistory"

    def __init__(self, max_interactions: int = 10):
        self.max_interactions = max_interactions

    def retrieve(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        if query.student_model is None:
            return []

        model = ws.get_frame(query.student_model)
        if model is None:
            return []

        candidates: list[ScoredCandidate] = []
        interaction_count = 0

        for edge in model.edges:
            if edge.label != "InteractionRecord":
                continue
            if interaction_count >= self.max_interactions:
                break
            interaction_count += 1

            # Score decays with interaction age (earlier edges = older).
            score = max(0.1, 1.0 - interaction_count * 0.1)

            candidates.append(
                ScoredCandidate(
                    hash=edge.target,
                    score=score,
                    source_strategy="InteractionHistory",
                    explanation=f"past interaction #{interaction_count}",
                )
            )

            # Get the event and include its inputs/outputs.
            event = ws.get_event(edge.target)
            if event is None:
                continue
            for ref in event.inputs + event.outputs:
                candidates.append(
                    ScoredCandidate(
                        hash=ref.hash,
                        score=score * 0.6,
                        source_strategy="InteractionHistory",
                        explanation=f"referenced in past interaction #{interaction_count} (role={ref.role})",
                    )
                )

        return candidates


# ============================================================================
# Retrieval policy: composes strategies into a pipeline
# ============================================================================


@dataclass
class RetrievalPolicy:
    """Defines how strategies are weighted and composed for a given intent.

    Each strategy produces candidates independently. The policy merges
    them (keeping the best score per hash), applies weights, and returns
    the top-k results.
    """

    strategies: list[tuple[RetrievalStrategy, float]]  # (strategy, weight)

    def execute(
        self,
        query: RetrievalQuery,
        ws: Workspace,
    ) -> list[ScoredCandidate]:
        """Run all strategies, merge candidates, return ranked results."""
        merged: dict[Hash, ScoredCandidate] = {}

        for strategy, weight in self.strategies:
            try:
                candidates = strategy.retrieve(query, ws)
            except Exception:
                # A failing strategy degrades quality, not correctness.
                continue

            for c in candidates:
                weighted_score = min(1.0, c.score * weight)
                if c.hash in merged:
                    existing = merged[c.hash]
                    if weighted_score > existing.score:
                        existing.score = weighted_score
                        existing.explanation = (
                            f"{c.explanation} (via {c.source_strategy})"
                        )
                        existing.source_strategy = c.source_strategy
                else:
                    merged[c.hash] = ScoredCandidate(
                        hash=c.hash,
                        score=weighted_score,
                        source_strategy=c.source_strategy,
                        explanation=c.explanation,
                    )

        ranked = sorted(merged.values(), key=lambda c: c.score, reverse=True)
        return ranked[: query.max_results]


# ============================================================================
# Default policies per intent
# ============================================================================

DEFAULT_POLICIES: dict[RetrievalIntent, RetrievalPolicy] = {
    RetrievalIntent.GENERAL: RetrievalPolicy(
        strategies=[
            (SemanticSimilarity(), 0.7),
            (GraphProximity(), 0.8),
            (MasteryAware(), 0.5),
            (TemporalRecency(), 0.3),
        ]
    ),
    RetrievalIntent.EXPLAIN_CONCEPT: RetrievalPolicy(
        strategies=[
            (SemanticSimilarity(), 0.8),
            (GraphProximity(), 0.9),
            (PrerequisiteChain(), 0.8),
            (MasteryAware(), 0.6),
        ]
    ),
    RetrievalIntent.GENERATE_PROBLEM: RetrievalPolicy(
        strategies=[
            (SemanticSimilarity(), 0.5),
            (GraphProximity(), 0.7),
            (MasteryAware(), 0.9),
        ]
    ),
    RetrievalIntent.DIAGNOSE_MISCONCEPTION: RetrievalPolicy(
        strategies=[
            (SemanticSimilarity(), 0.5),
            (InteractionHistory(), 0.9),
            (MasteryAware(), 0.8),
            (GraphProximity(), 0.5),
        ]
    ),
    RetrievalIntent.ASSESS_MASTERY: RetrievalPolicy(
        strategies=[
            (SemanticSimilarity(), 0.4),
            (MasteryAware(), 0.9),
            (InteractionHistory(), 0.7),
            (GraphProximity(), 0.4),
        ]
    ),
    RetrievalIntent.PLAN_LESSON: RetrievalPolicy(
        strategies=[
            (SemanticSimilarity(), 0.6),
            (GraphProximity(), 0.8),
            (PrerequisiteChain(), 0.9),
            (MasteryAware(), 0.7),
            (TemporalRecency(), 0.3),
        ]
    ),
    RetrievalIntent.REVIEW_SESSION_HISTORY: RetrievalPolicy(
        strategies=[
            (SemanticSimilarity(), 0.3),
            (TemporalRecency(), 0.9),
            (InteractionHistory(), 0.8),
            (MasteryAware(), 0.4),
        ]
    ),
}


def retrieve(
    query: RetrievalQuery,
    ws: Workspace,
    policy: RetrievalPolicy | None = None,
) -> list[ScoredCandidate]:
    """Convenience function: retrieve using the default policy for the query's intent.

    Pass a custom policy to override.
    """
    if policy is None:
        policy = DEFAULT_POLICIES.get(
            query.intent,
            DEFAULT_POLICIES[RetrievalIntent.GENERAL],
        )
    return policy.execute(query, ws)
