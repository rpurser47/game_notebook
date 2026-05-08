# Test Plan

Goal: verify that the four core notebook behaviors work reliably — recording, querying, updating, and that the LLM prompts produce correct structured output. Not aiming for full coverage; aiming for confidence that the notebook does its job.

---

## Test Tiers

| Tier | What's real | What's mocked | Speed |
|------|-------------|---------------|-------|
| Unit | File system (temp dir) + SQLite (in-memory) | LLM | < 1s |
| Integration | File system + SQLite (temp dir) + ChromaDB (temp dir) | LLM | < 10s |
| E2E | Everything | Nothing | ~2 min |

Run with: `uv run --extra dev pytest`

Markers: `unit`, `integration`, `e2e`, `slow`. E2E tests are skipped automatically if `OPENAI_API_KEY` is not set.

File naming convention: `test_<name>_unit.py`, `test_<name>_integration.py`, `test_<name>_e2e.py`.

---

## Unit Tests

### `tests/unit/test_db_unit.py` — DB round-trips

Real SQLite in-memory, no LLM.

| Class | What it covers |
|-------|---------------|
| `TestCreateEntity` | INSERT entity, fields written, aliases created |
| `TestUpdateEntityField` | UPDATE field; facts row written with provenance |
| `TestRelationships` | INSERT relationship; fetch by from_id; fetch by to_id |
| `TestConflictDetection` | proposed value differs from DB → conflict dict returned |
| `TestAliasLookup` | entity found by alias; new alias inserted on coreference |
| `TestFactsLog` | each field update produces immutable facts row with source/confidence |

### `tests/unit/test_markdown_unit.py` — Markdown rendering

Real temp directory, no LLM.

| Class | What it covers |
|-------|---------------|
| `TestRenderEntity` | entity rendered from DB row with correct field order |
| `TestAppendToJournal` | session entry appended with date header |
| `TestParseIntoChunks` | one chunk per `##` header, entity_name/type/status/related populated |

### `tests/unit/test_entities_unit.py` — Extraction parsing

Mock LLM; tests that `EntityExtractor` parses responses and handles edge cases.

| Class | What it covers |
|-------|---------------|
| `TestExtract` | valid JSON, JSON in code fences, malformed JSON → empty result |
| `TestExtractProvenance` | source and confidence fields present on all extracted items |
| `TestResolveEntities` | skip LLM for genuinely new names; call LLM for ambiguous; uncertain stays new |

### `tests/unit/test_nodes_unit.py` — Reflect and ConflictCheck nodes

Mock LLM; tests relevance-filtering and conflict detection.

| Class | What it covers |
|-------|---------------|
| `TestReflectNode` | keeps relevant IDs; drops irrelevant; empty input skips LLM; all irrelevant → empty; malformed JSON passes through; unknown IDs ignored; chunk content unchanged |
| `TestConflictCheckNode` | no conflict when values match; conflict dict when values differ; missing entity skips conflict; multiple conflicts returned |

### `tests/unit/test_respond_unit.py` — Contextual enrichment

Mock LLM and index; tests that respond fetches structured state first, semantic second.

| Class | What it covers |
|-------|---------------|
| `TestRespondContextualEnrichment` | DB results appear before semantic chunks in prompt; calls `hybrid_search` for record intent; calls for update intent; skips semantic for chat; context content appears in LLM prompt |

---

## Integration Tests

Real `NotebookDB` + `MarkdownStore` + `NotebookIndex` in a temp directory. LLM mocked.

### `tests/integration/test_storage_integration.py` — Write → search round-trip

| Class | What it covers |
|-------|---------------|
| `TestDBWriteAndQuery` | entity written to DB; re-read by name; re-read by alias |
| `TestSearchAfterWrite` | entity prose embedded; semantic search returns it |
| `TestMetadataFilters` | filter by entity_type; filter by status |
| `TestIncrementalIndexing` | unchanged entity → 0 vector updates; changed prose → re-embeds |
| `TestOrphanRemoval` | deleted entity chunk removed on reindex |
| `TestMarkdownRendered` | markdown file matches DB state after write |

### `tests/integration/test_provenance_integration.py` — Facts log

| Class | What it covers |
|-------|---------------|
| `TestFactsOnCreate` | new entity writes initial facts rows |
| `TestFactsOnUpdate` | field update writes old_value and new_value |
| `TestConflictResolution` | confirmed override writes both values with turn_text |

---

## E2E Tests

Real LLM (`gpt-4o`, `temperature=0.3`). Each test gets a fresh temp notebook seeded with realistic game content (Roger, Rupert Sanford, Kingston, Facility Epsilon, Facility Lambda, four todos including the Recover Loadmaster's Key chain) loaded into both the DB and vector index.

### `tests/e2e/test_record_e2e.py` — Recording new information

| Class | What it covers |
|-------|---------------|
| `TestRecordNewNPC` | new NPC appears in DB and people.md with role; journal updated; response acknowledges |
| `TestRecordNewLocation` | new location appears in DB and places.md |
| `TestRecordMultipleEntities` | both entities recorded in DB in same turn |
| `TestRecordProvenanceSet` | new entities have source=player_observed in facts table |

### `tests/e2e/test_query_e2e.py` — Recall

| Class | What it covers |
|-------|---------------|
| `TestQueryKnownNPC` | returns Rupert details from DB; returns Roger details |
| `TestQueryOpenQuests` | open quests from DB; completed quests not hallucinated |
| `TestQueryOpenMysteries` | mysteries returned |
| `TestQueryDoesNotModifyFiles` | query leaves DB and all files unchanged |
| `TestQueryUsesDBFirst` | response contains field values that are in DB, not hallucinated |

### `tests/e2e/test_update_e2e.py` — Corrections and status changes

| Class | What it covers |
|-------|---------------|
| `TestUpdateQuestStatus` | todo marked completed in DB and file; response acknowledges |
| `TestCorrectNPCRole` | field updated in-place in DB; no duplicate entry; facts log has old value |
| `TestUpdateDoesNotCreateDuplicate` | re-stating existing info → still one DB row |

### `tests/e2e/test_conflict_e2e.py` — Conflict detection

| Class | What it covers |
|-------|---------------|
| `TestConflictDetected` | contradicting known role → response describes discrepancy, no write |
| `TestConflictConfirmed` | user confirms override → DB updated, both values in facts log |
| `TestNoConflictOnSameValue` | restating same value → no conflict, no write |

### `tests/e2e/test_routing_e2e.py` — Intent classification

| Class | What it covers |
|-------|---------------|
| `TestRoutingRecord` | new ore creates DB entry; new NPC routes to record not update |
| `TestRoutingQuery` | question about known entity doesn't modify DB or files |
| `TestRoutingUpdate` | mark-done modifies DB and files; correction modifies DB and files |
| `TestRoutingChat` | greeting and meta-question leave DB and files unchanged |

### `tests/e2e/test_reflect_e2e.py` — Relevance filtering

| Class | What it covers |
|-------|---------------|
| `TestReflectionFiltersNoise` | codes query excludes rigs; person query excludes unrelated entities |

### `tests/e2e/test_contextual_response_e2e.py` — Contextual enrichment

| Class | What it covers |
|-------|---------------|
| `TestRecordSurfacesRelatedContext` | recording NPC event surfaces DB fields for that NPC; recording key completion surfaces next step; response is not just an echo |
| `TestUpdateSurfacesRelatedContext` | completing quest mentions what was unlocked; response is not bare "Noted." |
| `TestDBFactsBeforeSemanticInPrompt` | verified via prompt logging: DB rows appear before semantic chunks |

### `tests/e2e/test_status_propagation_e2e.py` — Cross-entity status propagation

| Class | What it covers |
|-------|---------------|
| `TestQuestCompletionPropagatesStatus` | completing key-recovery quest updates item status in DB and file; both todo AND item updated; item not left stale after quest done |

### `tests/e2e/test_outcome_e2e.py` — Outcome field on completion

| Class | What it covers |
|-------|---------------|
| `TestOutcomeFieldOnCompletion` | completing quest adds `**Outcome:**` field in DB and file; outcome is meaningful (not just "completed"); mystery resolution adds outcome; explicit mark-done also adds outcome; open todos do not get an outcome |

### `tests/e2e/test_coreference_e2e.py` — Entity alias resolution

| Class | What it covers |
|-------|---------------|
| `TestAliasResolution` | "the innkeeper" resolves to canonical entity in DB; alias written to aliases table; subsequent reference uses same canonical entity |

---

## What's Not Covered

- CLI rendering (Rich output) — manual verification only
- Conversation persistence (JSONL) — covered implicitly by e2e tests
- Dynamic file creation (`create_topic_file`) — low priority, test manually when first triggered
- Anthropic provider — spot-check manually; prompt behavior should be equivalent
- SQLite schema migration — manual verification on first run
