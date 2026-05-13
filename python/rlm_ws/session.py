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

Model calls use the Responses API for direct OpenAI requests and
chat-completions for OpenAI-compatible providers such as OpenRouter.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

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
from .providers import ModelRequest, adapter_for


@dataclass
class SessionConfig:
    """Configuration for a tutoring session."""

    student_id: str = "default"
    provider: str = "openai"
    model: str = "gpt-5.4-mini"
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    max_context_results: int = 10
    max_call_depth: int = 1
    system_prompt: str = ""
    ws_dir: Path | None = None  # set by CLI; used to load workspace.toml


FALLBACK_SYSTEM_PROMPT = """You are a patient, knowledgeable tutor. Your role is to help the student understand concepts deeply, not just memorize facts.

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


@dataclass(frozen=True)
class RetrievalRecord:
    """Retrieval output plus the query that produced it."""

    query: RetrievalQuery
    context_text: str
    results: list[ScoredCandidate]


@dataclass(frozen=True)
class EngineCommand:
    """A typed command emitted by the model for the session engine."""

    kind: str
    arguments: dict[str, Any]
    source_response_id: str | None = None


@dataclass(frozen=True)
class ParsedModelOutput:
    """Visible tutor text plus machine-readable engine commands."""

    visible_text: str
    commands: list[EngineCommand] = field(default_factory=list)
    raw_text: str = ""


@dataclass(frozen=True)
class SubcallResult:
    """A completed child model call."""

    event_hash: Hash
    output_hash: Hash
    visible_text: str


@dataclass(frozen=True)
class ContinuationResult:
    """A parent continuation after child calls complete."""

    event_hash: Hash
    output_hash: Hash
    parsed: ParsedModelOutput


@dataclass(frozen=True)
class SessionTraceRow:
    """Compact display data for a persisted session event."""

    index: int
    hash: Hash
    kind: str
    depth: int | None
    model: str
    input_roles: tuple[str, ...]
    output_roles: tuple[str, ...]
    parent_count: int


COMMAND_PROTOCOL = """\
## Engine Command Protocol

You may emit engine commands only when the engine should take an action.
Keep student-facing prose separate from machine-readable commands. Supported
commands are:
- mastery_update: update the student's mastery for a concept hash.
- subcall: request a scoped child call for a focused explanation or check.

If you need a command, include a final JSON block like:

```json
{
  "visible_text": "Short response shown to the student.",
  "commands": [
    {
      "kind": "mastery_update",
      "arguments": {
        "concept": "<concept hash>",
        "level": 0.73,
        "reason": "evidence from this turn"
      }
    },
    {
      "kind": "subcall",
      "arguments": {
        "intent": "explain_concept",
        "concepts": ["<concept hash>"],
        "prompt": "Explain the invariant briefly."
      }
    }
  ]
}
```
"""


def start_session(ws: Workspace, config: SessionConfig) -> SessionState:
    """Start a new tutoring session."""
    # Load system prompt from workspace.toml if not explicitly provided.
    if not config.system_prompt and config.ws_dir:
        from .templates import load_workspace_config

        ws_config = load_workspace_config(config.ws_dir)
        saved_prompt = ws_config.get("system_prompt", {}).get("content", "")
        if saved_prompt.strip():
            config.system_prompt = saved_prompt
            display.info("Loaded system prompt from workspace.toml")

    if not config.system_prompt:
        config.system_prompt = FALLBACK_SYSTEM_PROMPT

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


def _update_current_session_ref(state: SessionState) -> None:
    if state.last_event is None:
        return
    state.ws.set_ref(
        f"student/{state.config.student_id}/session/current",
        state.last_event,
    )


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

    # 2. Retrieve context and persist retrieval provenance.
    retrieval = _retrieve(state, user_input)
    retrieval_event = _write_retrieval_event(
        state,
        input_event,
        input_atom,
        retrieval,
    )

    # 3. Build a first-class call context frame before invoking the model.
    context_frame = _build_call_context(
        state,
        input_atom,
        retrieval_event,
        retrieval,
    )
    state.last_event = retrieval_event

    # 4. Build messages.
    system = state.config.system_prompt
    if retrieval.context_text:
        system += f"\n\n## Relevant Context\n\n{retrieval.context_text}"
    system += f"\n\n{COMMAND_PROTOCOL}"

    state.messages.append({"role": "user", "content": user_input})

    # 5. Call model.
    t0 = time.monotonic()
    raw_response = _call_model(state, system)
    latency_ms = int((time.monotonic() - t0) * 1000)
    parsed = _parse_model_output(raw_response)
    response_text = parsed.visible_text

    # 6. Execute bounded child calls requested by the model.
    child_results = _execute_subcalls(
        state,
        parsed.commands,
        parent_event=retrieval_event,
        depth=1,
    )

    # 7. Record model output + event.
    output_structured = None
    if parsed.commands or parsed.raw_text != parsed.visible_text or child_results:
        output_structured = {
            "commands": [_command_to_dict(c) for c in parsed.commands],
            "raw_text": parsed.raw_text,
            "child_calls": [
                {
                    "event": c.event_hash.to_hex(),
                    "output": c.output_hash.to_hex(),
                }
                for c in child_results
            ],
        }
    output_atom = state.ws.put_atom(
        Atom(
            "ModelOutput",
            response_text,
            tags=["model-output"],
            structured=output_structured,
        )
    )

    call_event = state.ws.put_event(
        Event(
            "ModelCall",
            parents=[retrieval_event],
            inputs=[
                EventRef(context_frame, "call_context"),
                EventRef(input_atom, "student_message"),
                EventRef(retrieval_event, "retrieval_event"),
            ],
            outputs=[EventRef(output_atom, "model_output")]
            + [EventRef(c.event_hash, "child_call") for c in child_results],
            trace=CallTrace(
                call_depth=0,
                model=state.config.model,
                latency_ms=latency_ms,
            ),
        )
    )

    continuation = None
    if child_results:
        continuation = _continue_parent_call(
            state,
            system,
            parsed,
            child_results,
            parent_call_event=call_event,
            parent_output=output_atom,
            context_frame=context_frame,
        )
        response_text = continuation.parsed.visible_text

    # 8. Apply supported state mutations requested through typed commands.
    commands_to_apply = list(parsed.commands)
    if continuation:
        commands_to_apply.extend(continuation.parsed.commands)
    mutation_events = _apply_engine_commands(
        state,
        commands_to_apply,
        parent_event=continuation.event_hash if continuation else call_event,
        model_output=continuation.output_hash if continuation else output_atom,
    )
    terminal_event = continuation.event_hash if continuation else call_event
    state.last_event = mutation_events[-1] if mutation_events else terminal_event
    _update_current_session_ref(state)

    state.messages.append({"role": "assistant", "content": response_text})

    return response_text


def session_trace_rows(
    ws: Workspace,
    session_tip: Hash,
) -> list[SessionTraceRow]:
    """Return a chronological summary of session events plus child calls."""
    events: list[tuple[Hash, Event]] = []
    visited: set[Hash] = set()

    def collect(event_hash: Hash) -> None:
        if event_hash in visited:
            return
        event = ws.get_event(event_hash)
        if event is None:
            return
        visited.add(event_hash)

        for parent_hash in event.parents:
            collect(parent_hash)

        events.append((event_hash, event))

        for output_ref in event.outputs:
            if output_ref.role == "child_call":
                collect(output_ref.hash)

    collect(session_tip)

    rows = []
    for index, (event_hash, event) in enumerate(events, start=1):
        depth = event.trace.call_depth if event.kind == "ModelCall" else None
        rows.append(
            SessionTraceRow(
                index=index,
                hash=event_hash,
                kind=event.kind,
                depth=depth,
                model=event.trace.model or "",
                input_roles=tuple(ref.role for ref in event.inputs),
                output_roles=tuple(ref.role for ref in event.outputs),
                parent_count=len(event.parents),
            )
        )
    return rows


SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "show available commands"),
    ("/mastery", "show current mastery levels"),
    ("/model", "show or change the current model"),
    ("/tree", "show course structure"),
    ("/status", "session and workspace stats"),
    ("/quit", "end the session (or press ^D)"),
]


def run_interactive(ws: Workspace, config: SessionConfig) -> None:
    """Run an interactive tutoring session in the terminal."""
    state = start_session(ws, config)

    course_name = ""
    if config.ws_dir:
        from .templates import load_workspace_config

        ws_config = load_workspace_config(config.ws_dir)
        course_name = (
            ws_config.get("answers", {}).get("course_name", "")
            or ws_config.get("workspace", {}).get("name", "")
            or config.ws_dir.name
        )

    display.welcome_banner(
        course=course_name,
        student=config.student_id,
        model=f"{config.provider} / {config.model}",
        extra_lines=("/help for commands  ·  ^D or /quit to exit",),
    )

    try:
        while True:
            try:
                user_input = display.student_input_prompt(commands=SLASH_COMMANDS)
            except (EOFError, KeyboardInterrupt):
                display.console.print()
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            cmd = stripped.lower()

            if cmd in ("/quit", "/exit", "quit", "exit"):
                break

            if cmd in ("/help", "/?", "help"):
                display.slash_help(SLASH_COMMANDS)
                continue

            if cmd == "/mastery":
                if state.student_model:
                    mastery = ws.student_mastery_map(state.student_model)
                    display.mastery_display(mastery, ws)
                else:
                    display.warn("No student model loaded")
                continue

            if cmd == "/model" or cmd.startswith("/model "):
                _handle_model_command(state, stripped)
                continue

            if cmd == "/tree":
                course_hash = ws.get_ref_hash("course/structure")
                if course_hash:
                    display.course_tree(ws, course_hash)
                else:
                    display.warn("No course structure found")
                continue

            if cmd == "/status":
                atoms, frames, events = ws.object_counts()
                display.object_counts_display(atoms, frames, events)
                display.info(f"turn      {state.turn_count}")
                display.info(f"student   {config.student_id}")
                display.info(f"provider  {config.provider}")
                display.info(f"model     {config.model}")
                continue

            if cmd.startswith("/"):
                display.warn(
                    f"Unknown command: {stripped.split()[0]}. "
                    "Type /help to see what's available."
                )
                continue

            with display.thinking():
                response = run_turn(state, stripped)

            display.prof_says(response)

    finally:
        end_session(state)


def _handle_model_command(state: SessionState, raw_command: str) -> None:
    models = _provider_models(state.config.provider)
    argument = _slash_argument(raw_command)
    if argument is not None:
        selected = _resolve_model_selection(argument, models)
        if selected is None:
            display.warn(f"Unknown model choice: {argument}")
            return
        _set_session_model(state, selected)
        return

    display.model_choices(state.config.provider, state.config.model, models)
    try:
        selected = _resolve_model_selection(
            display.text_prompt("model", default=state.config.model),
            models,
        )
    except (EOFError, KeyboardInterrupt):
        display.console.print()
        display.info("model unchanged")
        return
    if selected is None:
        display.info("model unchanged")
        return
    _set_session_model(state, selected)


def _slash_argument(raw_command: str) -> str | None:
    parts = raw_command.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    value = parts[1].strip()
    return value or None


def _provider_models(provider: str) -> list[str]:
    from .auth import PROVIDERS

    raw_models = PROVIDERS.get(provider, {}).get("models", [])
    return [model for model in raw_models if isinstance(model, str)]


def _resolve_model_selection(
    value: str,
    models: list[str],
) -> str | None:
    model = value.strip()
    if not model:
        return None
    if model.isdecimal():
        index = int(model) - 1
        if 0 <= index < len(models):
            return models[index]
        return None
    return model


def _set_session_model(state: SessionState, model: str) -> None:
    selected = model.strip()
    if not selected:
        display.warn("Model cannot be empty")
        return
    previous = state.config.model
    if selected == previous:
        display.info("model unchanged")
        return
    state.config.model = selected
    display.success(f"Model set to {selected}")
    display.hint(f"was {previous}; applies to subsequent model calls")


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


def _retrieve(
    state: SessionState,
    user_input: str,
) -> RetrievalRecord:
    """Run retrieval and return both prompt context and provenance data."""
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

    return _run_retrieval(state, query)


def _run_retrieval(state: SessionState, query: RetrievalQuery) -> RetrievalRecord:
    """Execute a retrieval query and format context."""

    try:
        results = retrieve(query, state.ws)
    except Exception as e:
        display.warn(f"Retrieval error: {e}")
        results = []

    if not results:
        return RetrievalRecord(query=query, context_text="", results=[])

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
                mastery_lines.append(f"  - {ch.short()} {name}: {level:.0%}")
            context_parts.append("Student mastery:\n" + "\n".join(mastery_lines))

    # Retrieved content.
    content_parts = []
    for candidate in results[: state.config.max_context_results]:
        try:
            atom = state.ws.get_atom(candidate.hash)
        except TypeError:
            atom = None
        if atom:
            content_parts.append(
                f"[{atom.kind} {candidate.hash.to_hex()}] {atom.text}"
            )
        else:
            try:
                frame = state.ws.get_frame(candidate.hash)
            except TypeError:
                frame = None
            if frame and frame.label:
                content_parts.append(
                    f"[{frame.kind} {candidate.hash.to_hex()}: {frame.label}]"
                )

    if content_parts:
        context_parts.append("Relevant materials:\n" + "\n---\n".join(content_parts))

    return RetrievalRecord(
        query=query,
        context_text="\n\n".join(context_parts),
        results=results,
    )


def _retrieve_context(
    state: SessionState,
    user_input: str,
) -> tuple[str, list[ScoredCandidate]]:
    """Run retrieval and format context for the model prompt."""
    record = _retrieve(state, user_input)
    return record.context_text, record.results


def _write_retrieval_event(
    state: SessionState,
    parent_event: Hash,
    input_atom: Hash,
    retrieval: RetrievalRecord,
    input_role: str = "student_message",
) -> Hash:
    """Persist a RetrievalPerformed event with rebuildable query metadata."""
    query_atom = state.ws.put_atom(
        Atom(
            "Config",
            f"retrieval query for turn {state.turn_count}",
            tags=["retrieval-query"],
            structured={
                "intent": retrieval.query.intent.value,
                "text_query": retrieval.query.text_query,
                "focus_concepts": [h.to_hex() for h in retrieval.query.focus_concepts],
                "target_kinds": retrieval.query.target_kinds,
                "student_model": (
                    retrieval.query.student_model.to_hex()
                    if retrieval.query.student_model
                    else None
                ),
                "max_results": retrieval.query.max_results,
                "results": [
                    {
                        "hash": c.hash.to_hex(),
                        "score": c.score,
                        "source_strategy": c.source_strategy,
                        "explanation": c.explanation,
                    }
                    for c in retrieval.results
                ],
            },
        )
    )

    inputs = [EventRef(input_atom, input_role)]
    if state.student_model:
        inputs.append(EventRef(state.student_model, "student_model"))

    return state.ws.put_event(
        Event(
            "RetrievalPerformed",
            parents=[parent_event],
            inputs=inputs,
            outputs=[EventRef(query_atom, "retrieval_query")]
            + [EventRef(c.hash, "retrieved") for c in retrieval.results],
            tags=["retrieval"],
        )
    )


def _build_call_context(
    state: SessionState,
    input_atom: Hash,
    retrieval_event: Hash,
    retrieval: RetrievalRecord,
    input_role: str = "student_message",
    label: str | None = None,
) -> Hash:
    """Build a first-class CallContext frame for model-call provenance."""
    edges = [
        Edge("ReceivedInput", input_atom, annotation={"role": input_role}),
        Edge("UsedScope", retrieval_event, annotation={"role": "retrieval_event"}),
    ]

    if state.student_model:
        edges.append(
            Edge(
                "InScope",
                state.student_model,
                annotation={"role": "student_model"},
            )
        )
    if state.last_event:
        edges.append(
            Edge(
                "InScope",
                state.last_event,
                annotation={"role": "prior_session_event"},
            )
        )

    for rank, candidate in enumerate(
        retrieval.results[: state.config.max_context_results]
    ):
        edges.append(
            Edge(
                "InScope",
                candidate.hash,
                weight=candidate.score,
                annotation={
                    "rank": rank,
                    "source_strategy": candidate.source_strategy,
                    "explanation": candidate.explanation,
                },
            )
        )

    return state.ws.put_frame(
        Frame(
            "CallContext",
            edges,
            tags=["call-context"],
            label=label or f"turn-{state.turn_count}",
        )
    )


def _parse_model_output(raw: str | dict[str, Any]) -> ParsedModelOutput:
    """Parse visible text and typed engine commands from model output."""
    if isinstance(raw, dict):
        return _parse_responses_payload(raw)

    raw_text = raw
    parsed = _extract_json_command_payload(raw_text)
    if parsed is None:
        return ParsedModelOutput(visible_text=raw_text, raw_text=raw_text)

    payload, payload_span = parsed
    commands = _commands_from_payload(payload)
    visible_text = ""
    if isinstance(payload, dict):
        visible_text = str(
            payload.get("visible_text") or payload.get("response") or ""
        ).strip()

    if not visible_text:
        visible_text = (
            raw_text[: payload_span[0]] + raw_text[payload_span[1] :]
        ).strip()

    if not visible_text:
        visible_text = raw_text.strip()

    return ParsedModelOutput(
        visible_text=visible_text,
        commands=commands,
        raw_text=raw_text,
    )


def _extract_json_command_payload(
    raw_text: str,
) -> tuple[Any, tuple[int, int]] | None:
    """Find and parse the first JSON object/list command payload."""
    block_match = re.search(
        r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
        raw_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if block_match:
        try:
            return json.loads(block_match.group(1)), block_match.span()
        except json.JSONDecodeError:
            return None

    stripped = raw_text.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped), (0, len(raw_text))
        except json.JSONDecodeError:
            return None

    return None


def _parse_responses_payload(data: dict[str, Any]) -> ParsedModelOutput:
    """Parse text and function-call-shaped items from a Responses payload."""
    commands: list[EngineCommand] = []
    response_id = data.get("id") if isinstance(data.get("id"), str) else None

    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") not in {"function_call", "tool_call"}:
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        arguments = _coerce_command_arguments(item.get("arguments"))
        commands.append(
            EngineCommand(
                kind=name,
                arguments=arguments,
                source_response_id=response_id,
            )
        )

    visible_text = _extract_responses_text(data)
    if not visible_text and not commands:
        visible_text = "_Unexpected API response format: no text output found_"
    return ParsedModelOutput(
        visible_text=visible_text,
        commands=[c for c in commands if _is_supported_command(c.kind)],
        raw_text=visible_text,
    )


def _commands_from_payload(payload: Any) -> list[EngineCommand]:
    """Normalize strict JSON payloads into EngineCommand objects."""
    command_items: list[Any]
    if isinstance(payload, dict) and isinstance(payload.get("commands"), list):
        command_items = payload["commands"]
    elif isinstance(payload, dict) and ("kind" in payload or "name" in payload):
        command_items = [payload]
    elif isinstance(payload, list):
        command_items = payload
    else:
        return []

    commands: list[EngineCommand] = []
    for item in command_items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") or item.get("name")
        if not isinstance(kind, str):
            continue
        arguments = _coerce_command_arguments(item.get("arguments", {}))
        if _is_supported_command(kind):
            commands.append(EngineCommand(kind=kind, arguments=arguments))
    return commands


def _is_supported_command(kind: str) -> bool:
    return kind in {"mastery_update", "subcall"}


def _coerce_command_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _command_to_dict(command: EngineCommand) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": command.kind,
        "arguments": command.arguments,
    }
    if command.source_response_id:
        data["source_response_id"] = command.source_response_id
    return data


def _execute_subcalls(
    state: SessionState,
    commands: list[EngineCommand],
    parent_event: Hash,
    depth: int,
) -> list[SubcallResult]:
    """Execute bounded recursive subcall commands."""
    if depth > state.config.max_call_depth:
        return []

    results: list[SubcallResult] = []
    for command in commands:
        if command.kind != "subcall":
            continue
        result = _execute_subcall(
            state,
            command,
            parent_event=parent_event,
            depth=depth,
        )
        if result:
            results.append(result)
    return results


def _execute_subcall(
    state: SessionState,
    command: EngineCommand,
    parent_event: Hash,
    depth: int,
) -> SubcallResult | None:
    """Execute a single child model call and record its event."""
    prompt = _subcall_prompt(command)
    if not prompt:
        return None

    request_atom = state.ws.put_atom(
        Atom(
            "Config",
            f"subcall request depth {depth}",
            tags=["subcall-request"],
            structured=command.arguments,
        )
    )

    retrieval = _run_retrieval(state, _subcall_query(state, command))
    retrieval_event = _write_retrieval_event(
        state,
        parent_event,
        request_atom,
        retrieval,
        input_role="subcall_request",
    )
    context_frame = _build_call_context(
        state,
        request_atom,
        retrieval_event,
        retrieval,
        input_role="subcall_request",
        label=f"turn-{state.turn_count}-subcall-{depth}",
    )

    system = state.config.system_prompt
    if retrieval.context_text:
        system += f"\n\n## Relevant Context\n\n{retrieval.context_text}"
    if depth < state.config.max_call_depth:
        system += f"\n\n{COMMAND_PROTOCOL}"

    model = _subcall_model(state, command, depth)
    sub_state = SessionState(
        ws=state.ws,
        config=replace(state.config, model=model),
        session_event=state.session_event,
        last_event=retrieval_event,
        student_model=state.student_model,
        messages=[{"role": "user", "content": prompt}],
        turn_count=state.turn_count,
    )

    t0 = time.monotonic()
    raw_response = _call_model(sub_state, system)
    latency_ms = int((time.monotonic() - t0) * 1000)
    parsed = _parse_model_output(raw_response)

    nested_results = _execute_subcalls(
        state,
        parsed.commands,
        parent_event=retrieval_event,
        depth=depth + 1,
    )

    output_structured = None
    if parsed.commands or parsed.raw_text != parsed.visible_text or nested_results:
        output_structured = {
            "commands": [_command_to_dict(c) for c in parsed.commands],
            "raw_text": parsed.raw_text,
            "child_calls": [
                {
                    "event": c.event_hash.to_hex(),
                    "output": c.output_hash.to_hex(),
                }
                for c in nested_results
            ],
        }

    output_atom = state.ws.put_atom(
        Atom(
            "ModelOutput",
            parsed.visible_text,
            tags=["model-output", "subcall-output"],
            structured=output_structured,
        )
    )

    call_event = state.ws.put_event(
        Event(
            "ModelCall",
            parents=[retrieval_event],
            inputs=[
                EventRef(context_frame, "call_context"),
                EventRef(request_atom, "subcall_request"),
                EventRef(retrieval_event, "retrieval_event"),
            ],
            outputs=[EventRef(output_atom, "model_output")]
            + [EventRef(c.event_hash, "child_call") for c in nested_results],
            trace=CallTrace(
                call_depth=depth,
                model=model,
                latency_ms=latency_ms,
            ),
        )
    )

    return SubcallResult(
        event_hash=call_event,
        output_hash=output_atom,
        visible_text=parsed.visible_text,
    )


def _subcall_prompt(command: EngineCommand) -> str:
    for key in ("prompt", "question", "text_query", "task"):
        value = command.arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _subcall_query(state: SessionState, command: EngineCommand) -> RetrievalQuery:
    concepts = _command_concept_hashes(command)
    text_query = _subcall_prompt(command)
    intent = _command_intent(command)
    return RetrievalQuery(
        focus_concepts=concepts,
        intent=intent,
        student_model=state.student_model,
        max_results=state.config.max_context_results,
        text_query=text_query,
    )


def _command_concept_hashes(command: EngineCommand) -> list[Hash]:
    raw_values: list[Any] = []
    concepts = command.arguments.get("concepts")
    if isinstance(concepts, list):
        raw_values.extend(concepts)
    concept = command.arguments.get("concept") or command.arguments.get("concept_hash")
    if concept:
        raw_values.append(concept)

    hashes: list[Hash] = []
    for raw in raw_values:
        if not isinstance(raw, str):
            continue
        try:
            hashes.append(Hash.from_hex(raw))
        except Exception:
            continue
    return hashes


def _command_intent(command: EngineCommand) -> RetrievalIntent:
    raw = command.arguments.get("intent")
    if isinstance(raw, str):
        try:
            return RetrievalIntent(raw)
        except ValueError:
            pass
    return RetrievalIntent.GENERAL


def _subcall_model(state: SessionState, command: EngineCommand, depth: int) -> str:
    model = command.arguments.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    child_defaults = {
        "gpt-5.4-mini": "gpt-5.4-nano",
        "openai/gpt-5.4-mini": "openai/gpt-5.4-nano",
    }
    if depth > 0 and state.config.model in child_defaults:
        return child_defaults[state.config.model]
    return state.config.model


def _continue_parent_call(
    state: SessionState,
    system: str,
    parent_parsed: ParsedModelOutput,
    child_results: list[SubcallResult],
    parent_call_event: Hash,
    parent_output: Hash,
    context_frame: Hash,
) -> ContinuationResult:
    """Feed child outputs back into the parent and record the final answer call."""
    continuation_prompt = _child_results_prompt(parent_parsed.visible_text, child_results)
    continuation_messages = [
        *state.messages,
        {"role": "assistant", "content": parent_parsed.visible_text},
        {"role": "user", "content": continuation_prompt},
    ]
    continuation_state = SessionState(
        ws=state.ws,
        config=state.config,
        session_event=state.session_event,
        last_event=parent_call_event,
        student_model=state.student_model,
        messages=continuation_messages,
        turn_count=state.turn_count,
    )

    t0 = time.monotonic()
    raw_response = _call_model(continuation_state, system)
    latency_ms = int((time.monotonic() - t0) * 1000)
    parsed = _parse_model_output(raw_response)

    output_structured = None
    if parsed.commands or parsed.raw_text != parsed.visible_text:
        output_structured = {
            "commands": [_command_to_dict(c) for c in parsed.commands],
            "raw_text": parsed.raw_text,
            "parent_call": parent_call_event.to_hex(),
            "child_calls": [
                {
                    "event": c.event_hash.to_hex(),
                    "output": c.output_hash.to_hex(),
                }
                for c in child_results
            ],
        }

    output_atom = state.ws.put_atom(
        Atom(
            "ModelOutput",
            parsed.visible_text,
            tags=["model-output", "continuation-output"],
            structured=output_structured,
        )
    )

    call_event = state.ws.put_event(
        Event(
            "ModelCall",
            parents=[parent_call_event],
            inputs=[
                EventRef(context_frame, "call_context"),
                EventRef(parent_output, "parent_draft"),
            ]
            + [EventRef(c.output_hash, "child_output") for c in child_results],
            outputs=[EventRef(output_atom, "model_output")],
            trace=CallTrace(
                call_depth=0,
                model=state.config.model,
                latency_ms=latency_ms,
                parent_call=parent_call_event,
            ),
        )
    )

    return ContinuationResult(
        event_hash=call_event,
        output_hash=output_atom,
        parsed=parsed,
    )


def _child_results_prompt(
    parent_text: str,
    child_results: list[SubcallResult],
) -> str:
    child_sections = []
    for idx, result in enumerate(child_results, 1):
        child_sections.append(
            "\n".join(
                [
                    f"Child call {idx}:",
                    f"event={result.event_hash.to_hex()}",
                    f"output={result.output_hash.to_hex()}",
                    result.visible_text,
                ]
            )
        )
    return (
        "Use the completed child call outputs to compose the final response for "
        "the student. Do not mention internal call mechanics unless it is "
        "pedagogically useful.\n\n"
        f"Parent draft:\n{parent_text}\n\n"
        "Child outputs:\n"
        + "\n\n".join(child_sections)
    )


def _apply_engine_commands(
    state: SessionState,
    commands: list[EngineCommand],
    parent_event: Hash,
    model_output: Hash,
) -> list[Hash]:
    """Apply supported model commands and return mutation event hashes."""
    mutation_events: list[Hash] = []
    current_parent = parent_event
    for command in commands:
        if command.kind != "mastery_update":
            continue
        event_hash = _apply_mastery_update(
            state,
            command,
            parent_event=current_parent,
            model_output=model_output,
        )
        if event_hash:
            mutation_events.append(event_hash)
            current_parent = event_hash
    return mutation_events


def _apply_mastery_update(
    state: SessionState,
    command: EngineCommand,
    parent_event: Hash,
    model_output: Hash,
) -> Hash | None:
    """Apply a single CAS-backed mastery update command."""
    if state.student_model is None:
        return None

    concept_hash = _command_concept_hash(command)
    level = _command_mastery_level(command)
    if concept_hash is None or level is None:
        return None

    old_model_hash = state.student_model
    old_model = state.ws.get_frame(old_model_hash)
    if old_model is None:
        return None

    reason = str(command.arguments.get("reason") or "").strip()
    updated_edges = []
    replaced = False
    for edge in old_model.edges:
        if edge.label == "MasteryEstimate" and edge.target == concept_hash:
            updated_edges.append(
                Edge(
                    "MasteryEstimate",
                    concept_hash,
                    weight=level,
                    annotation={"reason": reason} if reason else None,
                )
            )
            replaced = True
        else:
            updated_edges.append(
                Edge(
                    edge.label,
                    edge.target,
                    weight=edge.weight,
                    annotation=edge.annotation,
                )
            )

    if not replaced:
        updated_edges.append(
            Edge(
                "MasteryEstimate",
                concept_hash,
                weight=level,
                annotation={"reason": reason} if reason else None,
            )
        )

    updated_edges.append(
        Edge(
            "InteractionRecord",
            parent_event,
            annotation={"source": "mastery_update"},
        )
    )

    new_model_hash = state.ws.put_frame(
        Frame(
            "StudentModel",
            updated_edges,
            tags=old_model.tags,
            label=old_model.label,
        )
    )

    event = Event(
        "StudentModelUpdate",
        parents=[parent_event],
        inputs=[
            EventRef(old_model_hash, "prior"),
            EventRef(model_output, "model_output"),
            EventRef(concept_hash, "concept"),
        ],
        outputs=[EventRef(new_model_hash, "updated")],
        tags=["mastery"],
    )
    mastery_ref = f"student/{state.config.student_id}/mastery"

    try:
        event_hash = state.ws.commit_mutation(
            event,
            [(mastery_ref, old_model_hash, new_model_hash)],
        )
    except ValueError as exc:
        display.warn(f"Mastery update skipped: {exc}")
        return None

    state.student_model = new_model_hash
    return event_hash


def _command_concept_hash(command: EngineCommand) -> Hash | None:
    raw = command.arguments.get("concept") or command.arguments.get("concept_hash")
    if not isinstance(raw, str):
        return None
    try:
        return Hash.from_hex(raw)
    except Exception:
        return None


def _command_mastery_level(command: EngineCommand) -> float | None:
    raw = command.arguments.get("level")
    if raw is None:
        raw = command.arguments.get("mastery")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, value))


def _call_model(state: SessionState, system: str) -> str | dict[str, Any]:
    """Call the configured model provider and return the raw response payload."""
    request = ModelRequest(
        provider=state.config.provider,
        model=state.config.model,
        api_base=state.config.api_base,
        api_key=state.config.api_key,
        system=system,
        messages=list(state.messages),
    )
    adapter = adapter_for(
        state.config.provider,
        state.config.api_base,
        state.config.api_key,
    )
    return adapter.call(request)


def _extract_responses_text(data: dict) -> str:
    """Extract text from a Responses API response object."""
    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    chunks: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "".join(chunks)
