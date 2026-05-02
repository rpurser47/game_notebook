# Game Notebook

A conversational agentic notebook for 1st-person RPG games. It records observations, tracks entities, and helps recall information — like talking to someone with perfect memory.

## Features

- **Conversational interface**: Natural dialogue, no visible internal mechanics
- **Entity tracking**: People, places, items, quests, mysteries
- **Semantic search**: Find information by meaning, not just keywords
- **Structured queries**: Filter by entity type, status, relationships
- **Persistent storage**: Markdown files you can read and edit directly
- **Automatic entity extraction**: LLM-powered extraction and coreference resolution

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd game_notebook

# Set up environment with mise
mise trust
mise install

# Install dependencies
uv sync
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Set your API keys and preferences:

```env
# LLM Provider (openai or anthropic)
LLM_PROVIDER=openai

# API Keys
OPENAI_API_KEY=your-key-here
# or
ANTHROPIC_API_KEY=your-key-here

# Embedding (local or openai)
EMBEDDING_PROVIDER=local

# Notebook path
NOTEBOOK_PATH=./notebook
```

## Usage

```bash
# Run the notebook
uv run python -m src.main

# Or after uv sync
uv run notebook
```

### Commands

| Command | Description |
|---------|-------------|
| `/quit`, `/exit` | Exit the notebook |
| `/status` | Show index statistics |
| `/reindex` | Force full reindex |
| `/clear` | Clear conversation history |
| `/help` | Show help |

### Examples

```
> met a blacksmith named Kira in Millhaven
Added Kira — blacksmith in Millhaven.

> she mentioned her brother went missing near the old mines
Noted. Added Kira's brother as missing near the old mines.

> what quests are open?
You've got three open quests: Find Kira's brother, unlock the secure storage,
and repair the Lambda reactor.

> what do I know about Kira?
Kira is a blacksmith in Millhaven. Her brother went missing near the old mines —
you haven't resolved that yet.
```

## Architecture

See [docs/design.md](docs/design.md) for the full design document.

```
src/
├── agent/          # LangGraph agent
│   ├── graph.py    # Graph definition
│   ├── nodes.py    # Node implementations
│   └── state.py    # State schema
├── storage/        # Persistence layer
│   ├── markdown.py # Markdown file operations
│   └── index.py    # Vector index (ChromaDB)
├── extraction/     # Entity extraction
│   └── entities.py # LLM-based extraction
├── cli/            # Terminal interface
│   └── interface.py
└── main.py         # Entry point
```

## Notebook Structure

Your game data lives in the `notebook/` directory:

| File | Purpose |
|------|---------|
| `journal.md` | Chronological observations |
| `people.md` | Characters/NPCs |
| `locations.md` | Places |
| `todo.md` | Quests/objectives |
| `mysteries.md` | Unresolved questions |
| `resources.md` | Items and materials |
| `*.md` | Additional topic files as needed |

Files use YAML frontmatter and standardized entity headers — see existing files for examples.

## License

MIT
