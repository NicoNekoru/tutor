# Tutor RLM

A TUI-based tutoring application inspired by Recursive Language Model (RLM) architecture.

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

1. **Workspace**: Human-readable files on disk (syllabus.md, lessons/*.md, concepts/*.md, etc.)
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
