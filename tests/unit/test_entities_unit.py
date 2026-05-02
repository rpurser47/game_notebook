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
