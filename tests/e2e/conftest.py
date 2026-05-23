"""E2E fixtures: real LLM, real storage, seeded notebook content."""

import os
import pytest
from dotenv import load_dotenv
from pathlib import Path

from src.storage.markdown import MarkdownStore
from src.storage.index import NotebookIndex
from src.agent.graph import NotebookAgent

load_dotenv()


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests requiring OPENAI_API_KEY")


@pytest.fixture(scope="session", autouse=True)
def require_api_key():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — skipping e2e tests")


@pytest.fixture
def agent(tmp_path):
    """Real NotebookAgent backed by a seeded temp notebook."""
    from langchain_openai import ChatOpenAI

    nb = tmp_path / "notebook"
    store = MarkdownStore(nb)

    # Seed with realistic game content matching the actual notebook
    store.write_file("people.md", """\
---
type: characters
description: Named NPCs and their roles
---

## Roger
**Role:** Loadmaster
**Location:** Unknown
**Status:** Unknown
**Related:** [[Sorrell]], [[Jack]], [[Loadmaster's Key]]

- Lost the Loadmaster's key to Epsilon's secure storage.
- Believed the key was left at Sorrell's fishing hab.

## Rupert Sanford
**Role:** Custodian
**Location:** Unknown
**Status:** Active
**Related:** [[Kingston]]

- Complaining that cleaning supplies are going missing.
- Has discussed the issue with Kingston.

## Kingston
**Role:** Unknown
**Location:** Unknown
**Status:** Unknown
**Related:** [[Rupert Sanford]]

- Person Rupert Sanford has been talking to about the missing cleaning supplies.
""")

    store.write_file("places.md", """\
---
type: locations
description: Locations and facilities
---

## Facility Epsilon
**Explored:** partial
**Status:** active

- Main underground facility. Multiple crew quarters and secure storage.

## Facility Lambda
**Explored:** partial
**Status:** active

- Swamp facility. Radioactive area. Damaged reactor suspected cause.
""")

    store.write_file("todos.md", """\
---
type: todos
description: Quests, plans, and mysteries
---

## Unlock Epsilon Secure Storage
**Subtype:** quest
**Status:** open
**Requires:** [[Recover Loadmaster's Key]]
**Related:** [[Loadmaster's Key]], [[Facility Epsilon]]

- Use the Loadmaster's key to open Epsilon's secure storage.

## Recover Loadmaster's Key
**Subtype:** quest
**Status:** open
**Related:** [[Roger]], [[Sorrell]], [[Loadmaster's Key]]

- The key is probably at Sorrell's fishing hab.

## Lambda Radiation Cause
**Subtype:** mystery
**Status:** open
**Related:** [[Facility Lambda]]

- Why is the Lambda swamp radioactive? Best lead: damaged reactor.

## Rupert Sanford's Missing Supplies
**Subtype:** mystery
**Status:** open
**Related:** [[Rupert Sanford]], [[Kingston]]

- Cleaning supplies going missing. Petty theft? Story hook?
""")

    store.write_file("journal.md", """\
---
type: observations
description: Chronological session log
---

# Journal

## Session — initial
- Started exploring the underground facility.
""")

    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        temperature=0.3,
    )
    index = NotebookIndex(nb, embedding_provider="local")
    index.index_all(store)

    from src.storage.db import NotebookDB
    from src.storage.migrate import migrate
    db = NotebookDB(nb)
    migrate(nb, db)

    return NotebookAgent(llm, store, index, db)
