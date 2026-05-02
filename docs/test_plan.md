# Test Plan

Goal: verify that the four core notebook behaviors work reliably — recording, querying, updating, and that the LLM prompts produce correct structured output. Not aiming for full coverage; aiming for confidence that the notebook does its job.

---

## Test Tiers

| Tier | What's real | What's mocked | Speed |
|------|-------------|---------------|-------|
| Unit | File system (temp dir) | LLM | < 1s |
| Integration | File system + ChromaDB (temp dir) | LLM | < 10s |
| E2E | Everything | Nothing | < 30s |

---

## Unit Tests

### `tests/unit/markdown_unit.py` — Storage round-trips

These tests use a real temp directory. No mocking.

| Test | Input | Expected |
|------|-------|----------|
| `test_create_entity` | create "Kira", type character, role blacksmith | `## Kira` and `**Role:** blacksmith` appear in people.md |
| `test_update_entity_field` | update Roger's Role from "Loadmaster" to "Captain" | field value changes in-place, old value gone |
| `test_update_appends_history` | update with `append_history=True` | dated `### YYYY-MM-DD` section appended below entity |
| `test_append_to_journal` | append ["Found the key at fishing hab"] | new `## Session —` section at bottom of journal.md |
| `test_parse_into_chunks` | parse people.md fixture | one chunk per `##` header, entity_name and entity_type populated |
| `test_get_known_entities` | parse all fixture files | returns dict with "characters", "todos", etc. keys |

### `tests/unit/entities_unit.py` — Extraction parsing

Mock the LLM; test that `EntityExtractor` correctly parses responses and handles edge cases.

| Test | LLM returns | Expected |
|------|-------------|----------|
| `test_extract_new_person` | valid JSON with one new character entity | `ExtractionResult.entities[0].is_new == True` |
| `test_extract_handles_code_fence` | JSON wrapped in ` ```json ``` ` | parses successfully |
| `test_extract_handles_malformed_json` | partial/invalid JSON | returns empty ExtractionResult, no exception |
| `test_resolve_skips_llm_for_new_entity` | — | if name not in known_entities, no LLM call made |
| `test_resolve_calls_llm_for_ambiguous` | coreference JSON: `{"resolved_to": "Roger", "confidence": "certain", ...}` | entity marked `is_new=False`, `resolved_name="Roger"` |
| `test_resolve_uncertain_stays_new` | coreference JSON: `{"resolved_to": null, "confidence": "uncertain", ...}` | entity stays `is_new=True` |

---

## Integration Tests

These spin up a real `MarkdownStore` + `NotebookIndex` in a temp directory. LLM is still mocked.

### `tests/integration/test_storage_index.py` — Write → search round-trip

| Test | Steps | Expected |
|------|-------|----------|
| `test_new_entity_is_searchable` | create Kira via MarkdownStore, index_file, search "blacksmith" | Kira chunk appears in results |
| `test_updated_entity_reflects_in_index` | create Roger, update role to Captain, index_file, search "Captain" | updated chunk returned, old "Loadmaster" content gone |
| `test_metadata_filter_by_type` | create entities of mixed types, search with `entity_type=characters` filter | only character chunks returned |
| `test_metadata_filter_by_status` | create todos with open/completed status, filter `status=open` | only open todos returned |
| `test_hash_prevents_redundant_reindex` | index same file twice unchanged | second index call returns 0 changes |
| `test_orphan_chunk_removed` | index file, delete entity from markdown, reindex all | deleted entity's chunk no longer in results |

---

## E2E / Prompt Tests

These call the real LLM (requires `OPENAI_API_KEY`). They test that the prompts produce correct behavior on realistic game inputs. Skipped if no API key is set.

Each test creates a fresh temp notebook directory, initializes a `NotebookAgent`, sends one or more messages, and inspects both the response and the resulting markdown files.

### `tests/e2e/test_record.py` — Recording new information

| Test | Input | Assert |
|------|-------|--------|
| `test_record_new_npc` | "I met a mechanic named Yuki at the surface base, she fixes drones" | people.md contains `## Yuki`, Role includes "mechanic", journal updated |
| `test_record_new_location` | "Found a new room called the Bunker Room below Epsilon" | places.md contains `## Bunker Room` |
| `test_record_new_quest` | "I need to find the source of the Jaspite ore — no idea where to look yet" | todos.md contains new entry, Subtype is quest |
| `test_record_multiple_entities` | "Talked to a guard named Praxis outside the Theta gate — he mentioned someone called the Warden" | both Praxis and the Warden appear in people.md |

### `tests/e2e/test_query.py` — Recall

These seed the temp notebook with the real fixture files, then query.

| Test | Input | Assert |
|------|-------|--------|
| `test_query_known_npc` | "What do I know about Rupert Sanford?" | response mentions "custodian" and "cleaning supplies" |
| `test_query_open_quests` | "What quests are still open?" | response includes "Unlock Epsilon Secure Storage", "Repair Lambda Reactor", does not include completed quests |
| `test_query_open_mysteries` | "What mysteries am I tracking?" | response includes "Lambda Radiation Cause", "Epsilon Crew Disappearance" |
| `test_query_entity_relationship` | "What's Roger's connection to the key?" | response mentions Loadmaster's Key and Sorrell/fishing hab |

### `tests/e2e/test_update.py` — Corrections and status changes

| Test | Input | Assert |
|------|-------|--------|
| `test_update_quest_status` | "I finished the Theta Gate Servo Install" | todos.md shows `**Status:** completed` for that entry |
| `test_correct_npc_role` | "Actually Roger is the captain, not the loadmaster" | people.md shows `**Role:** captain` (or Captain), response says "Noted" |
| `test_update_does_not_create_duplicate` | "Roger's role is captain" (Roger already exists) | people.md has exactly one `## Roger` section |

### `tests/e2e/test_routing.py` — Intent classification

Checks that the router sends inputs down the right path by inspecting which files were modified (or not).

| Test | Input | Expected intent | Files modified? |
|------|-------|-----------------|-----------------|
| `test_routes_record` | "Found a new ore called viridite near Lambda" | record | yes |
| `test_routes_query` | "Where is the fishing hab?" | query | no |
| `test_routes_update` | "Mark 'Explore North Gate Jungle' as done" | update | yes |
| `test_routes_chat` | "Thanks, that's all for now" | chat | no |

---

## What's Not Covered

- CLI rendering (Rich output) — manual verification only
- Conversation persistence (JSONL) — covered implicitly by integration tests
- Dynamic file creation (`create_topic_file`) — low priority, test manually when it first occurs
- Anthropic provider — spot-check manually; prompt behavior should be equivalent
