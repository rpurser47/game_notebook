"""E2E: reflection step filters irrelevant chunks from query results."""

import pytest


@pytest.mark.e2e
class TestReflectionFiltersNoise:
    def test_codes_query_excludes_rigs(self, agent):
        """'What needs a code?' should not return drilling rigs."""
        # Seed some rigs and codes so the index has both
        agent.store.write_file("things.md", """\
---
type: items
description: Items and equipment
---

## Surface Hab Storage Code
**Category:** access-code
**Status:** unknown

- Numeric code for the locked storage at the surface hab. Unknown.

## Epsilon Storage Room Code
**Category:** access-code
**Status:** unknown

- Numeric code for the Epsilon storage room. Unknown.

## Loadmaster's Key
**Category:** key-item
**Status:** found
**Related:** [[Roger]], [[Epsilon Secure Storage]]

- Key to Epsilon's secure storage. Found at Sorrell's fishing hab.

## Rig #1
**Category:** equipment
**Status:** active

- Drilling rig on Level 1. Mining status unknown.

## Rig #3
**Category:** equipment
**Status:** active

- Drilling rig on Level 3. Mining kaloxite.

## Mk2 Cargo Drone
**Category:** equipment
**Status:** unknown

- Blueprint or unlock condition unknown.
""")
        agent.index.index_all(agent.store)

        response = agent.chat("what else needs a code?")
        lower = response.lower()

        # Codes and keys should appear
        assert "code" in lower or "key" in lower or "storage" in lower

        # Rigs are clearly irrelevant to a codes query
        assert "rig #1" not in lower
        assert "rig #3" not in lower
        assert "mk2 cargo drone" not in lower

    def test_person_query_excludes_unrelated_entities(self, agent):
        """Asking about a specific person should not surface unrelated items."""
        response = agent.chat("What do I know about Rupert Sanford?")
        lower = response.lower()

        assert "rupert" in lower or "custodian" in lower or "cleaning" in lower
        # Facility Lambda and Roger are in the seed data but unrelated to Rupert
        assert "lambda" not in lower
        assert "reactor" not in lower
