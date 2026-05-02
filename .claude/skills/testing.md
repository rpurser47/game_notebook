# Testing Skill

Guidelines for writing and running Python tests in this project.

## Running Tests

**Always use `uv run pytest`** — never invoke pytest directly.

```powershell
# Run all tests
uv run pytest

# Run by marker
uv run pytest -m unit
uv run pytest -m integration
uv run pytest -m e2e
uv run pytest -m "not slow"

# Run a single file
uv run pytest tests/unit/markdown_unit.py

# Run with output
uv run pytest -v -s
```

## Code Quality

Run `ruff` before running tests or committing. Fix all issues first.

```powershell
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

There is no pylint or black in this project — ruff handles both formatting and linting.

## Test Directory Structure

```
tests/
├── conftest.py              # Shared fixtures (paths, tmp dirs, LLM stubs)
├── unit/                    # Fast, mocked — one file per source file
│   ├── markdown_unit.py
│   ├── index_unit.py
│   ├── entities_unit.py
│   ├── nodes_unit.py
│   ├── graph_unit.py
│   └── ...
├── integration/             # Real dependencies, no LLM calls
│   └── test_*.py
└── e2e/                     # Full pipeline with real LLM
    └── test_notebook_e2e.py
```

### Source-to-Test Mapping

| Source File | Unit Test File |
|-------------|----------------|
| `src/storage/markdown.py` | `tests/unit/markdown_unit.py` |
| `src/storage/index.py` | `tests/unit/index_unit.py` |
| `src/extraction/entities.py` | `tests/unit/entities_unit.py` |
| `src/agent/nodes.py` | `tests/unit/nodes_unit.py` |
| `src/agent/graph.py` | `tests/unit/graph_unit.py` |
| `src/agent/state.py` | `tests/unit/state_unit.py` |
| `src/cli/interface.py` | `tests/unit/interface_unit.py` |
| `src/main.py` | `tests/unit/main_unit.py` |

Every new source file needs a corresponding unit test file before merging.

## Test Markers

```python
@pytest.mark.unit         # < 1s, all dependencies mocked
@pytest.mark.integration  # < 10s, real file system, no LLM
@pytest.mark.e2e          # < 30s, full pipeline with real LLM
@pytest.mark.slow         # > 10s, opt-in only
```

Register markers in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "unit: fast unit tests with mocked dependencies",
    "integration: tests with real file system and ChromaDB",
    "e2e: full pipeline tests with real LLM calls",
    "slow: tests that take longer than 10 seconds",
]
```

## Mocking Strategy

### Unit Tests — mock everything external
- Mock the LLM (`ChatOpenAI`, `ChatAnthropic`) to return controlled JSON
- Mock ChromaDB collection calls
- Use `tempfile.TemporaryDirectory()` for file system operations — don't mock `MarkdownStore` itself

### Integration Tests — real file system, mock LLM
- Use real `MarkdownStore` + `NotebookIndex` against a temp directory
- Mock only the LLM to avoid API costs and flakiness
- Validates that storage, indexing, and parsing work end-to-end

### E2E Tests — real LLM, real everything
- Only mock environment variables and config paths
- Never mock `MarkdownStore`, `NotebookIndex`, `EntityExtractor`, or agent nodes
- Use a dedicated temp notebook directory; clean up after each test

## File Operations Pattern

Prefer real file operations in a temp directory over mocking `MarkdownStore`:

```python
import tempfile
from pathlib import Path
from src.storage.markdown import MarkdownStore

def test_create_entity():
    with tempfile.TemporaryDirectory() as tmp:
        store = MarkdownStore(Path(tmp))
        store.create_entity("people.md", "Kira", "character", {"role": "blacksmith"})
        content = store.read_file("people.md")
        assert "## Kira" in content
        assert "blacksmith" in content
```

## LLM Mocking Pattern

Mock at the LLM instance level, returning pre-set JSON:

```python
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content='{"intent": "record"}')
    return llm
```

For extraction tests, return realistic JSON matching the `ExtractionResult` schema:

```python
extraction_response = {
    "observations": ["Met blacksmith Kira in Millhaven"],
    "entities": [{"name": "Kira", "type": "character", "is_new": True, "fields": {"role": "blacksmith"}}],
    "updates": [],
    "relationships": []
}
llm.invoke.return_value = MagicMock(content=json.dumps(extraction_response))
```

## Missing Files — Fail, Don't Skip

When a required fixture file is missing, fail fast:

```python
# WRONG
if not fixture_path.exists():
    pytest.skip("fixture missing")

# CORRECT
if not fixture_path.exists():
    pytest.fail(f"Required fixture not found: {fixture_path}")

# CORRECT — skip only for optional external deps
if not os.getenv("OPENAI_API_KEY"):
    pytest.skip("OPENAI_API_KEY not set — skipping e2e test")
```

## Path Management

Use fixtures for shared paths, not relative path construction in test bodies:

```python
# conftest.py
@pytest.fixture
def notebook_dir(tmp_path):
    """Fresh notebook directory for each test."""
    return tmp_path / "notebook"

@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"
```

## Test Requirements

- All new or edited tests must pass before moving on
- Never leave failing tests — fix them or explicitly remove them
- Test file names must be unique project-wide
- Run the full suite before committing

## What to Test for This Project

The core notebook behaviors worth covering:

| Area | Key Tests |
|------|-----------|
| `MarkdownStore` | parse_into_chunks, create_entity, update_entity, append_to_journal |
| `NotebookIndex` | upsert/search round-trip, hash change detection, hybrid_search filters |
| `EntityExtractor` | extraction JSON parsing, coreference skip for new entities, resolve logic |
| Agent routing | intent classification → correct graph branch |
| Write node | new entity creates file section, relationships appended |
| Modify node | field update changes correct line, history entry appended |
| Query flow | analyze_query produces correct filters, retrieve returns relevant chunks |
