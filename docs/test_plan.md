# Test Plan

Goal: verify that the four core notebook behaviors work reliably — recording, querying, updating, and that the LLM prompts produce correct structured output. Not aiming for full coverage; aiming for confidence that the notebook does its job.

---

## Test Tiers

| Tier | What's real | What's mocked | Speed |
|------|-------------|---------------|-------|
| Unit | File system (temp dir) | LLM | < 1s |
| Integration | File system + ChromaDB (temp dir) | LLM | < 10s |
| E2E | Everything | Nothing | ~2 min |

Run with: `uv run --extra dev pytest`

Markers: `unit`, `integration`, `e2e`, `slow`. E2E tests are skipped automatically if `OPENAI_API_KEY` is not set.

File naming convention: `test_<name>_unit.py`, `test_<name>_integration.py`, `test_<name>_e2e.py`.

---

## Unit Tests

### `tests/unit/test_markdown_unit.py` — Storage round-trips

Real temp directory, no LLM.

| Class | What it covers |
|-------|---------------|
| `TestCreateEntity` | create entity, fields written correctly, appended to file |
| `TestUpdateEntity` | field updated in-place; new fields inserted when absent; history appended |
| `TestAppendToJournal` | session entry appended with date header |
| `TestParseIntoChunks` | one chunk per `##` header, entity_name/type/status/related populated |
| `TestGetKnownEntities` | returns dict grouped by type across multiple files |

### `tests/unit/test_entities_unit.py` — Extraction parsing

Mock LLM; tests that `EntityExtractor` parses responses and handles edge cases.

| Class | What it covers |
|-------|---------------|
| `TestExtract` | valid JSON, JSON in code fences, malformed JSON → empty result |
| `TestResolveEntities` | skip LLM for genuinely new names; call LLM for ambiguous; uncertain stays new |

### `tests/unit/test_nodes_unit.py` — Reflect node

Mock LLM; tests the relevance-filtering pass.

| Class | What it covers |
|-------|---------------|
| `TestReflectNode` | keeps relevant IDs; drops irrelevant; empty input skips LLM; all irrelevant → empty; malformed JSON passes through; unknown IDs ignored; chunk content unchanged |

### `tests/unit/test_respond_unit.py` — Contextual enrichment

Mock LLM and index; tests that respond fetches related context.

| Class | What it covers |
|-------|---------------|
| `TestRespondContextualEnrichment` | calls `hybrid_search` for record intent; calls for update intent; skips for chat; context content appears in LLM prompt |

---

## Integration Tests

Real `MarkdownStore` + `NotebookIndex` in a temp directory. LLM mocked.

### `tests/integration/test_storage_integration.py` — Write → search round-trip

| Class | What it covers |
|-------|---------------|
| `TestSearchAfterWrite` | new entity searchable; updated entity reflects in index |
| `TestMetadataFilters` | filter by entity_type; filter by status |
| `TestIncrementalIndexing` | unchanged file → 0 updates; changed file → updates |
| `TestOrphanRemoval` | deleted entity chunk removed on reindex |

---

## E2E Tests

Real LLM (`gpt-4o`, `temperature=0.3`). Each test gets a fresh temp notebook seeded with realistic game content (Roger, Rupert Sanford, Kingston, Facility Epsilon, Facility Lambda, four todos including the Recover Loadmaster's Key chain).

### `tests/e2e/test_record_e2e.py` — Recording new information

| Class | What it covers |
|-------|---------------|
| `TestRecordNewNPC` | new NPC appears in people.md with role; journal updated; response acknowledges |
| `TestRecordNewLocation` | new location appears in places.md |
| `TestRecordMultipleEntities` | both entities recorded in same turn |

### `tests/e2e/test_query_e2e.py` — Recall

| Class | What it covers |
|-------|---------------|
| `TestQueryKnownNPC` | returns Rupert details; returns Roger details |
| `TestQueryOpenQuests` | open quests returned; completed quests not hallucinated |
| `TestQueryOpenMysteries` | mysteries returned |
| `TestQueryDoesNotModifyFiles` | query leaves all files unchanged |

### `tests/e2e/test_update_e2e.py` — Corrections and status changes

| Class | What it covers |
|-------|---------------|
| `TestUpdateQuestStatus` | todo marked completed in file; response acknowledges |
| `TestCorrectNPCRole` | field updated in-place; no duplicate entry |
| `TestUpdateDoesNotCreateDuplicate` | re-stating existing info → still one entry |

### `tests/e2e/test_routing_e2e.py` — Intent classification

| Class | What it covers |
|-------|---------------|
| `TestRoutingRecord` | new ore creates entry; new NPC routes to record not update |
| `TestRoutingQuery` | question about known entity doesn't modify files |
| `TestRoutingUpdate` | mark-done modifies files; correction modifies files |
| `TestRoutingChat` | greeting and meta-question leave files unchanged |

### `tests/e2e/test_reflect_e2e.py` — Relevance filtering

| Class | What it covers |
|-------|---------------|
| `TestReflectionFiltersNoise` | codes query excludes rigs; person query excludes unrelated entities |

### `tests/e2e/test_contextual_response_e2e.py` — Contextual enrichment

| Class | What it covers |
|-------|---------------|
| `TestRecordSurfacesRelatedContext` | recording NPC event surfaces known info about that NPC; recording key completion surfaces next step; response is not just an echo |
| `TestUpdateSurfacesRelatedContext` | completing quest mentions what was unlocked; response is not bare "Noted." |

### `tests/e2e/test_status_propagation_e2e.py` — Cross-entity status propagation

| Class | What it covers |
|-------|---------------|
| `TestQuestCompletionPropagatesStatus` | completing key-recovery quest updates item status away from "lost"; both todo AND item updated; item not left stale after quest done |

### `tests/e2e/test_outcome_e2e.py` — Outcome field on completion

| Class | What it covers |
|-------|---------------|
| `TestOutcomeFieldOnCompletion` | completing quest adds `**Outcome:**` field; outcome is meaningful (not just "completed"); mystery resolution adds outcome; explicit mark-done also adds outcome; open todos do not get an outcome |

---

## What's Not Covered

- CLI rendering (Rich output) — manual verification only
- Conversation persistence (JSONL) — covered implicitly by e2e tests
- Dynamic file creation (`create_topic_file`) — low priority, test manually when first triggered
- Anthropic provider — spot-check manually; prompt behavior should be equivalent
