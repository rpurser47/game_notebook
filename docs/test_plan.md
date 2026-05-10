# Test Plan

Goal: verify that the four core notebook behaviors work reliably — recording, querying, updating, and that the LLM prompts produce correct structured output. Not aiming for full coverage; aiming for confidence that the notebook does its job.

---

## Test Tiers

| Tier | What's real | What's mocked | Speed |
|------|-------------|---------------|-------|
| Unit | File system (temp dir) + SQLite (real file in tmp) | LLM, index (where not under test) | < 1s |
| Integration | File system + SQLite (temp dir) + ChromaDB (temp dir) | LLM | < 30s |
| E2E | Everything | Nothing | ~2 min |

Run with: `uv run --extra dev pytest`

Markers: `unit`, `integration`, `e2e`, `slow`. E2E tests are skipped automatically if `OPENAI_API_KEY` is not set.

File naming convention: `test_<name>_unit.py`, `test_<name>_integration.py`, `test_<name>_e2e.py`.

---

## Shared Fixtures

`tests/conftest.py` provides:
- `notebook_dir` — fresh `tmp_path / "notebook"` directory
- `store` — `MarkdownStore` backed by `notebook_dir`
- `seeded_store` — `MarkdownStore` pre-populated with `people.md`, `todos.md`, and `journal.md`

---

## Unit Tests

### `tests/unit/test_db_unit.py` — DB round-trips

Real SQLite in a temp directory, no LLM.

| Class | What it covers |
|-------|---------------|
| `TestCreateEntity` | INSERT entity; fields written; case-insensitive lookup; idempotent on (name, type) |
| `TestUpdateEntityField` | UPDATE field; overwrite on second upsert; status syncs entity row; fields hydrated on get |
| `TestFactsLog` | each field write produces facts row with source/confidence/turn_text; update records old_value |
| `TestRelationships` | INSERT relationship; idempotent; related hydrated on entity get |
| `TestAliasLookup` | entity found by alias; idempotent; aliases hydrated on get |
| `TestConflictDetection` | no conflict when field absent; no conflict on empty old_value; no conflict when new equals DB; conflict when explicit old_value is wrong; only flags conflicting item in batch; unknown entity skipped; exploration update not a conflict |
| `TestGetKnownEntities` | returns names grouped by type; empty DB returns `{}` |

### `tests/unit/test_markdown_unit.py` — Markdown rendering

Real temp directory, no LLM.

| Class | What it covers |
|-------|---------------|
| `TestCreateEntity` | entity rendered with correct field labels; appends to existing file without clobbering |
| `TestUpdateEntity` | field updated in-place; missing entity returns False; history entry appended; no duplicate section on update |
| `TestAppendToJournal` | session header added; multiple observations; preserves existing content; creates journal if missing |
| `TestParseIntoChunks` | one chunk per `##` header; entity_type from frontmatter; status and related fields populated; empty/missing file → empty list |
| `TestGetKnownEntities` | entities grouped by type across files; empty notebook → empty dict |

### `tests/unit/test_entities_unit.py` — Extraction parsing

Mock LLM; tests that `EntityExtractor` parses responses and handles edge cases.

| Class | What it covers |
|-------|---------------|
| `TestExtract` | valid JSON; JSON in code fences (` ```json ` and plain ` ``` `); malformed JSON → empty result; empty arrays; update parsing |
| `TestResolveEntities` | skip LLM for genuinely new name; call LLM when name exists in known; uncertain coreference → entity stays new; `is_new: false` skips coreference; batch with mixed new/known → LLM called only for ambiguous |

### `tests/unit/test_nodes_unit.py` — Reflect node

Mock LLM; tests relevance-filtering logic.

| Class | What it covers |
|-------|---------------|
| `TestReflectNode` | keeps relevant IDs; drops irrelevant; empty input skips LLM; all irrelevant → empty list; malformed JSON passes all chunks through; unknown IDs in LLM response ignored; chunk content unchanged after filter |

### `tests/unit/test_persist_unit.py` — Persist and ConflictCheck nodes

Real DB + MarkdownStore in temp dir; mock LLM and index.

| Class | What it covers |
|-------|---------------|
| `TestConflictCheckNode` | no conflicts when no updates; no conflict for routine update with empty old_value; conflict detected when explicit old_value is wrong; state passed through unchanged |
| `TestPersistNewEntity` | new character written to DB; new character appears in markdown; existing entity not duplicated; observations written to journal (record); observations not written for update intent; `files_modified` returned |
| `TestPersistFieldUpdate` | correction updates DB field; correction updates markdown in-place; old value in facts log; turn_text stored in facts; status update syncs entity row; completing todo writes Outcome to markdown; completing todo writes Outcome to DB; unknown entity update skipped gracefully |
| `TestPersistRelationships` | relationship written to DB; unknown from_entity skipped gracefully |
| `TestPersistTriggersReindex` | `index_file` called for each modified file; not called when nothing modified |

### `tests/unit/test_respond_unit.py` — Contextual enrichment

Mock LLM and index; tests that respond fetches structured state first, semantic second.

| Class | What it covers |
|-------|---------------|
| `TestRespondContextualEnrichment` | calls `hybrid_search` for record intent; calls for update intent; skips semantic for chat; chunk content appears in LLM prompt |

### `tests/unit/test_e2e_fixture.py` — DB seeding requirement

Documents the contract that e2e fixtures must seed the DB via `migrate()`.

| Class | What it covers |
|-------|---------------|
| `TestDBMustBeSeededFromMarkdown` | DB empty before migrate; DB populated after migrate; empty DB makes Roger look new (is_new: true path); migrated DB shows Roger as known; migrated DB shows quest as known |

---

## Integration Tests

Real `NotebookDB` + `MarkdownStore` + `NotebookIndex` in a temp directory. LLM mocked.

### `tests/integration/test_db_integration.py` — DB + MarkdownStore together

| Class | What it covers |
|-------|---------------|
| `TestDBWriteAndQuery` | entity written and read back; read by alias; get_entities_by_type; filtered by status; filtered by subtype |
| `TestProvenanceLog` | initial insert creates fact row; field update records old and new values with source/turn_text; multiple fields each get their own fact row |
| `TestConflictDetectionRealistic` | exploration update not blocked; status progression not blocked; explicit wrong prior value blocked; batch only flags real conflict |
| `TestMarkdownConsistency` | DB and markdown agree after a migration-style write |

### `tests/integration/test_storage_integration.py` — Write → index → search round-trip

| Class | What it covers |
|-------|---------------|
| `TestNewEntityIsSearchable` | character found by role after index; location found by name; journal entry searchable |
| `TestUpdatedEntityReflectsInIndex` | updated field appears in search; old content superseded after update |
| `TestMetadataFilters` | filter by entity_type returns only that type; status=open excludes completed; semantic + type filter |
| `TestIncrementalIndexing` | unchanged file returns 0 updates; changed file returns nonzero; stats reflect indexed chunks |
| `TestOrphanRemoval` | deleted entity chunk removed on reindex |

### `tests/integration/test_correction_integration.py` — Full correction flow (all three layers)

Real DB + MarkdownStore + NotebookIndex; persist node drives writes.

| Class | What it covers |
|-------|---------------|
| `TestCorrectionAllLayersUpdated` | DB updated after correction; markdown updated after correction; index updated (new role searchable); old value absent from index; facts log records old/new provenance; DB and markdown agree after correction |
| `TestQuestCompletionAllLayersUpdated` | DB status updated; markdown status updated; Outcome written to DB; Outcome written to markdown; index reflects completed status (excluded from open filter) |
| `TestNewEntityAllLayersPopulated` | new entity searchable immediately after persist; DB and markdown consistent |

### `tests/integration/test_index_update.py` — Embedding correctness after updates

Real NotebookIndex + MarkdownStore. No LLM.

| Class | What it covers |
|-------|---------------|
| `TestDocumentContentAfterUpdate` | stored document reflects new field value; old value absent; multiple field updates all reflected; completed status reflected in stored document |
| `TestMetadataAfterUpdate` | status metadata updated after completion; entity_type metadata preserved; entity_name metadata preserved |
| `TestMetadataFilterAfterUpdate` | completed quest excluded from open filter; completed quest returned by completed filter; todo update doesn't pollute character type filter |
| `TestHashTrackingAfterUpdate` | hash updated after field change; sibling entity hash stable after unrelated update; unchanged file returns 0 on second pass; changed file returns nonzero |
| `TestSemanticSearchAfterUpdate` | new value semantically retrievable; Outcome field semantically retrievable; history note semantically retrievable |

### `tests/integration/test_task_list_update.py` — Open task list correctness across query → update → re-query

Real DB + MarkdownStore + NotebookIndex; persist node drives writes.

| Class | What it covers |
|-------|---------------|
| `TestOpenTaskListAfterCompletion` | all four tasks open before any update; completed task removed from open list; remaining tasks still open; open count decreases by one; completing two tasks removes both; DB open count matches index open count; subtype filter correct after completion |

---

## E2E Tests

Real LLM (`gpt-4o`, `temperature=0.3`). Each test gets a fresh temp notebook seeded with realistic game content (Roger, Rupert Sanford, Kingston, Facility Epsilon, Facility Lambda, four todos including the Recover Loadmaster's Key chain) loaded into both the DB and vector index.

**Important**: the e2e `conftest.py` fixture (`tests/e2e/conftest.py`) seeds markdown files but does not currently call `migrate()` to populate the DB. Until that is fixed, the LLM will not see `known_entities` and may treat existing NPCs as new. The `tests/unit/test_e2e_fixture.py` file documents this requirement.

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
- `migrate.py` correctness beyond what `test_e2e_fixture.py` exercises — the fixture tests prove the DB seeding contract but don't exhaustively test field parsing edge cases
