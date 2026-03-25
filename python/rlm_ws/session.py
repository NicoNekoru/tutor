"""
Interactive tutoring session: the RLM execution loop.

This module implements the session lifecycle:
1. Start session → SessionStart event
2. Student input → StudentInput event
3. Retrieve context → RetrievalPerformed event
4. Call model → ModelCall event
5. Update mastery → StudentModelUpdate event
6. Loop back to 2
7. End session → SessionEnd event

Model calls use httpx to hit OpenRouter (or any OpenAI-compatible endpoint).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import httpx

from .rlm_ws import (
    Atom,
    Edge,
    Event,
    EventRef,
    CallTrace,
    Frame,
    Hash,
    Workspace,
)
from .retrieval import (
    RetrievalQuery,
    RetrievalIntent,
    ScoredCandidate,
    retrieve,
)
from . import display


@dataclass
class SessionConfig:
    """Configuration for a tutoring session."""

    student_id: str = "default"
    model: str = "anthropic/claude-sonnet-4-20250514"
    api_base: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    max_context_results: int = 10
    system_prompt: str = ""

    def __post_init__(self):
        if not self.api_key:
            self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self.system_prompt:
            self.system_prompt = DEFAULT_SYSTEM_PROMPT


DEFAULT_SYSTEM_PROMPT = """You are a patient, knowledgeable tutor. Your role is to help the student understand concepts deeply, not just memorize facts.

Guidelines:
- Start from what the student knows and build on it.
- Use analogies and concrete examples when explaining abstract concepts.
- When the student makes an error, guide them to the correct understanding rather than just stating the answer.
- Periodically check understanding by asking the student to explain concepts back.
- Keep responses focused and not too long — aim for clarity over completeness.

You will be given context about the course material and the student's current mastery levels. Use this to calibrate your explanations.
"""


@dataclass
class SessionState:
    """Mutable state for an active session."""

    ws: Workspace
    config: SessionConfig
    session_event: Hash | None = None
    last_event: Hash | None = None
    student_model: Hash | None = None
    messages: list[dict] = field(default_factory=list)
    turn_count: int = 0


def start_session(ws: Workspace, config: SessionConfig) -> SessionState:
    """Start a new tutoring session."""
    state = SessionState(ws=ws, config=config)

    # Resolve or create student model.
    mastery_ref = f"student/{config.student_id}/mastery"
    model_hash = ws.get_ref_hash(mastery_ref)

    if model_hash is None:
        # Initialize student model from course concepts.
        display.info(f"Creating new student model for '{config.student_id}'")
        model_hash = _init_student_model(ws, config.student_id)

    state.student_model = model_hash

    # Record SessionStart event.
    course_hash = ws.get_ref_hash("course/structure")
    inputs = []
    if model_hash:
        inputs.append(EventRef(model_hash, "student_model"))
    if course_hash:
        inputs.append(EventRef(course_hash, "course"))

    start_event = ws.put_event(
        Event(
            "SessionStart",
            inputs=inputs,
            tags=["session"],
        )
    )
    state.session_event = start_event
    state.last_event = start_event

    session_ref = f"student/{config.student_id}/session/current"
    ws.set_ref(session_ref, start_event)

    display.success(f"Session started for student '{config.student_id}'")

    # Show current mastery.
    if model_hash:
        mastery = ws.student_mastery_map(model_hash)
        if mastery:
            display.mastery_display(mastery, ws)

    return state


def end_session(state: SessionState) -> None:
    """End the current session."""
    end_event = state.ws.put_event(
        Event(
            "SessionEnd",
            parents=[state.last_event] if state.last_event else [],
            tags=["session"],
        )
    )

    # Archive the session.
    session_id = f"session-{state.turn_count}t"
    state.ws.set_ref(
        f"student/{state.config.student_id}/session/{session_id}",
        end_event,
    )

    # Remove current session ref.
    state.ws.delete_ref(f"student/{state.config.student_id}/session/current")

    display.success(f"Session ended ({state.turn_count} turns)")

    # Show final mastery.
    if state.student_model:
        mastery = state.ws.student_mastery_map(state.student_model)
        if mastery:
            display.console.print()
            display.mastery_display(mastery, state.ws)


def run_turn(state: SessionState, user_input: str) -> str:
    """Execute a single turn: student input → retrieval → model call → response.

    Returns the model's response text.
    """
    state.turn_count += 1

    # 1. Record student input.
    input_atom = state.ws.put_atom(
        Atom(
            "StudentResponse",
            user_input,
            tags=["student-input"],
        )
    )
    input_event = state.ws.put_event(
        Event(
            "StudentInput",
            parents=[state.last_event] if state.last_event else [],
            outputs=[EventRef(input_atom, "student_message")],
        )
    )
    state.last_event = input_event

    # 2. Retrieve context.
    context_text, retrieved = _retrieve_context(state, user_input)

    # 3. Build messages.
    system = state.config.system_prompt
    if context_text:
        system += f"\n\n## Relevant Context\n\n{context_text}"

    state.messages.append({"role": "user", "content": user_input})

    # 4. Call model.
    t0 = time.monotonic()
    response_text = _call_model(state, system)
    latency_ms = int((time.monotonic() - t0) * 1000)

    state.messages.append({"role": "assistant", "content": response_text})

    # 5. Record model output + event.
    output_atom = state.ws.put_atom(
        Atom(
            "ModelOutput",
            response_text,
            tags=["model-output"],
        )
    )

    call_event = state.ws.put_event(
        Event(
            "ModelCall",
            parents=[input_event],
            inputs=[EventRef(input_atom, "student_message")]
            + [EventRef(c.hash, "retrieved") for c in retrieved[:5]],
            outputs=[EventRef(output_atom, "model_output")],
            trace=CallTrace(
                call_depth=0,
                model=state.config.model,
                latency_ms=latency_ms,
            ),
        )
    )
    state.last_event = call_event

    return response_text


def run_interactive(ws: Workspace, config: SessionConfig) -> None:
    """Run an interactive tutoring session in the terminal."""
    state = start_session(ws, config)

    display.console.print()
    display.info("Type your questions or 'quit' to end the session.")
    display.info("Commands: /mastery, /tree, /status, /quit")
    display.console.print()

    try:
        while True:
            try:
                user_input = display.student_input_prompt()
            except (EOFError, KeyboardInterrupt):
                display.console.print()
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            # Handle commands.
            if stripped.lower() in ("/quit", "/exit", "quit", "exit"):
                break

            if stripped.lower() == "/mastery":
                if state.student_model:
                    mastery = ws.student_mastery_map(state.student_model)
                    display.mastery_display(mastery, ws)
                else:
                    display.warn("No student model loaded")
                continue

            if stripped.lower() == "/tree":
                course_hash = ws.get_ref_hash("course/structure")
                if course_hash:
                    display.course_tree(ws, course_hash)
                else:
                    display.warn("No course structure found")
                continue

            if stripped.lower() == "/status":
                atoms, frames, events = ws.object_counts()
                display.object_counts_display(atoms, frames, events)
                display.info(f"Turn: {state.turn_count}")
                display.info(f"Student: {config.student_id}")
                display.info(f"Model: {config.model}")
                continue

            # Regular tutoring turn.
            with display.console.status("[cyan]Thinking...", spinner="dots"):
                response = run_turn(state, stripped)

            display.model_response(response)

    finally:
        end_session(state)


# ============================================================================
# Internal helpers
# ============================================================================


def _init_student_model(ws: Workspace, student_id: str) -> Hash | None:
    """Create an initial student model with zero mastery for all course concepts."""
    course_hash = ws.get_ref_hash("course/structure")
    if course_hash is None:
        display.warn("No course structure found — cannot initialize student model")
        return None

    concepts = ws.collect_atoms(course_hash, "ConceptDefinition")
    if not concepts:
        display.warn("No concepts found in course")
        return None

    edges = [
        Edge("MasteryEstimate", concept_hash, weight=0.0)
        for concept_hash, _ in concepts
    ]

    model_hash = ws.put_frame(Frame("StudentModel", edges))
    ws.set_ref(f"student/{student_id}/mastery", model_hash)

    display.info(f"Initialized mastery for {len(concepts)} concept(s)")
    return model_hash


def _retrieve_context(
    state: SessionState,
    user_input: str,
) -> tuple[str, list[ScoredCandidate]]:
    """Run retrieval and format context for the model prompt."""
    # Determine intent from a simple heuristic.
    intent = RetrievalIntent.GENERAL
    lower = user_input.lower()
    if any(w in lower for w in ["explain", "what is", "how does", "describe"]):
        intent = RetrievalIntent.EXPLAIN_CONCEPT
    elif any(w in lower for w in ["practice", "quiz", "test", "problem", "exercise"]):
        intent = RetrievalIntent.GENERATE_PROBLEM
    elif any(w in lower for w in ["wrong", "mistake", "confused", "don't understand"]):
        intent = RetrievalIntent.DIAGNOSE_MISCONCEPTION

    # Find focus concepts by searching tags/content.
    # For now, use all course concepts as potential focus.
    # A more sophisticated version would use embedding similarity.
    course_hash = state.ws.get_ref_hash("course/structure")
    focus = []
    if course_hash:
        all_concepts = state.ws.collect_atoms(course_hash, "ConceptDefinition")
        for ch, atom in all_concepts:
            # Simple keyword matching.
            if any(
                word in atom.text.lower()
                for word in user_input.lower().split()
                if len(word) > 3
            ):
                focus.append(ch)

    query = RetrievalQuery(
        focus_concepts=focus,
        intent=intent,
        student_model=state.student_model,
        max_results=state.config.max_context_results,
        text_query=user_input,
    )

    try:
        results = retrieve(query, state.ws)
    except Exception as e:
        display.warn(f"Retrieval error: {e}")
        results = []

    if not results:
        return "", []

    # Format context.
    context_parts = []

    # Mastery summary.
    if state.student_model:
        mastery = state.ws.student_mastery_map(state.student_model)
        if mastery:
            mastery_lines = []
            for ch, level in sorted(mastery, key=lambda x: x[1]):
                atom = state.ws.get_atom(ch)
                name = atom.text[:50] if atom else ch.short()
                mastery_lines.append(f"  - {name}: {level:.0%}")
            context_parts.append("Student mastery:\n" + "\n".join(mastery_lines))

    # Retrieved content.
    content_parts = []
    for candidate in results[: state.config.max_context_results]:
        try:
            atom = state.ws.get_atom(candidate.hash)
        except TypeError:
            atom = None
        if atom:
            content_parts.append(f"[{atom.kind}] {atom.text}")
        else:
            try:
                frame = state.ws.get_frame(candidate.hash)
            except TypeError:
                frame = None
            if frame and frame.label:
                content_parts.append(f"[{frame.kind}: {frame.label}]")

    if content_parts:
        context_parts.append("Relevant materials:\n" + "\n---\n".join(content_parts))

    return "\n\n".join(context_parts), results


def _call_model(state: SessionState, system: str) -> str:
    """Call the model API and return the response text."""
    if not state.config.api_key:
        return (
            "_No API key configured. Set OPENROUTER_API_KEY or pass --api-key. "
            "Running in offline mode — I'll echo your input back._\n\n"
            f"> {state.messages[-1]['content']}"
        )

    try:
        response = httpx.post(
            f"{state.config.api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {state.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": state.config.model,
                "messages": [
                    {"role": "system", "content": system},
                    *state.messages,
                ],
                "max_tokens": 2048,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    except httpx.HTTPStatusError as e:
        return f"_API error: {e.response.status_code} {e.response.text[:200]}_"
    except httpx.RequestError as e:
        return f"_Request failed: {e}_"
    except (KeyError, IndexError) as e:
        return f"_Unexpected API response format: {e}_"
