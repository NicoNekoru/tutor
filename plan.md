Based on the Recursive Language Model (RLM) paper's proposed framework with the python REPL for indexing context with a search-engine like retrieval, let's build a TUI app for learning. In particular, for some specific initialization process which clarifies the theme of the tutoring, establishes the persona of the model, and develops a syllabus, the lessons, teaching logs, etc. are all stored either statically in files / indexed within the REPL.

As an example initialization:
> Hello! You are my tutor for combinatorics. You are a highly theoretical professor within the field, with a research specialization in combinatorial applications in machine learning. However, I am your only student. Start by creating a syllabus for the combinatorial theory course you will personally teach me, and then let's begin.

Please help me figure out what considerations are necessary for this kind of application, how we can bootstrap this to existing model providing CLIs like opencode, and anything else that may be useful. Focus on architecting and broader implementation details, not yet specific code yet.





This is a very good fit for an RLM-style application.

What you’re really building is not just “a chat app with files,” but a small tutoring operating system:

- a persistent pedagogical memory,
- a retrieval layer over that memory,
- a model-facing tool interface,
- and a TUI that makes all of that legible to the learner.

If you keep that framing in mind, the architecture becomes much clearer.

1. Core product idea

The app should treat tutoring as a long-lived, structured process rather than a sequence of unrelated chats.

Given an initialization like:

> Hello! You are my tutor for combinatorics...

the system should produce and maintain:

- tutor persona / instructional stance
- student profile
- course theme and goals
- syllabus
- lesson plans
- lesson artifacts
- progress / mastery state
- teaching logs
- exercises and solutions
- retrieval index over all of the above

The model then does not need to “remember” everything in-context. Instead, it should be able to search, inspect, summarize, and update this course memory.

That is the RLM-like move:
- keep the active prompt small,
- recursively retrieve and inspect relevant state,
- use tools to reason over the persistent context.

2. Architectural principle: separate canonical state from model context

This is the most important design decision.

Do not let the conversation transcript be the source of truth.

Instead, maintain two layers:

A. Canonical persistent state
Stored on disk in structured and human-readable formats:
- Markdown for lesson notes, syllabus, explanations
- YAML/JSON/TOML for metadata and machine-readable state
- SQLite for logs, indexing metadata, embeddings, event records
- optional flat files for transcripts and assignments

B. Dynamic model context
At each turn, construct a small working context by retrieving:
- relevant syllabus sections
- recent teaching log entries
- open student questions
- current lesson plan
- prerequisite concepts
- past mistakes or gaps
- current scratch work

This avoids “chat drift,” keeps behavior consistent, and makes the app inspectable.

3. A useful mental model: knowledge graph + notebook + search engine

Your tutoring system can be thought of as three coupled structures.

A. Knowledge graph
Represents the pedagogical structure:
- topics
- subtopics
- prerequisites
- lesson dependencies
- learning objectives
- concept mastery links

For combinatorics, for example:
- counting principles
- bijections
- generating functions
- inclusion-exclusion
- graph enumeration
- probabilistic method

Each concept node can store:
- definition
- lesson references
- prerequisite nodes
- exercises
- common misconceptions
- mastery estimate

B. Notebook / archive
Stores the actual artifacts:
- syllabus.md
- lesson_001.md
- lesson_002.md
- office_hours_log.md
- mistakes.md
- assignments/
- reflections/
- summaries/

C. Search / retrieval index
Lets the model find relevant fragments quickly:
- lexical search for exact terms
- semantic search for conceptual similarity
- metadata filtering by topic, lesson number, date, type
- graph-aware expansion through prerequisites and neighbors

That combination is much more powerful than “vector DB only” or “just files.”

4. What should be persisted?

You’ll want to explicitly define your durable entities.

At minimum:

A. Tutor configuration
- subject
- persona
- tone
- pedagogical philosophy
- depth preference
- problem-solving style
- allowed tools
- curriculum generation rules

Example:
- “Highly theoretical professor”
- “research specialization in combinatorial applications in ML”
- “emphasize proof techniques and abstraction”

B. Student profile
- name / handle
- goals
- prior knowledge
- preferred pacing
- confidence areas
- struggle areas
- time commitment
- assessment style preference

C. Course manifest
- course title
- subject
- syllabus version
- course objectives
- topic sequence
- current lesson
- completion status

D. Lessons
For each lesson:
- title
- objectives
- prerequisites
- main exposition
- examples
- exercises
- lesson summary
- generated follow-ups
- status

E. Teaching logs
These are crucial and often overlooked.
Store:
- what was taught
- what the student asked
- where confusion arose
- what analogies worked
- what homework was assigned
- what should be reviewed next time

F. Concept mastery records
For each concept:
- exposure count
- last discussed time
- student self-rated confidence
- inferred mastery
- evidence for mastery / confusion

G. Transcripts
Useful, but not canonical.
Transcripts support:
- auditability
- summarization
- learning analytics
- prompt debugging

5. Initialization flow

Your example initialization suggests a very natural bootstrap pipeline.

When the user provides a broad tutoring request, the app should do an initialization transaction.

Suggested stages:

A. Parse and structure the request
Extract:
- subject: combinatorics
- tutor persona: highly theoretical professor
- specialization: combinatorial applications in machine learning
- relationship: single-student private tutoring
- immediate task: create syllabus, then begin

B. Create a course workspace
Create a persistent workspace like:
- `courses/combinatorics-private-tutoring/`

C. Generate initial artifacts
- `course_manifest.yaml`
- `tutor_persona.md`
- `student_profile.yaml`
- `syllabus.md`
- `lesson_001.md`
- `teaching_log.md`

D. Build initial index
Index these files immediately.

E. Start first lesson state
Mark:
- current lesson = 1
- current concepts = foundations / counting principles / proof techniques
or whatever the generated syllabus decides

F. Show the user a review step
Before fully locking in the course, you likely want a lightweight confirmation:
- desired rigor
- pace
- prior background
- whether applications to ML should be woven throughout or saved for later

That confirmation is important because otherwise the model may generate a beautiful but mismatched syllabus.

6. Retrieval design: this is where the RLM flavor really matters

You mentioned “python REPL for indexing context with a search-engine-like retrieval.” Architecturally, I’d separate retrieval into two layers:

A. Stable retrieval subsystem
This should not live purely “inside the model.”
It should be an application-level service/tool exposing operations like:
- search(query, filters)
- fetch(document_id)
- fetch_neighbors(concept_id)
- list_recent_logs()
- get_current_lesson()
- get_open_questions()
- get_prerequisites(concept)

The model can call these via tools or CLI wrappers.

B. Python REPL as a higher-order reasoning tool
The Python REPL is best used for:
- ad hoc ranking logic
- re-scoring retrieved chunks
- building temporary concept maps
- comparing candidate contexts
- doing symbolic/math computations
- generating summaries or schedule plans from structured data

In other words:
- retrieval infra should be a reliable substrate
- REPL should be the flexible analysis layer on top

If you rely on the REPL as the only indexing/retrieval engine, you risk fragility, slower turn times, and inconsistent state.

7. Retrieval strategy recommendations

A tutoring app has richer retrieval needs than ordinary RAG.

You do not just want “documents similar to the current question.”
You want pedagogically relevant context.

Use a hybrid retrieval policy combining:

A. Lexical retrieval
Useful for:
- exact concept names
- theorem references
- exercise IDs
- notation consistency
- quoted phrases from prior lessons

B. Semantic retrieval
Useful for:
- paraphrased questions
- conceptually related explanations
- misconception matching

C. Structural retrieval
Use graph relations:
- prerequisites
- same lesson
- same topic cluster
- adjacent syllabus modules

D. Temporal retrieval
Recent items often matter:
- current lesson
- previous lesson
- latest confusion points
- recent assignments

E. Mastery-aware retrieval
Bring in:
- concepts the student is weak on
- recurring mistakes
- spaced review candidates

This is much better than raw top-k embeddings.

A good retrieval bundle for each turn might be:
- 1 current lesson artifact
- 1 relevant syllabus section
- 2 recent log snippets
- 1 past confusion/mistake snippet
- 2 concept-related chunks
- optional prerequisite note

8. Chunking considerations

Because your materials are pedagogically structured, generic chunking is often not enough.

Prefer semantic / typed chunks such as:
- lesson objective
- explanation block
- worked example
- theorem/proof
- exercise
- misconception note
- lesson summary
- student question
- tutor reflection

This lets you retrieve “the right kind” of context.

For example:
if the user asks for intuition, don’t retrieve only theorem statements.
If the user asks for proof help, favor proof/explanation chunks over exercises.

Metadata on chunks should include:
- source file
- lesson number
- topic
- concept tags
- artifact type
- timestamp
- status
- difficulty
- prerequisite tags

9. Context assembly policy

The model should not see the whole archive.

Have a context builder that assembles a compact prompt package, such as:

- system instruction / tutor contract
- student profile summary
- current lesson state
- retrieved documents
- active user message
- tool affordances

You want deterministic rules for what is always included.

Likely always include:
- tutor persona summary
- course goals summary
- current lesson metadata
- concise progress summary

And then retrieve the rest on demand.

This avoids the “model forgets it’s a theoretical tutor” problem.

10. Persona design and prompt governance

Since persona is part of the product, don’t leave it buried in an old transcript.

Represent it explicitly.

I’d define a stable “tutor contract” with fields like:
- identity/style
- rigor level
- preferred teaching method
- degree of formality
- when to ask diagnostic questions
- when to provide exercises
- how to handle confusion
- how to adapt for this student

For example:
- lead with theory, then examples
- emphasize proofs and invariant-based reasoning
- connect topics to ML applications when relevant
- adjust pace based on student mastery
- maintain continuity across lessons

This should be stored and surfaced in every session.

Also consider allowing persona revisions over time:
- “be less formal”
- “give more intuition before proofs”
- “use more concrete examples”

11. TUI design considerations

A TUI can be excellent here because the app is fundamentally stateful and document-centric.

A useful TUI layout might have 4 panels:

A. Main dialogue pane
The live tutoring interaction.

B. Course/navigation pane
- syllabus tree
- lessons
- concepts
- assignments
- logs

C. Context pane
Show what the model currently retrieved:
- active files
- ranked chunks
- lesson references
- notes used in response generation

This is especially important if you want the app to feel “RLM-like” and inspectable.

D. Scratch / REPL / notes pane
For:
- model’s tool actions
- user scratch work
- Python outputs
- symbolic derivations
- draft explanations

This makes the app more than a chatbot; it becomes a learning cockpit.

Useful TUI commands:
- `:init`
- `:syllabus`
- `:lesson next`
- `:review`
- `:search <query>`
- `:context`
- `:log`
- `:concept <name>`
- `:assign`
- `:reindex`
- `:persona`
- `:export`

12. Transparency and inspectability

One of the biggest benefits of this kind of app is that you can make the tutoring memory visible.

Strongly consider exposing:
- what was retrieved
- why it was retrieved
- what files were updated
- what summary was written after the session
- what the system believes the student currently knows

This solves two major problems:
- trust
- debuggability

It also aligns well with the RLM spirit: the model is not magically remembering; it is operating over tools and state.

13. Session lifecycle

A tutoring session should have explicit phases.

A. Pre-session
- load course state
- identify current lesson
- retrieve recent logs
- gather due review concepts
- generate session brief

B. Active tutoring
- handle dialogue
- retrieve as needed
- use REPL as needed
- update ephemeral notes

C. Post-session consolidation
This is very important.
After the conversation, generate:
- lesson summary
- concepts covered
- misconceptions identified
- exercises assigned
- mastery updates
- next-step recommendation

Then write these back to persistent storage and reindex.

If you skip consolidation, your archive will decay into messy transcripts.

14. How to bootstrap with existing model CLIs like opencode

The safest and cleanest architecture is to treat the model CLI as an interchangeable inference backend, not as the app itself.

So your TUI app should own:
- file storage
- indexing
- retrieval
- session management
- post-session consolidation
- tool routing
- data schemas

And the model CLI should provide:
- completion/chat generation
- tool-call-compatible output if supported
- maybe streaming tokens

This gives you portability across model providers.

A practical layering would be:

TUI app
-> Orchestrator
-> Retrieval/storage/tool services
-> Model adapter
-> CLI backend (`opencode`, other CLIs, local model runner, API wrapper)

The model adapter should normalize:
- prompt formatting
- streaming behavior
- tool call syntax
- JSON mode / structured outputs
- error handling
- retries

That way, if `opencode` changes or you want another backend, you don’t have to rewrite your app.

15. CLI integration patterns

There are a few ways to use existing CLIs.

A. Subprocess wrapper
Run the CLI as a child process and exchange:
- stdin/stdout
- JSON files
- temp prompt files

Pros:
- simple
- works quickly for prototyping

Cons:
- can be brittle
- harder to manage tool calls and structured state

B. Long-lived broker process
Your app launches a persistent model process and communicates over a stable protocol.

Pros:
- lower latency
- better streaming
- easier session continuity

Cons:
- more implementation work

C. API-compatible adapter
If the CLI exposes or can be wrapped as an OpenAI-like chat API, your orchestration becomes easier.

For a learning app, I’d strongly prefer a structured interface where you can request:
- response text
- tool requests
- metadata
- confidence or reasoning summaries if available
- JSON output for post-session updates

16. Structured outputs are extremely important

For a tutoring system with persistent state, free-form prose is not enough.

You’ll want the model to reliably produce machine-readable outputs for tasks like:
- syllabus generation
- lesson plan generation
- mastery updates
- session summaries
- extracted misconceptions
- assignment lists

So define schemas early.

For example, conceptually:
- `CourseManifest`
- `LessonPlan`
- `SessionSummary`
- `MasteryUpdate`
- `RetrievalPlan`

Even if the tutoring response to the student is plain text, the side effects should ideally be structured.

17. Event sourcing vs direct file mutation

A subtle but valuable design choice: consider storing changes as events, not just overwriting files.

Example events:
- course_initialized
- syllabus_approved
- lesson_started
- concept_mastery_updated
- assignment_created
- session_summarized
- persona_adjusted

Benefits:
- audit trail
- easier debugging
- easier rollback
- easier analytics
- possible future “replay” of course evolution

You can still materialize human-readable files from the event log.

18. Filesystem organization

A clean workspace layout will matter a lot.

Something like:

```text
course/
  manifest.yaml
  tutor_persona.md
  student_profile.yaml
  syllabus.md
  lessons/
    001-foundations.md
    002-bijections.md
  concepts/
    counting-principles.md
    inclusion-exclusion.md
  logs/
    session-2026-03-18.md
    session-2026-03-20.md
  assignments/
    hw-001.md
  reviews/
    misconceptions.md
    mastery.yaml
  transcripts/
    2026-03-18.jsonl
  index/
    metadata.db
    embeddings.db
```

This keeps the system understandable to the user and easy to back up.

19. Index implementation choices

You mentioned search-engine-like retrieval. You do not necessarily need a heavyweight vector database at first.

A strong local-first stack could be:

- SQLite for metadata
- BM25 / full-text search for lexical retrieval
- optional embeddings for semantic retrieval
- simple reranking
- graph edges stored in SQLite or files

For many tutoring workflows, a hybrid local index will be enough:
- fast
- portable
- inspectable
- low operational complexity

You can add embeddings later if lexical retrieval is insufficient.

20. The REPL’s real role

The Python REPL can be unusually useful in a tutoring environment, but it should be positioned carefully.

Good uses:
- build or update the syllabus programmatically
- compute spaced review schedules
- analyze session logs
- parse artifacts and construct indices
- solve or verify combinatorics examples
- generate plots/tables if useful
- maintain a concept dependency graph

Less ideal as the primary mechanism:
- being the only place where indexing logic lives
- being the only state store
- serving as a hidden mutable memory

If you want robustness, the REPL should operate over explicit files and databases, not replace them.

21. Pedagogical state is a first-class concern

A normal chat app stores text.
A tutoring app should store learning state.

This includes:
- what the student has seen
- what they understood
- what they misunderstood
- what should be reviewed
- what level of abstraction is comfortable
- what style of explanation works best

If you model this well, the tutoring quality improves dramatically.

For example, you may want a “misconception registry”:
- “confuses combinations with permutations”
- “treats independence too casually”
- “struggles to construct bijections”
- “can follow proofs but rarely invents them”

That’s gold for retrieval.

22. Adaptive syllabus evolution

The syllabus should not be static after generation.

In a personal tutor setting, the course should evolve based on:
- student interest
- performance
- pacing
- spontaneous questions
- time constraints

So distinguish:
- canonical planned syllabus
- actual taught path

The app should track both.

This lets the tutor say:
- “We planned to cover generating functions this week, but since inclusion-exclusion is still shaky, let’s reinforce that first.”

23. Long-context vs retrieval-first

Even if you have access to long-context models, retrieval-first still matters.

Why:
- lower cost
- higher reliability
- more transparent behavior
- easier debugging
- less prompt clutter
- better persistence semantics

Long context can help with:
- loading an entire lesson draft
- processing a transcript
- doing periodic consolidation

But everyday operation should still be retrieval-centric.

24. Prompt injection and trust boundaries

Because the model will read local files, you should think early about trust boundaries.

Potential issue:
- a retrieved file contains text that tries to override the tutor’s instructions
- external imported notes contain malicious or confusing content
- user scratch files include adversarial prompt-like content

Mitigations:
- mark sources by trust level
- separate system contract from retrieved content
- sanitize imported material
- teach the orchestrator not to elevate retrieved text above system policies
- optionally show provenance for each chunk

This matters more once the system starts ingesting arbitrary notes or PDFs.

25. Versioning and reproducibility

You are building a longitudinal system, so versioning helps a lot.

Version:
- prompts
- schemas
- lesson templates
- retrieval policies
- indexes
- generated syllabus revisions

Without versioning, it becomes hard to know whether a change in behavior came from:
- the model backend
- the prompt
- the retrieval policy
- the stored artifacts

26. Evaluation: don’t skip this

For this kind of app, evaluation should be built in from the start.

You want to assess:

A. Retrieval quality
Given a query or lesson state, did the system retrieve the right materials?

B. Tutoring continuity
Does the tutor maintain consistent persona and course progression across sessions?

C. Pedagogical usefulness
Are summaries accurate?
Are mastery updates sensible?
Are recommended next lessons reasonable?

D. State update correctness
Did the system write the right concepts/log entries/assignments back to storage?

A nice practical evaluation approach:
- create a few synthetic tutoring scenarios
- seed a small course archive
- test whether the system retrieves appropriate prior lessons and misconceptions
- compare generated session summaries against expected ones

27. MVP recommendation

If you want a sensible first version, keep it narrow.

MVP scope:
- one student
- one subject
- local filesystem workspace
- lexical retrieval + metadata filters
- optional simple embeddings later
- structured initialization flow
- lesson/session summary writing
- visible context pane in the TUI
- model backend adapter around an existing CLI

That will already be powerful.

Avoid in v1:
- multi-user support
- distributed vector DB
- complex autonomous planning loops
- hidden magical memory
- over-automation of grading and mastery estimation

28. Suggested system modules

A clean conceptual breakdown:

A. Workspace manager
Creates and loads course directories.

B. Schema layer
Defines manifests, lessons, logs, mastery, assignments.

C. Indexer
Builds searchable chunks and metadata.

D. Retrieval engine
Hybrid retrieval and reranking.

E. Orchestrator
Decides:
- what context to fetch
- when to call tools
- when to update memory

F. Model adapter
Wraps CLI/API backends.

G. Session manager
Handles pre-session, live session, post-session flows.

H. TUI frontend
Displays state and supports commands.

I. Consolidation engine
Produces summaries and updates durable artifacts.

29. Good design questions to answer early

Before implementation, I’d explicitly decide:

- What is the canonical source of truth: files, SQLite, or event log?
- What artifacts must be human-editable?
- What kinds of retrieval do you need on day one?
- How do you represent concepts and prerequisites?
- What structured outputs are required from the model?
- How does the user inspect retrieved context?
- How are post-session summaries generated and stored?
- How much autonomy should the model have in writing files?
- How do you handle syllabus revisions?
- How do you swap model backends without changing the core app?

30. A strong product heuristic

If the model disappeared and you only had the stored workspace, would the course still make sense?

If yes, your architecture is probably healthy.

That means:
- syllabus is visible
- lesson history is visible
- student progress is visible
- assignments are visible
- tutor persona is visible
- next steps are visible

The model then becomes an intelligent operator over this course state, not the sole container of it.

31. My recommended overall approach

I’d recommend this direction:

- local-first
- filesystem-backed canonical artifacts
- SQLite-backed metadata/indexing
- hybrid retrieval
- explicit tutor/student/course schemas
- post-session consolidation
- transparent TUI with context inspection
- model CLI as pluggable backend
- Python REPL as an analysis/tool layer, not the primary datastore

That gives you:
- RLM-like recursive retrieval behavior
- inspectability
- robustness
- portability
- a good user experience for tutoring

32. Concretely, what to build first

In order:

1. Define the course/workspace data model
2. Design the initialization contract and generated artifacts
3. Create the lesson/session lifecycle
4. Build indexing and retrieval over those artifacts
5. Build a minimal orchestrator that assembles context
6. Wrap one model CLI backend
7. Add TUI panes for chat, syllabus, and retrieved context
8. Add post-session summarization and mastery updates
9. Iterate on retrieval quality and pedagogy

If you want, next I can help you with one of these three follow-ups:

1. a proposed folder/schema design for the course workspace
2. a high-level orchestration flow for each tutoring turn
3. a TUI screen/layout and command design for the MVP
