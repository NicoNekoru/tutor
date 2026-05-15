# How To Use rlm-ws

This document separates what works today from motions that are planned but not
yet implemented. The current app is an early persistent tutor: it can ingest a
course, run tutoring turns, retrieve relevant material, persist every turn in
the object store, and update a per-student mastery model.

## 1. Create A Course Workspace

For a local non-network demo, run:

```bash
rlm-ws demo rlm-demo
cd rlm-demo
rlm-ws inspect --sessions demo
rlm-ws inspect --timeline demo --concept "binary search"
```

For your own course, run:

```bash
rlm-ws init my-course
cd my-course
```

The initializer creates a workspace and starter content. Course material lives
in markdown files under `content/`.

Supported markdown blocks today:

- `#` and `##` headings for modules and lessons.
- `### Concept: Name` for concept definitions.
- `### Problem: Name` for practice prompts.
- `### Example: Name` for worked examples.
- `<!-- prerequisite: Lesson Or Concept Name -->` for prerequisite links.

Planned:

- (planned) Richer importers for PDFs, notebooks, webpages, and existing course exports.
- (planned) Course-level mastery rubrics that steer the model judge per concept.

## 2. Configure A Model Provider

```bash
rlm-ws auth
rlm-ws auth --show
```

OpenAI is the default direct provider. OpenRouter and OpenAI-compatible
providers use chat completions. Without an API key, sessions run in offline mode
and echo input while still exercising storage, retrieval, and heuristic mastery
updates.

The default tutoring model is mini. Recursive child calls and mastery judgment
use nano when the active OpenAI/OpenRouter model is mini.

Planned:

- (planned) Native provider adapters beyond OpenAI-compatible chat completions.
- (planned) Provider-native structured tool calls where available.

## 3. Start Tutoring

```bash
rlm-ws session --student alice
```

Useful in-session commands:

- `/mastery` shows current mastery estimates.
- `/model` shows or changes the active model for later turns.
- `/judge` shows or changes mastery update mode: `model` or `heuristic`.
- `/tree` shows the ingested course structure.
- `/status` shows session and workspace status.
- `/quit` ends and archives the session.

During each turn, the engine currently:

- Records the student message as a `StudentInput` event.
- Retrieves relevant course and student-state context.
- Persists a `RetrievalPerformed` event.
- Builds a first-class `CallContext`.
- Calls the model and validates any engine commands.
- Executes bounded recursive `subcall` requests.
- Persists model calls, child calls, engine notices, and turn evidence.
- Updates mastery from explicit commands, model-judged evidence, or heuristic fallback.

Planned:

- (planned) Richer recursive planning and merge policies.
- (planned) Better user controls for budgets, depth, and recursive behavior.
- (planned) Practice/problem-generation flows that update mastery from structured answers.

## 4. Inspect What Happened

```bash
rlm-ws inspect --sessions alice
rlm-ws inspect --mastery alice
rlm-ws inspect --tree
rlm-ws inspect --timeline alice --concept "binary search"
```

Today, session inspection shows the persisted event timeline, including model
calls, child calls, engine notices, and decoded mastery-judgment evidence:
prior level, judged level, bounded applied level, delta, confidence, fallback
status, and the turn evidence cited by the judge. Timeline inspection shows how
one concept's mastery changed across turns. Mastery inspection shows the current
per-concept mastery frame.

Planned:

- (planned) Retrieval explanation views that show why specific material was selected.
- (planned) Diff-style views between student model versions.

## 5. Move Data Between Workspaces

```bash
rlm-ws export course/structure -o course.json
rlm-ws import course.json --set-ref course/imported
```

Export and import operate on object-store subgraphs, so refs can be moved
without relying on hosted model state.

Planned:

- (planned) Higher-level course-package import/export workflows.
- (planned) Merge tooling for imported course or student-state branches.

## Current Engine Status

Implemented:

- Content-addressed atoms, frames, events, refs, CAS mutations, and rebuildable indexes.
- Markdown course ingestion.
- Retrieval strategies for graph proximity, mastery, recency, prerequisites, interaction history, sparse text, and optional derived embeddings.
- Interactive tutoring sessions.
- Persistent student mastery models.
- Model-judged mastery with bounded deltas and heuristic fallback.
- Bounded recursive child model calls.
- Session trace inspection with decoded mastery-judgment evidence.
- Per-concept learning timelines.

Planned:

- (planned) Full recursive planner/executor semantics.
- (planned) Native structured command schemas across providers.
- (planned) Course-specific mastery rubrics.
- (planned) Robust semantic embedding adapters and rebuild commands.
