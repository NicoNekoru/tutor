# Tutor RLM

A TUI-based tutoring application inspired by Recursive Language Model (RLM) architecture.

## Motivations

Standard chat-based tutoring applications face fundamental limitations:

- **Context Window Constraints**: LLMs can only hold limited information in their prompt, causing them to forget earlier parts of long tutoring sessions
- **Chat Drift**: Without persistent state, the model's behavior becomes inconsistent over time as it loses track of the pedagogical context
- **Black Box Nature**: Users cannot inspect what the model "remembers" or why it gave a particular explanation
- **Scalability Issues**: As course material grows, the approach becomes increasingly ineffective

The Recursive Language Model (RLM) architecture addresses these limitations by providing a principled approach to building effective, scalable, and transparent tutoring systems:

### Core Advantages of RLM Architecture

1. **Persistent Pedagogical Memory**
   - Maintains canonical state on disk in structured, human-readable formats:
     - Markdown for syllabus, lesson plans, concept explanations
     - YAML/JSON/TOML for metadata and machine-readable state (student profiles, tutor persona)
     - SQLite for logs, indexing metadata, embeddings, and event records
   - Enables long-term tracking of learning progress, misconceptions, and instructional history that survives model restarts and session boundaries
   - Stores not just what was said, but what was learned, mastered, and struggled with

2. **Effective Unlimited Context via Retrieval**
   - Keeps the active prompt small while providing access to arbitrarily large course materials
   - Uses hybrid retrieval (lexical + semantic + structural) to find pedagogically relevant context
   - Allows the model to search, inspect, summarize, and update course memory rather than trying to hold everything in-context
   - Implements the RLM principle: "keep the active prompt small, recursively retrieve and inspect relevant state, use tools to reason over the persistent context"

3. **Transparency & Inspectability**
   - Makes tutoring memory visible: users can see what was retrieved, why it was retrieved, and what files were updated
   - Shows retrieved documents, ranked chunks, lesson references, and notes used in response generation
   - Builds trust and enables debugging by exposing the model's reasoning process over persistent state
   - Solves the "black box" problem by making the tutoring system's inner workings inspectable rather than hidden in model weights
   - Aligns with the RLM spirit: the model is not magically remembering; it is operating over tools and state

4. **Consistent & Personalized Pedagogy**
   - Maintains stable tutor persona, course goals, and learning state across sessions (no "chat drift")
   - Tracks rich learning state: what the student has seen, understood, misunderstood, what should be reviewed, preferred explanation styles, and comfort with abstraction levels
   - Enables adaptive instruction based on mastery-aware retrieval and personalized learning state
   - Supports explicit representation of tutor contracts (teaching style, rigor level, preferred methods) and student profiles (goals, prior knowledge, learning preferences)
   - Supports sophisticated features like misconception registries that are gold for retrieval and targeted instruction

5. **Scalable Design**
   - Supports arbitrarily large course materials through efficient retrieval rather than context window limitations
   - Uses SQLite/FTS5 for metadata and indexing with optional embeddings for semantic retrieval
   - Separates concerns cleanly: workspace management, indexing, retrieval, orchestration, and model adaption
   - Enables the system to grow with the curriculum without degrading performance

This transforms the model from a stateless chatbot into an intelligent operator over a persistent knowledge base, creating a more reliable, inspectable, personalized, and scalable tutoring system where the course state remains visible and usable even if the model component changes.

## Features

- Persistent pedagogical memory with file-based course artifacts
- Hybrid retrieval (lexical + semantic + structural)
- Knowledge graph representation of concepts
- Transparent context inspection
- Model-agnostic adapter layer
- Python REPL tool for advanced operations

## Quick Start

### 1. Install dependencies

```bash
# Using bun (for TypeScript app)
bun install

# Using uv (for Python tools)
uv sync
```

### 2. Initialize a course

```bash
bun run src/index.ts init --course-id combinatorics --subject combinatorics
```

### 3. Start the TUI

```bash
bun run src/index.ts start --course-id combinatorics
```

## Project Structure

```
tutor/
├── src/
│   ├── schemas/         # TypeScript type definitions
│   ├── workspace/       # Workspace management (file I/O)
│   ├── indexer/         # Chunk extraction and SQLite indexing
│   ├── retrieval/       # Search engine with hybrid ranking
│   ├── adapter/         # Model backend adapter (CLI, API, etc.)
│   ├── orchestrator/    # Turn logic, context assembly, tool routing
│   ├── consolidation/  # Post-session summarization
│   └── tui/             # Terminal UI with 4-pane layout
├── courses/             # Course workspaces (created at runtime)
├── python_tools/        # Python utilities (REPL worker, math tools)
└── pyproject.toml       # Python dependencies (uv)
```

## Architecture

The system separates canonical state (files) from dynamic context (model prompt). Core components:

1. **Workspace**: Human-readable files on disk (syllabus.md, lessons/_.md, concepts/_.md, etc.)
2. **Index**: SQLite with FTS5 for fast retrieval and metadata
3. **Retrieval**: Hybrid search combining lexical, semantic, and structural signals
4. **Orchestrator**: Assembles context, classifies intent, executes tools
5. **Model Adapter**: Pluggable interface to various LLM backends
6. **TUI**: Four-pane interface showing dialogue, navigation, context, and tools

## Configuration

Model backends are configured via environment variables or config files. Example for opencode:

```bash
export TUTOR_MODEL_BACKEND=opencode
export OPENCODE_API_KEY=...
```

## Development

```bash
# Run in watch mode
bun run dev

# Build
bun run build

# Lint
bun run lint
```

## Note

This is an early prototype. The architecture is inspired by the RLM paper and emphasizes:

- Inspectability (you can see what was retrieved)
- Persistence (all course artifacts stored in plain files)
- Extensibility (swap model backends, add retrieval strategies)
