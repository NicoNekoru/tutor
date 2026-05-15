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
    extra_headers: dict[str, str] = field(default_factory=dict)
    max_context_results: int = 10
    max_call_depth: int = 1
    max_subcalls_per_turn: int = 3
    mastery_judgment: str = "model"
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
    subcalls_used: int = 0


@dataclass(frozen=True)
class RetrievalRecord:
    """Retrieval output plus the query that produced it."""

    query: RetrievalQuery
    context_text: str
    results: list[ScoredCandidate]


@dataclass(frozen=True)
class TurnEvidenceRecord:
    """Persisted evidence used for turn-level mastery updates."""

    atom_hash: Hash
    event_hash: Hash
    concept_scores: dict[Hash, float]
    signal: str
    base_delta: float


@dataclass(frozen=True)
class MasteryJudgmentResult:
    """Result of an optional model-judged mastery pass."""

    commands: list[EngineCommand] = field(default_factory=list)
    event_hash: Hash | None = None
    output_hash: Hash | None = None
    attempted: bool = False
    usable: bool = False


@dataclass(frozen=True)
class EngineCommand:
    """A typed command emitted by the model for the session engine."""

    kind: str
    arguments: dict[str, Any]
    source_response_id: str | None = None


@dataclass(frozen=True)
class CommandError:
    """Validation error for a model-emitted command."""

    kind: str | None
    message: str
    item: Any
    source_response_id: str | None = None


@dataclass(frozen=True)
class ParsedModelOutput:
    """Visible tutor text plus machine-readable engine commands."""

    visible_text: str
    commands: list[EngineCommand] = field(default_factory=list)
    command_errors: list[CommandError] = field(default_factory=list)
    raw_text: str = ""


@dataclass(frozen=True)
class SubcallResult:
    """A completed child model call."""

    event_hash: Hash
    output_hash: Hash
    visible_text: str


@dataclass(frozen=True)
class EngineNotice:
    """A persisted non-fatal engine notice."""

    event_hash: Hash
    atom_hash: Hash
    kind: str
    message: str


@dataclass(frozen=True)
class SubcallBatch:
    """Result of executing subcall commands."""

    child_results: list[SubcallResult] = field(default_factory=list)
    notices: list[EngineNotice] = field(default_factory=list)


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


@dataclass(frozen=True)
class MasteryJudgmentTraceRow:
    """Human-readable mastery judgment evidence from a session trace."""

    index: int
    event_hash: Hash
    turn: int | None
    model: str
    concept_hash: Hash | None
    concept_name: str
    current_level: float | None
    judged_level: float | None
    bounded_level: float | None
    delta: float | None
    confidence: float | None
    status: str
    evidence: str
    fallback: bool
    errors: tuple[str, ...]


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


MASTERY_JUDGMENT_PROTOCOL = """\
## Mastery Judgment Protocol

You are judging student mastery after one tutoring turn. Use the course-specific
context, the student's message, the tutor response, and current mastery values.
Return only strict JSON with this shape:

{
  "judgments": [
    {
      "concept": "<candidate concept hash>",
      "level": 0.0,
      "confidence": 0.0,
      "evidence": "short behavioral evidence from this turn",
      "reason": "short reason for the estimate"
    }
  ]
}

Rules:
- Judge only concepts listed in candidate_concepts.
- Use level as the absolute mastery estimate after this turn.
- Prefer an empty judgments list when evidence is weak.
- Do not infer strong mastery from the student merely asking for an explanation.
- Keep evidence and reason concise.
"""

MASTERY_JUDGMENT_MODES = {"heuristic", "model"}
MIN_MASTERY_JUDGMENT_CONFIDENCE = 0.35
MAX_MASTERY_JUDGMENT_INCREASE = 0.08
MAX_MASTERY_JUDGMENT_DECREASE = 0.10


def start_session(ws: Workspace, config: SessionConfig) -> SessionState:
    """Start a new tutoring session."""
    judgment_mode = _resolve_mastery_judgment_mode(config.mastery_judgment)
    if judgment_mode is None:
        display.warn(
            f"Unknown mastery judgment mode '{config.mastery_judgment}', using model"
        )
        judgment_mode = "model"
    config.mastery_judgment = judgment_mode

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
    state.subcalls_used = 0

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
    command_notices = _write_command_error_notices(
        state,
        retrieval_event,
        parsed.command_errors,
    )

    # 6. Execute bounded child calls requested by the model.
    subcall_batch = _execute_subcalls(
        state,
        parsed.commands,
        parent_event=retrieval_event,
        depth=1,
    )
    child_results = subcall_batch.child_results

    # 7. Record model output + event.
    output_structured = None
    engine_notices = command_notices + subcall_batch.notices
    if (
        parsed.commands
        or parsed.command_errors
        or parsed.raw_text != parsed.visible_text
        or child_results
        or engine_notices
    ):
        output_structured = {
            "commands": [_command_to_dict(c) for c in parsed.commands],
            "command_errors": [_command_error_to_dict(e) for e in parsed.command_errors],
            "raw_text": parsed.raw_text,
            "child_calls": [
                {
                    "event": c.event_hash.to_hex(),
                    "output": c.output_hash.to_hex(),
                }
                for c in child_results
            ],
            "engine_notices": [
                {
                    "event": n.event_hash.to_hex(),
                    "kind": n.kind,
                    "message": n.message,
                }
                for n in engine_notices
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
            + [EventRef(c.event_hash, "child_call") for c in child_results]
            + [EventRef(n.event_hash, "engine_notice") for n in engine_notices],
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

    # 8. Persist turn evidence, then apply explicit and derived state updates.
    commands_to_apply = list(parsed.commands)
    if continuation:
        commands_to_apply.extend(continuation.parsed.commands)
    terminal_event = continuation.event_hash if continuation else call_event
    terminal_output = continuation.output_hash if continuation else output_atom
    turn_evidence = _write_turn_evidence(
        state,
        input_atom=input_atom,
        retrieval_event=retrieval_event,
        retrieval=retrieval,
        parent_event=terminal_event,
        model_output=terminal_output,
        response_text=response_text,
        commands=commands_to_apply,
        command_errors=parsed.command_errors
        + (continuation.parsed.command_errors if continuation else []),
    )

    mutation_events = _apply_engine_commands(
        state,
        commands_to_apply,
        parent_event=turn_evidence.event_hash,
        model_output=terminal_output,
        turn_evidence=turn_evidence.atom_hash,
    )
    current_parent = mutation_events[-1] if mutation_events else turn_evidence.event_hash
    if not _has_mastery_update(commands_to_apply):
        judgment = _judge_mastery_updates(
            state,
            evidence=turn_evidence,
            parent_event=current_parent,
            model_output=terminal_output,
            user_input=user_input,
            response_text=response_text,
            retrieval=retrieval,
        )
        if judgment.event_hash:
            current_parent = judgment.event_hash

        derived_commands = (
            judgment.commands
            if judgment.usable
            else _derive_mastery_updates(state, turn_evidence)
        )
        derived_events = _apply_engine_commands(
            state,
            derived_commands,
            parent_event=current_parent,
            model_output=terminal_output,
            turn_evidence=turn_evidence.atom_hash,
        )
        mutation_events.extend(derived_events)
        if derived_events:
            current_parent = derived_events[-1]

    state.last_event = current_parent
    _update_current_session_ref(state)

    state.messages.append({"role": "assistant", "content": response_text})

    return response_text


def session_trace_rows(
    ws: Workspace,
    session_tip: Hash,
) -> list[SessionTraceRow]:
    """Return a chronological summary of session events plus child calls."""
    events = _session_related_events(ws, session_tip)

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


def mastery_judgment_trace_rows(
    ws: Workspace,
    session_tip: Hash,
) -> list[MasteryJudgmentTraceRow]:
    """Return decoded mastery-judgment evidence from a session trace."""
    rows: list[MasteryJudgmentTraceRow] = []
    for event_hash, event in _session_related_events(ws, session_tip):
        if "mastery-judgment" not in event.tags:
            continue

        output_ref = next(
            (ref for ref in event.outputs if ref.role == "mastery_judgment"),
            None,
        )
        if output_ref is None:
            continue
        output_atom = ws.get_atom(output_ref.hash)
        structured = (
            output_atom.structured
            if output_atom is not None and isinstance(output_atom.structured, dict)
            else {}
        )
        turn = _optional_int(structured.get("turn"))
        model = event.trace.model or str(structured.get("model") or "")
        fallback = bool(structured.get("fallback"))
        errors = tuple(str(error) for error in structured.get("errors") or [])
        judgments = structured.get("judgments")

        if not isinstance(judgments, list) or not judgments:
            rows.append(
                MasteryJudgmentTraceRow(
                    index=len(rows) + 1,
                    event_hash=event_hash,
                    turn=turn,
                    model=model,
                    concept_hash=None,
                    concept_name="",
                    current_level=None,
                    judged_level=None,
                    bounded_level=None,
                    delta=None,
                    confidence=None,
                    status=_mastery_judgment_status({}, fallback, errors),
                    evidence="",
                    fallback=fallback,
                    errors=errors,
                )
            )
            continue

        for judgment in judgments:
            if not isinstance(judgment, dict):
                rows.append(
                    MasteryJudgmentTraceRow(
                        index=len(rows) + 1,
                        event_hash=event_hash,
                        turn=turn,
                        model=model,
                        concept_hash=None,
                        concept_name="",
                        current_level=None,
                        judged_level=None,
                        bounded_level=None,
                        delta=None,
                        confidence=None,
                        status="invalid judgment",
                        evidence="",
                        fallback=fallback,
                        errors=errors,
                    )
                )
                continue

            concept_hash = _optional_hash(judgment.get("concept"))
            rows.append(
                MasteryJudgmentTraceRow(
                    index=len(rows) + 1,
                    event_hash=event_hash,
                    turn=turn,
                    model=model,
                    concept_hash=concept_hash,
                    concept_name=_concept_name(ws, concept_hash),
                    current_level=_optional_float(judgment.get("current_mastery")),
                    judged_level=_optional_float(judgment.get("level")),
                    bounded_level=_optional_float(judgment.get("bounded_level")),
                    delta=_optional_float(judgment.get("delta")),
                    confidence=_optional_float(judgment.get("confidence")),
                    status=_mastery_judgment_status(judgment, fallback, errors),
                    evidence=_bounded_text(
                        str(judgment.get("evidence") or ""),
                        140,
                    ),
                    fallback=fallback,
                    errors=errors,
                )
            )
    return rows


def _session_related_events(
    ws: Workspace,
    session_tip: Hash,
) -> list[tuple[Hash, Event]]:
    """Collect parent-chain events plus auxiliary child calls and notices."""
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
            if output_ref.role in {"child_call", "engine_notice"}:
                collect(output_ref.hash)

    collect(session_tip)
    return events


def _mastery_judgment_status(
    judgment: dict[str, Any],
    fallback: bool,
    errors: tuple[str, ...],
) -> str:
    if judgment.get("accepted"):
        return "accepted"
    if judgment.get("error"):
        return f"invalid: {judgment['error']}"
    if judgment.get("skip_reason"):
        return f"skipped: {judgment['skip_reason']}"
    if errors:
        return "error -> fallback" if fallback else "error"
    if fallback:
        return "fallback"
    return "skipped"


def _optional_hash(value: Any) -> Hash | None:
    if not isinstance(value, str):
        return None
    try:
        return Hash.from_hex(value)
    except Exception:
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _concept_name(ws: Workspace, concept_hash: Hash | None) -> str:
    if concept_hash is None:
        return ""
    atom = ws.get_atom(concept_hash)
    if atom is None:
        return concept_hash.short()
    return _bounded_text(atom.text, 72)


SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "show available commands"),
    ("/mastery", "show current mastery levels"),
    ("/model", "show or change the current model"),
    ("/judge", "show or change mastery judgment mode"),
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

            if cmd == "/judge" or cmd.startswith("/judge "):
                _handle_judge_command(state, stripped)
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
                display.info(f"judge     {config.mastery_judgment}")
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


def _handle_judge_command(state: SessionState, raw_command: str) -> None:
    argument = _slash_argument(raw_command)
    if argument is None:
        display.info(f"mastery judge {state.config.mastery_judgment}")
        display.hint("use /judge model or /judge heuristic")
        return

    selected = _resolve_mastery_judgment_mode(argument)
    if selected is None:
        display.warn(f"Unknown mastery judgment mode: {argument}")
        display.hint("available modes: model, heuristic")
        return
    _set_mastery_judgment_mode(state, selected)


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


def _resolve_mastery_judgment_mode(value: str) -> str | None:
    mode = value.strip().lower().replace("_", "-")
    aliases = {
        "h": "heuristic",
        "heuristics": "heuristic",
        "rule": "heuristic",
        "rules": "heuristic",
        "m": "model",
        "judge": "model",
        "model-judged": "model",
        "model-judgement": "model",
        "model-judgment": "model",
    }
    mode = aliases.get(mode, mode)
    if mode in MASTERY_JUDGMENT_MODES:
        return mode
    return None


def _set_mastery_judgment_mode(state: SessionState, mode: str) -> None:
    selected = _resolve_mastery_judgment_mode(mode)
    if selected is None:
        display.warn(f"Unknown mastery judgment mode: {mode}")
        return
    previous = state.config.mastery_judgment
    if selected == previous:
        display.info("mastery judge unchanged")
        return
    state.config.mastery_judgment = selected
    display.success(f"Mastery judge set to {selected}")
    display.hint(f"was {previous}; applies to subsequent turns")


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


def _write_turn_evidence(
    state: SessionState,
    input_atom: Hash,
    retrieval_event: Hash,
    retrieval: RetrievalRecord,
    parent_event: Hash,
    model_output: Hash,
    response_text: str,
    commands: list[EngineCommand],
    command_errors: list[CommandError],
) -> TurnEvidenceRecord:
    """Persist rebuildable evidence for turn-level mastery changes."""
    concept_scores = _turn_concept_scores(state, retrieval)
    signal, base_delta = _student_mastery_signal(retrieval.query.text_query or "")
    evidence_atom = state.ws.put_atom(
        Atom(
            "Config",
            f"turn evidence for turn {state.turn_count}",
            tags=["turn-evidence"],
            structured={
                "turn": state.turn_count,
                "student_message": input_atom.to_hex(),
                "retrieval_event": retrieval_event.to_hex(),
                "model_output": model_output.to_hex(),
                "response_chars": len(response_text),
                "signal": signal,
                "base_delta": base_delta,
                "concept_scores": [
                    {"concept": h.to_hex(), "score": score}
                    for h, score in sorted(
                        concept_scores.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                ],
                "commands": [_command_to_dict(c) for c in commands],
                "command_errors": [
                    _command_error_to_dict(error) for error in command_errors
                ],
            },
        )
    )

    inputs = [
        EventRef(input_atom, "student_message"),
        EventRef(retrieval_event, "retrieval_event"),
        EventRef(model_output, "model_output"),
    ]
    if state.student_model:
        inputs.append(EventRef(state.student_model, "student_model"))

    evidence_event = state.ws.put_event(
        Event(
            "Admin",
            parents=[parent_event],
            inputs=inputs,
            outputs=[EventRef(evidence_atom, "turn_evidence")],
            tags=["turn-evidence"],
        )
    )

    return TurnEvidenceRecord(
        atom_hash=evidence_atom,
        event_hash=evidence_event,
        concept_scores=concept_scores,
        signal=signal,
        base_delta=base_delta,
    )


def _turn_concept_scores(
    state: SessionState,
    retrieval: RetrievalRecord,
) -> dict[Hash, float]:
    """Find concepts with evidence in this turn and their confidence scores."""
    scores: dict[Hash, float] = {h: 1.0 for h in retrieval.query.focus_concepts}
    if scores:
        return scores

    for candidate in retrieval.results[: state.config.max_context_results]:
        _add_concept_score(state, scores, candidate.hash, candidate.score)

    return scores


def _add_concept_score(
    state: SessionState,
    scores: dict[Hash, float],
    candidate_hash: Hash,
    score: float,
) -> None:
    try:
        atom = state.ws.get_atom(candidate_hash)
    except TypeError:
        atom = None
    if atom is not None:
        if atom.kind == "ConceptDefinition":
            scores[candidate_hash] = max(scores.get(candidate_hash, 0.0), score)
        return

    try:
        concepts = state.ws.collect_atoms(candidate_hash, "ConceptDefinition")
    except Exception:
        return
    for concept_hash, _atom in concepts:
        scores[concept_hash] = max(scores.get(concept_hash, 0.0), score * 0.8)


def _student_mastery_signal(user_input: str) -> tuple[str, float]:
    lower = user_input.lower()
    negative_markers = [
        "confused",
        "don't understand",
        "do not understand",
        "stuck",
        "lost",
        "wrong",
        "mistake",
        "hard",
        "struggling",
    ]
    positive_markers = [
        "i understand",
        "makes sense",
        "got it",
        "solved",
        "figured out",
        "correct",
        "that works",
    ]
    practice_markers = ["practice", "quiz", "test", "problem", "exercise"]
    explanation_markers = ["explain", "what is", "how does", "describe", "why"]

    if any(marker in lower for marker in negative_markers):
        return "student_confusion", -0.06
    if any(marker in lower for marker in positive_markers):
        return "student_self_reported_progress", 0.08
    if any(marker in lower for marker in practice_markers):
        return "practice_or_assessment_request", 0.04
    if any(marker in lower for marker in explanation_markers):
        return "instructional_exposure", 0.025
    return "turn_interaction", 0.015


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
    commands, command_errors = _commands_from_payload(payload)
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
        command_errors=command_errors,
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
    command_errors: list[CommandError] = []
    response_id = data.get("id") if isinstance(data.get("id"), str) else None

    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") not in {"function_call", "tool_call"}:
            continue
        name = item.get("name")
        if not isinstance(name, str):
            command_errors.append(
                CommandError(
                    kind=None,
                    message="tool call missing command name",
                    item=item,
                    source_response_id=response_id,
                )
            )
            continue
        arguments = _coerce_command_arguments(item.get("arguments"))
        command = EngineCommand(
            kind=name,
            arguments=arguments,
            source_response_id=response_id,
        )
        errors = _validate_command(command)
        if errors:
            command_errors.append(
                CommandError(
                    kind=name,
                    message="; ".join(errors),
                    item=item,
                    source_response_id=response_id,
                )
            )
            continue
        commands.append(command)

    visible_text = _extract_responses_text(data)
    if not visible_text and not commands:
        visible_text = "_Unexpected API response format: no text output found_"
    return ParsedModelOutput(
        visible_text=visible_text,
        commands=commands,
        command_errors=command_errors,
        raw_text=visible_text,
    )


def _commands_from_payload(payload: Any) -> tuple[list[EngineCommand], list[CommandError]]:
    """Normalize strict JSON payloads into EngineCommand objects."""
    command_items: list[Any]
    if isinstance(payload, dict) and isinstance(payload.get("commands"), list):
        command_items = payload["commands"]
    elif isinstance(payload, dict) and ("kind" in payload or "name" in payload):
        command_items = [payload]
    elif isinstance(payload, list):
        command_items = payload
    else:
        return [], []

    commands: list[EngineCommand] = []
    command_errors: list[CommandError] = []
    for item in command_items:
        if not isinstance(item, dict):
            command_errors.append(
                CommandError(
                    kind=None,
                    message="command item must be an object",
                    item=item,
                )
            )
            continue
        kind = item.get("kind") or item.get("name")
        if not isinstance(kind, str):
            command_errors.append(
                CommandError(
                    kind=None,
                    message="command missing kind",
                    item=item,
                )
            )
            continue
        arguments = _coerce_command_arguments(item.get("arguments", {}))
        command = EngineCommand(kind=kind, arguments=arguments)
        errors = _validate_command(command)
        if errors:
            command_errors.append(
                CommandError(
                    kind=kind,
                    message="; ".join(errors),
                    item=item,
                )
            )
            continue
        commands.append(command)
    return commands, command_errors


def _is_supported_command(kind: str) -> bool:
    return kind in {"mastery_update", "subcall"}


def _validate_command(command: EngineCommand) -> list[str]:
    if not _is_supported_command(command.kind):
        return [f"unsupported command kind: {command.kind}"]
    if command.kind == "mastery_update":
        errors = []
        if _command_concept_hash(command) is None:
            errors.append("mastery_update requires a valid concept hash")
        if _command_mastery_level(command) is None:
            errors.append("mastery_update requires a numeric level")
        return errors
    if command.kind == "subcall":
        if not _subcall_prompt(command):
            return ["subcall requires a non-empty prompt"]
    return []


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


def _command_error_to_dict(error: CommandError) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": error.kind,
        "message": error.message,
        "item": error.item,
    }
    if error.source_response_id:
        data["source_response_id"] = error.source_response_id
    return data


def _write_command_error_notices(
    state: SessionState,
    parent_event: Hash,
    errors: list[CommandError],
) -> list[EngineNotice]:
    notices = []
    for error in errors:
        notices.append(
            _write_engine_notice(
                state,
                parent_event,
                "command_validation_failed",
                error.message,
                details={"command_error": _command_error_to_dict(error)},
            )
        )
    return notices


def _write_engine_notice(
    state: SessionState,
    parent_event: Hash,
    kind: str,
    message: str,
    *,
    command: EngineCommand | None = None,
    depth: int | None = None,
    details: dict[str, Any] | None = None,
) -> EngineNotice:
    structured: dict[str, Any] = {
        "kind": kind,
        "message": message,
    }
    if depth is not None:
        structured["depth"] = depth
    if command is not None:
        structured["command"] = _command_to_dict(command)
    if details:
        structured.update(details)

    atom_hash = state.ws.put_atom(
        Atom(
            "Config",
            f"engine notice: {kind}",
            tags=["engine-notice"],
            structured=structured,
        )
    )
    event_hash = state.ws.put_event(
        Event(
            "Admin",
            parents=[parent_event],
            outputs=[EventRef(atom_hash, "notice")],
            tags=["engine-notice", kind],
        )
    )
    return EngineNotice(
        event_hash=event_hash,
        atom_hash=atom_hash,
        kind=kind,
        message=message,
    )


def _execute_subcalls(
    state: SessionState,
    commands: list[EngineCommand],
    parent_event: Hash,
    depth: int,
) -> SubcallBatch:
    """Execute bounded recursive subcall commands."""
    batch = SubcallBatch()
    for command in commands:
        if command.kind != "subcall":
            continue
        if depth > state.config.max_call_depth:
            batch.notices.append(
                _write_engine_notice(
                    state,
                    parent_event,
                    "subcall_depth_exceeded",
                    (
                        f"subcall depth {depth} exceeds max depth "
                        f"{state.config.max_call_depth}"
                    ),
                    command=command,
                    depth=depth,
                )
            )
            continue
        if state.subcalls_used >= state.config.max_subcalls_per_turn:
            batch.notices.append(
                _write_engine_notice(
                    state,
                    parent_event,
                    "subcall_budget_exceeded",
                    (
                        f"subcall budget {state.config.max_subcalls_per_turn} "
                        "used for this turn"
                    ),
                    command=command,
                    depth=depth,
                )
            )
            continue
        result = _execute_subcall(
            state,
            command,
            parent_event=parent_event,
            depth=depth,
        )
        if result:
            batch.child_results.append(result)
        else:
            batch.notices.append(
                _write_engine_notice(
                    state,
                    parent_event,
                    "subcall_invalid_request",
                    "subcall request had no prompt",
                    command=command,
                    depth=depth,
                )
            )
    return batch


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
    state.subcalls_used += 1

    request_atom = state.ws.put_atom(
        Atom(
            "Config",
            f"subcall request depth {depth}",
            tags=["subcall-request"],
            structured={
                **command.arguments,
                "depth": depth,
                "parent_event": parent_event.to_hex(),
                "budget_index": state.subcalls_used,
                "source_response_id": command.source_response_id,
            },
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
    command_notices = _write_command_error_notices(
        state,
        retrieval_event,
        parsed.command_errors,
    )

    nested_batch = _execute_subcalls(
        state,
        parsed.commands,
        parent_event=retrieval_event,
        depth=depth + 1,
    )
    nested_results = nested_batch.child_results

    output_structured = None
    if (
        parsed.commands
        or parsed.command_errors
        or parsed.raw_text != parsed.visible_text
        or nested_results
        or command_notices
        or nested_batch.notices
    ):
        output_structured = {
            "commands": [_command_to_dict(c) for c in parsed.commands],
            "command_errors": [
                _command_error_to_dict(e) for e in parsed.command_errors
            ],
            "raw_text": parsed.raw_text,
            "child_calls": [
                {
                    "event": c.event_hash.to_hex(),
                    "output": c.output_hash.to_hex(),
                }
                for c in nested_results
            ],
            "engine_notices": [
                {
                    "event": n.event_hash.to_hex(),
                    "kind": n.kind,
                    "message": n.message,
                }
                for n in command_notices + nested_batch.notices
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
            + [EventRef(c.event_hash, "child_call") for c in nested_results]
            + [
                EventRef(n.event_hash, "engine_notice")
                for n in command_notices + nested_batch.notices
            ],
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
    command_notices = _write_command_error_notices(
        state,
        parent_call_event,
        parsed.command_errors,
    )

    output_structured = None
    if (
        child_results
        or parsed.commands
        or parsed.command_errors
        or parsed.raw_text != parsed.visible_text
        or command_notices
    ):
        output_structured = {
            "commands": [_command_to_dict(c) for c in parsed.commands],
            "command_errors": [
                _command_error_to_dict(e) for e in parsed.command_errors
            ],
            "raw_text": parsed.raw_text,
            "parent_call": parent_call_event.to_hex(),
            "merge_rule": "compose_parent_draft_with_child_outputs",
            "child_count": len(child_results),
            "child_calls": [
                {
                    "event": c.event_hash.to_hex(),
                    "output": c.output_hash.to_hex(),
                }
                for c in child_results
            ],
            "engine_notices": [
                {
                    "event": n.event_hash.to_hex(),
                    "kind": n.kind,
                    "message": n.message,
                }
                for n in command_notices
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
            outputs=[EventRef(output_atom, "model_output")]
            + [EventRef(n.event_hash, "engine_notice") for n in command_notices],
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


def _judge_mastery_updates(
    state: SessionState,
    evidence: TurnEvidenceRecord,
    parent_event: Hash,
    model_output: Hash,
    user_input: str,
    response_text: str,
    retrieval: RetrievalRecord,
) -> MasteryJudgmentResult:
    """Ask a bounded model judge for mastery updates when configured."""
    mode = _resolve_mastery_judgment_mode(state.config.mastery_judgment) or "model"
    state.config.mastery_judgment = mode
    if mode == "heuristic":
        return MasteryJudgmentResult()
    if state.student_model is None or not state.config.api_key:
        return MasteryJudgmentResult()

    candidates = _mastery_judgment_candidates(state, evidence)
    if not candidates:
        return MasteryJudgmentResult()

    prompt_payload = _mastery_judgment_prompt_payload(
        state,
        evidence=evidence,
        candidates=candidates,
        user_input=user_input,
        response_text=response_text,
        retrieval=retrieval,
    )
    judge_model = _mastery_judge_model(state)
    judge_state = SessionState(
        ws=state.ws,
        config=replace(state.config, model=judge_model),
        session_event=state.session_event,
        last_event=parent_event,
        student_model=state.student_model,
        messages=[
            {
                "role": "user",
                "content": json.dumps(prompt_payload, indent=2, sort_keys=True),
            }
        ],
        turn_count=state.turn_count,
    )

    t0 = time.monotonic()
    try:
        raw_response = _call_model(judge_state, MASTERY_JUDGMENT_PROTOCOL)
        latency_ms = int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        display.warn(f"Mastery judgment skipped: {exc}")
        return _write_mastery_judgment_call(
            state,
            parent_event=parent_event,
            turn_evidence=evidence.atom_hash,
            model_output=model_output,
            judge_model=judge_model,
            latency_ms=latency_ms,
            prompt_payload=prompt_payload,
            raw_output="",
            normalized_judgments=[],
            accepted_commands=[],
            errors=[f"model call failed: {exc}"],
            usable=False,
        )

    raw_output, judgments, parse_errors = _parse_mastery_judgment_payload(raw_response)
    normalized_judgments: list[dict[str, Any]] = []
    commands: list[EngineCommand] = []
    validation_errors: list[str] = []
    if judgments is not None:
        commands, normalized_judgments, validation_errors = (
            _mastery_judgment_commands(state, candidates, judgments)
        )

    errors = parse_errors + validation_errors
    usable = judgments is not None and (not validation_errors or bool(commands))
    return _write_mastery_judgment_call(
        state,
        parent_event=parent_event,
        turn_evidence=evidence.atom_hash,
        model_output=model_output,
        judge_model=judge_model,
        latency_ms=latency_ms,
        prompt_payload=prompt_payload,
        raw_output=raw_output,
        normalized_judgments=normalized_judgments,
        accepted_commands=commands,
        errors=errors,
        usable=usable,
    )


def _mastery_judgment_candidates(
    state: SessionState,
    evidence: TurnEvidenceRecord,
) -> list[dict[str, Any]]:
    mastery = dict(state.ws.student_mastery_map(state.student_model))
    candidates: list[dict[str, Any]] = []
    for concept_hash, score in sorted(
        evidence.concept_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:5]:
        atom = state.ws.get_atom(concept_hash)
        candidates.append(
            {
                "concept": concept_hash.to_hex(),
                "name": _bounded_text(atom.text if atom else concept_hash.short(), 240),
                "current_mastery": mastery.get(concept_hash, 0.0),
                "evidence_score": score,
            }
        )
    return candidates


def _mastery_judgment_prompt_payload(
    state: SessionState,
    evidence: TurnEvidenceRecord,
    candidates: list[dict[str, Any]],
    user_input: str,
    response_text: str,
    retrieval: RetrievalRecord,
) -> dict[str, Any]:
    return {
        "prompt_version": "mastery-judgment-v1",
        "student_id": state.config.student_id,
        "turn": state.turn_count,
        "turn_signal": evidence.signal,
        "base_delta": evidence.base_delta,
        "candidate_concepts": candidates,
        "student_message": user_input,
        "tutor_response": response_text,
        "course_context": _bounded_text(retrieval.context_text, 6000),
        "system_prompt": _bounded_text(state.config.system_prompt, 2000),
    }


def _parse_mastery_judgment_payload(
    raw_response: str | dict[str, Any],
) -> tuple[str, list[Any] | None, list[str]]:
    raw_output = (
        _extract_responses_text(raw_response)
        if isinstance(raw_response, dict)
        else str(raw_response)
    )
    parsed = _extract_json_command_payload(raw_output)
    if parsed is None:
        return raw_output, None, ["mastery judgment must be strict JSON"]

    payload = parsed[0]
    if isinstance(payload, dict):
        judgments = payload.get("judgments")
        if not isinstance(judgments, list):
            return raw_output, None, ["mastery judgment JSON requires judgments list"]
        return raw_output, judgments, []
    if isinstance(payload, list):
        return raw_output, payload, []
    return raw_output, None, ["mastery judgment JSON must be an object or list"]


def _mastery_judgment_commands(
    state: SessionState,
    candidates: list[dict[str, Any]],
    judgments: list[Any],
) -> tuple[list[EngineCommand], list[dict[str, Any]], list[str]]:
    candidate_by_hex = {candidate["concept"]: candidate for candidate in candidates}
    commands: list[EngineCommand] = []
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()

    for index, item in enumerate(judgments):
        record: dict[str, Any] = {
            "index": index,
            "accepted": False,
        }
        if not isinstance(item, dict):
            record["error"] = "judgment item must be an object"
            normalized.append(record)
            errors.append(f"judgment {index}: item must be an object")
            continue

        concept_raw = item.get("concept") or item.get("concept_hash")
        level = _coerce_judgment_number(item.get("level"))
        confidence = _coerce_judgment_number(item.get("confidence"))
        evidence_text = _bounded_text(str(item.get("evidence") or "").strip(), 240)
        reason_text = _bounded_text(str(item.get("reason") or "").strip(), 240)

        record.update(
            {
                "concept": concept_raw,
                "level": level,
                "confidence": confidence,
                "evidence": evidence_text,
                "reason": reason_text,
            }
        )

        if not isinstance(concept_raw, str):
            record["error"] = "concept must be a hash string"
            normalized.append(record)
            errors.append(f"judgment {index}: concept must be a hash string")
            continue
        try:
            concept_hash = Hash.from_hex(concept_raw)
        except Exception:
            record["error"] = "concept is not a valid hash"
            normalized.append(record)
            errors.append(f"judgment {index}: concept is not a valid hash")
            continue
        concept_hex = concept_hash.to_hex()
        if concept_hex not in candidate_by_hex:
            record["error"] = "concept was not in candidate_concepts"
            normalized.append(record)
            errors.append(f"judgment {index}: concept was not in candidate_concepts")
            continue
        if concept_hex in seen:
            record["error"] = "duplicate concept judgment"
            normalized.append(record)
            errors.append(f"judgment {index}: duplicate concept judgment")
            continue
        seen.add(concept_hex)

        if level is None:
            record["error"] = "level must be numeric"
            normalized.append(record)
            errors.append(f"judgment {index}: level must be numeric")
            continue
        if confidence is None:
            record["error"] = "confidence must be numeric"
            normalized.append(record)
            errors.append(f"judgment {index}: confidence must be numeric")
            continue

        target_level = max(0.0, min(1.0, level))
        confidence = max(0.0, min(1.0, confidence))
        current_level = float(candidate_by_hex[concept_hex]["current_mastery"])
        bounded_level = _bounded_judged_mastery_level(current_level, target_level)
        delta = bounded_level - current_level

        record.update(
            {
                "concept": concept_hex,
                "level": target_level,
                "confidence": confidence,
                "current_mastery": current_level,
                "bounded_level": bounded_level,
                "delta": delta,
            }
        )

        if confidence < MIN_MASTERY_JUDGMENT_CONFIDENCE:
            record["skip_reason"] = "confidence below threshold"
            normalized.append(record)
            continue
        if abs(delta) < 0.005:
            record["skip_reason"] = "bounded delta too small"
            normalized.append(record)
            continue

        reason = reason_text or evidence_text or "model-judged turn evidence"
        commands.append(
            EngineCommand(
                kind="mastery_update",
                arguments={
                    "concept": concept_hex,
                    "level": bounded_level,
                    "reason": (
                        f"model-judged mastery: {reason} "
                        f"(confidence={confidence:.2f}, delta={delta:+.3f})"
                    ),
                    "source": "model_judgment",
                    "confidence": confidence,
                    "judged_level": target_level,
                },
            )
        )
        record["accepted"] = True
        normalized.append(record)

    return commands, normalized, errors


def _write_mastery_judgment_call(
    state: SessionState,
    parent_event: Hash,
    turn_evidence: Hash,
    model_output: Hash,
    judge_model: str,
    latency_ms: int,
    prompt_payload: dict[str, Any],
    raw_output: str,
    normalized_judgments: list[dict[str, Any]],
    accepted_commands: list[EngineCommand],
    errors: list[str],
    usable: bool,
) -> MasteryJudgmentResult:
    output_hash = state.ws.put_atom(
        Atom(
            "ModelOutput",
            f"mastery judgment for turn {state.turn_count}",
            tags=["model-output", "mastery-judgment"],
            structured={
                "prompt_version": "mastery-judgment-v1",
                "mode": "model",
                "provider": state.config.provider,
                "model": judge_model,
                "turn": state.turn_count,
                "attempted": True,
                "usable": usable,
                "fallback": not usable,
                "input": prompt_payload,
                "raw_output": raw_output,
                "judgments": normalized_judgments,
                "accepted_commands": [
                    _command_to_dict(command) for command in accepted_commands
                ],
                "errors": errors,
            },
        )
    )

    inputs = [
        EventRef(turn_evidence, "turn_evidence"),
        EventRef(model_output, "model_output"),
    ]
    if state.student_model:
        inputs.append(EventRef(state.student_model, "student_model"))

    event_hash = state.ws.put_event(
        Event(
            "ModelCall",
            parents=[parent_event],
            inputs=inputs,
            outputs=[EventRef(output_hash, "mastery_judgment")],
            tags=["mastery-judgment"],
            trace=CallTrace(
                call_depth=1,
                model=judge_model,
                latency_ms=latency_ms,
            ),
        )
    )

    return MasteryJudgmentResult(
        commands=accepted_commands,
        event_hash=event_hash,
        output_hash=output_hash,
        attempted=True,
        usable=usable,
    )


def _mastery_judge_model(state: SessionState) -> str:
    judge_defaults = {
        "gpt-5.4-mini": "gpt-5.4-nano",
        "openai/gpt-5.4-mini": "openai/gpt-5.4-nano",
    }
    return judge_defaults.get(state.config.model, state.config.model)


def _bounded_judged_mastery_level(current_level: float, judged_level: float) -> float:
    delta = judged_level - current_level
    if delta > 0:
        delta = min(delta, MAX_MASTERY_JUDGMENT_INCREASE)
    else:
        delta = max(delta, -MAX_MASTERY_JUDGMENT_DECREASE)
    return max(0.0, min(1.0, current_level + delta))


def _coerce_judgment_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _apply_engine_commands(
    state: SessionState,
    commands: list[EngineCommand],
    parent_event: Hash,
    model_output: Hash,
    turn_evidence: Hash | None = None,
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
            turn_evidence=turn_evidence,
        )
        if event_hash:
            mutation_events.append(event_hash)
            current_parent = event_hash
    return mutation_events


def _has_mastery_update(commands: list[EngineCommand]) -> bool:
    return any(command.kind == "mastery_update" for command in commands)


def _derive_mastery_updates(
    state: SessionState,
    evidence: TurnEvidenceRecord,
) -> list[EngineCommand]:
    """Derive conservative mastery changes from turn evidence."""
    if state.student_model is None or not evidence.concept_scores:
        return []

    mastery = dict(state.ws.student_mastery_map(state.student_model))
    commands: list[EngineCommand] = []
    for concept_hash, confidence in sorted(
        evidence.concept_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:3]:
        old_level = mastery.get(concept_hash, 0.0)
        scaled_delta = evidence.base_delta * (0.5 + 0.5 * min(1.0, confidence))
        new_level = max(0.0, min(1.0, old_level + scaled_delta))
        if abs(new_level - old_level) < 0.005:
            continue
        commands.append(
            EngineCommand(
                kind="mastery_update",
                arguments={
                    "concept": concept_hash.to_hex(),
                    "level": new_level,
                    "reason": (
                        f"derived from {evidence.signal} "
                        f"(confidence={confidence:.2f}, "
                        f"delta={new_level - old_level:+.3f})"
                    ),
                    "source": "turn_evidence",
                },
            )
        )
    return commands


def _apply_mastery_update(
    state: SessionState,
    command: EngineCommand,
    parent_event: Hash,
    model_output: Hash,
    turn_evidence: Hash | None = None,
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

    source = str(command.arguments.get("source") or "mastery_update")
    updated_edges.append(
        Edge(
            "InteractionRecord",
            parent_event,
            annotation={"source": source},
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

    inputs = [
        EventRef(old_model_hash, "prior"),
        EventRef(model_output, "model_output"),
        EventRef(concept_hash, "concept"),
    ]
    if turn_evidence:
        inputs.append(EventRef(turn_evidence, "turn_evidence"))

    event = Event(
        "StudentModelUpdate",
        parents=[parent_event],
        inputs=inputs,
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
        extra_headers=dict(state.config.extra_headers),
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
