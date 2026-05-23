"""Unit tests for EntityExtractor."""

import json
import pytest
from unittest.mock import MagicMock, call
from src.extraction.entities import EntityExtractor, ExtractionResult, CoreferenceResult


def make_llm(response_text: str) -> MagicMock:
    """Return a mock LLM whose invoke() returns the given text."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=response_text)
    return llm


def extraction_json(**kwargs) -> str:
    defaults = {"observations": [], "entities": [], "updates": [], "relationships": []}
    defaults.update(kwargs)
    return json.dumps(defaults)


@pytest.mark.unit
class TestExtract:
    def test_parses_new_character(self):
        payload = extraction_json(
            observations=["Met blacksmith Kira in Millhaven."],
            entities=[{"name": "Kira", "type": "character", "is_new": True, "fields": {"role": "blacksmith"}}],
        )
        extractor = EntityExtractor(make_llm(payload))
        result = extractor.extract("I met a blacksmith named Kira in Millhaven")
        assert len(result.entities) == 1
        assert result.entities[0]["name"] == "Kira"
        assert result.entities[0]["is_new"] is True
        assert result.observations == ["Met blacksmith Kira in Millhaven."]

    def test_parses_json_wrapped_in_code_fence(self):
        payload = "```json\n" + extraction_json(
            entities=[{"name": "Kira", "type": "character", "is_new": True, "fields": {}}]
        ) + "\n```"
        extractor = EntityExtractor(make_llm(payload))
        result = extractor.extract("met Kira")
        assert result.entities[0]["name"] == "Kira"

    def test_parses_json_wrapped_in_plain_fence(self):
        payload = "```\n" + extraction_json(
            observations=["Found a key."]
        ) + "\n```"
        extractor = EntityExtractor(make_llm(payload))
        result = extractor.extract("found a key")
        assert result.observations == ["Found a key."]

    def test_malformed_json_returns_empty_result(self):
        extractor = EntityExtractor(make_llm("This is not JSON at all."))
        result = extractor.extract("something")
        assert result == ExtractionResult()

    def test_empty_arrays_in_response(self):
        extractor = EntityExtractor(make_llm(extraction_json()))
        result = extractor.extract("hello")
        assert result.observations == []
        assert result.entities == []
        assert result.updates == []
        assert result.relationships == []

    def test_parses_update(self):
        payload = extraction_json(
            updates=[{"entity": "Roger", "field": "Role", "old_value": "Loadmaster", "new_value": "Captain"}]
        )
        extractor = EntityExtractor(make_llm(payload))
        result = extractor.extract("Roger is actually the captain")
        assert result.updates[0]["new_value"] == "Captain"


@pytest.mark.unit
class TestResolveEntities:
    KNOWN = {"characters": ["Roger", "Kira"], "locations": ["Millhaven"]}

    def test_skips_llm_for_genuinely_new_entity(self):
        llm = make_llm("{}")
        extractor = EntityExtractor(llm)
        entities = [{"name": "Yuki", "type": "character", "is_new": True, "fields": {}}]
        resolved = extractor.resolve_entities(entities, [], self.KNOWN)
        llm.invoke.assert_not_called()
        assert resolved[0]["resolved_name"] == "Yuki"
        assert resolved[0]["is_new"] is True

    def test_calls_llm_when_name_exists_in_known(self):
        coref_response = json.dumps({"resolved_to": "Roger", "confidence": "certain", "reasoning": "same name"})
        llm = make_llm(coref_response)
        extractor = EntityExtractor(llm)
        entities = [{"name": "Roger", "type": "character", "is_new": True, "fields": {}}]
        resolved = extractor.resolve_entities(entities, [], self.KNOWN)
        llm.invoke.assert_called_once()
        assert resolved[0]["is_new"] is False
        assert resolved[0]["resolved_name"] == "Roger"

    def test_uncertain_coreference_keeps_entity_new(self):
        coref_response = json.dumps({"resolved_to": None, "confidence": "uncertain", "reasoning": "no match"})
        llm = make_llm(coref_response)
        extractor = EntityExtractor(llm)
        entities = [{"name": "Roger", "type": "character", "is_new": True, "fields": {}}]
        resolved = extractor.resolve_entities(entities, [], self.KNOWN)
        assert resolved[0]["is_new"] is True

    def test_is_new_false_skips_coreference(self):
        llm = make_llm("{}")
        extractor = EntityExtractor(llm)
        entities = [{"name": "Roger", "type": "character", "is_new": False, "fields": {}}]
        resolved = extractor.resolve_entities(entities, [], self.KNOWN)
        llm.invoke.assert_not_called()
        assert resolved[0]["resolved_name"] == "Roger"

    def test_multiple_entities_only_calls_llm_for_ambiguous(self):
        coref_response = json.dumps({"resolved_to": "Roger", "confidence": "certain", "reasoning": "same"})
        llm = make_llm(coref_response)
        extractor = EntityExtractor(llm)
        entities = [
            {"name": "Roger", "type": "character", "is_new": True, "fields": {}},   # known → LLM call
            {"name": "Yuki", "type": "character", "is_new": True, "fields": {}},    # new → no call
        ]
        extractor.resolve_entities(entities, [], self.KNOWN)
        assert llm.invoke.call_count == 1


# ---------------------------------------------------------------------------
# Extraction prompt — dependency chain rules
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExtractionPromptDependencyRules:
    """The extraction prompt must contain explicit CRITICAL rules that prevent
    the LLM from dropping prerequisite entities in dependency chain statements.

    These tests are prompt-content checks — fast and deterministic. They
    fail until the prompt is updated, then pass permanently as regression guards.
    """

    def test_critical_rule_for_items_not_dropped(self):
        """Prompt must have a CRITICAL rule that explicitly covers items (not just
        characters and locations) so prerequisite items aren't silently dropped."""
        from src.extraction.entities import EXTRACTION_SYSTEM_PROMPT
        import re
        # Extract the sentence/phrase immediately following each "CRITICAL" label
        critical_sentences = re.findall(r"CRITICAL[^.:\n]*[.:\n][^\n]*", EXTRACTION_SYSTEM_PROMPT)
        # Existing rules cover characters and locations. Need one that covers items.
        item_rule = any(
            "item" in s.lower() and ("new" in s.lower() or "drop" in s.lower() or "must" in s.lower())
            for s in critical_sentences
        )
        assert item_rule, (
            f"No CRITICAL rule found covering new items.\nFound CRITICAL sentences:\n"
            + "\n".join(critical_sentences)
        )

    def test_prompt_instructs_extract_all_chain_entities(self):
        """Prompt must explicitly instruct extracting every entity in a dependency
        chain, not just the terminal/goal entity."""
        from src.extraction.entities import EXTRACTION_SYSTEM_PROMPT
        lower = EXTRACTION_SYSTEM_PROMPT.lower()
        has_all_instruction = (
            ("every entity" in lower or "all entities" in lower or "each entity" in lower)
            and ("chain" in lower or "dependency" in lower)
        )
        assert has_all_instruction, (
            "Prompt does not instruct extracting ALL entities in a dependency chain"
        )

    def test_prompt_has_dependency_chain_example(self):
        """Prompt must include a concrete multi-step chain example using 'need X to Y'
        phrasing, so the LLM has a pattern to follow."""
        from src.extraction.entities import EXTRACTION_SYSTEM_PROMPT
        # The existing 6 arrows are for entity naming examples. We need an additional
        # example that demonstrates chain extraction — it will add at least one more arrow
        # AND must contain "need" in a chain/dependency context.
        lower = EXTRACTION_SYSTEM_PROMPT.lower()
        has_chain_example = (
            EXTRACTION_SYSTEM_PROMPT.count("→") >= 7
            and "need" in lower
            and ("chain" in lower or "dependency" in lower)
        )
        assert has_chain_example, (
            "Prompt needs a dependency chain example (need X to Y phrasing with → output)"
        )

    def test_requires_field_explained_in_chain_context(self):
        """Prompt must explain that `requires` on a todo should be populated
        from 'I need X before Y' phrasing — not just listed as a field name."""
        from src.extraction.entities import EXTRACTION_SYSTEM_PROMPT
        lower = EXTRACTION_SYSTEM_PROMPT.lower()
        # "requires" field is already listed in the field reference. We need it
        # to also appear in an explanatory rule or example that connects it to
        # dependency chain language ("need ... before", "need ... to").
        requires_explained = (
            "\"requires\"" in EXTRACTION_SYSTEM_PROMPT
            or "`requires`" in EXTRACTION_SYSTEM_PROMPT
            or "requires field" in lower
            or ("requires" in lower and "chain" in lower)
            or ("requires" in lower and "dependency" in lower)
        )
        assert requires_explained, (
            "Prompt does not explain when to populate the `requires` field from chain statements"
        )


# ---------------------------------------------------------------------------
# Extraction parsing — dependency chain inputs
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExtractDependencyChain:
    """Verify the extractor correctly parses LLM output for chain inputs.
    The LLM is mocked — these tests check parsing and pass-through, not LLM behaviour.
    """

    def test_parses_two_entities_from_chain_response(self):
        """Extractor must return all entities the LLM emits, even when there are
        multiple items in a dependency chain."""
        payload = extraction_json(
            observations=[
                "Needs thermo-pump to fix the climber.",
                "Needs climber working to reach the upper shaft.",
            ],
            entities=[
                {"name": "Thermo-Pump", "type": "item", "is_new": True,
                 "fields": {"category": "tech-component", "status": "not obtained"}},
                {"name": "Upper Shaft", "type": "location", "is_new": True,
                 "fields": {"explored": "no"}},
            ],
            relationships=[
                {"from": "Thermo-Pump", "relation": "required to fix", "to": "Climber"},
            ],
        )
        extractor = EntityExtractor(make_llm(payload))
        result = extractor.extract(
            "I need a thermo-pump to fix the climber, "
            "and I need the climber working to reach the upper shaft"
        )
        names = [e["name"] for e in result.entities]
        assert "Thermo-Pump" in names
        assert "Upper Shaft" in names

    def test_parses_three_entities_from_three_hop_chain(self):
        """All three chain elements must survive the parse step."""
        payload = extraction_json(
            observations=[
                "Needs fuel cell to power the lift.",
                "Needs lift to reach level 3.",
                "Needs level 3 to find core sample.",
            ],
            entities=[
                {"name": "Fuel Cell", "type": "item", "is_new": True,
                 "fields": {"category": "tech-component", "status": "not obtained"}},
                {"name": "Level 3", "type": "location", "is_new": True,
                 "fields": {"explored": "no"}},
                {"name": "Core Sample", "type": "item", "is_new": True,
                 "fields": {"category": "key-item", "status": "not obtained"}},
            ],
        )
        extractor = EntityExtractor(make_llm(payload))
        result = extractor.extract(
            "I need the fuel cell to power the lift, "
            "I need the lift to reach level 3, "
            "and I need level 3 to find the core sample"
        )
        names = [e["name"] for e in result.entities]
        assert "Fuel Cell" in names
        assert "Level 3" in names
        assert "Core Sample" in names

    def test_parses_requires_field_on_todo(self):
        """When the LLM sets `requires` on a todo, it must survive the parse."""
        payload = extraction_json(
            entities=[
                {"name": "Open Security Door", "type": "todo", "is_new": True,
                 "fields": {"subtype": "quest", "status": "blocked",
                            "requires": "Find Access Card"}},
            ],
        )
        extractor = EntityExtractor(make_llm(payload))
        result = extractor.extract(
            "I have to find the access card to open the security door"
        )
        todo = result.entities[0]
        assert todo["fields"].get("requires") == "Find Access Card"

    def test_relationships_preserved_for_chain(self):
        """Prerequisite relationships between chain entities must be returned."""
        payload = extraction_json(
            relationships=[
                {"from": "Access Card", "relation": "required to open", "to": "Security Door"},
                {"from": "Security Door", "relation": "blocks access to", "to": "Generator Room"},
            ],
        )
        extractor = EntityExtractor(make_llm(payload))
        result = extractor.extract(
            "I need the access card to open the security door "
            "and I need it open to get to the generator room"
        )
        assert len(result.relationships) == 2
        froms = [r["from"] for r in result.relationships]
        assert "Access Card" in froms
        assert "Security Door" in froms
