"""Entity extraction and coreference resolution using LLM."""

import json
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


EXTRACTION_SYSTEM_PROMPT = """You are extracting structured information from a player's narration about their RPG game.

Given the player's message and recent conversation context, extract:

1. **Observations**: Discrete facts to log in the journal. Each should be one atomic piece of information.

2. **Entities**: People, locations, things, todos, or events mentioned. For each:
   - name: The entity name (proper noun, capitalized)
   - type: character | location | item | todo | event
   - is_new: Whether this entity appears to be new (not in known_entities). Check carefully — if the name does NOT appear in known_entities, set is_new: true.
   - fields: Any attributes mentioned (see field reference below)

3. **Updates**: Changes to existing entities (status changes, corrections, new facts)
   - IMPORTANT: When the player reports completing a task, finding something, or resolving a mystery, update the related todo's Status to "completed" or "answered"
   - Look at known_entities for todos that match what the player just accomplished
   - Only generate updates for entities that ARE in known_entities. For new people/places/things, use entities instead.

4. **Relationships**: Links between entities (X is at Y, X gave Y to player, etc.)

Output ONLY valid JSON with this structure:
{
  "observations": ["string", ...],
  "entities": [
    {"name": "...", "type": "...", "is_new": true/false, "fields": {...}}
  ],
  "updates": [
    {"entity": "...", "field": "...", "old_value": "...", "new_value": "..."}
  ],
  "relationships": [
    {"from": "...", "relation": "...", "to": "..."}
  ]
}

Field reference by type:
- character: role, location, status, description (optional — one sentence of colour or context: appearance, personality, what makes them memorable)
- location: explored (yes|no|partial), status, position (spatial relationship to another place), parent (containing place), description (optional — atmosphere, notable features, what it feels like)
- item: category (resource|equipment|key-item|tech-component|access-code), status, location, description (optional — what it looks like or why it matters). Use "resource" for raw materials, consumables, and harvestable substances found in the world.
- todo: subtype (quest|plan|mystery), status (open|in-progress|blocked|completed|answered), requires (prerequisite todo name), outcome (one sentence: how/why it was completed — only set when status becomes completed or answered)
- event: category (death|discovery|encounter|hazard-confirmed|quest-resolution|other), date, location, status (active|resolved|noted)

Rules:
- Be precise. Only extract what's explicitly stated or clearly implied.
- Tag uncertain info with "(probable)" in the observation text.
- CRITICAL — entity naming: when an entity has no explicit in-world name, construct one from its type and geographic context — what it IS + WHERE it is. This makes names stable and searchable across sessions. Never use conversational references ("second", "another", "that one", "new", ordinal numbers) as part of a name.
  - BAD: "Second Drill", "Another Laser Drill", "New Location", "Third Door"
  - GOOD: "Laser Drill near Epsilon South Gate", "Door at Kappa Lab Level", "Drill Site South of Epsilon Yard"
- For corrections, include the old_value if mentioned.
- If nothing to extract, return empty arrays.
- CRITICAL: If a person's name is not in known_entities["characters"], they MUST appear as an entity with is_new: true. Do not silently drop new people.
- CRITICAL: If a place is described (even partially — "there's a bridge beyond Mu") and it's not in known_entities["locations"], create it as a new location with is_new: true.
- CRITICAL: If an item is mentioned (even as a prerequisite or intermediate step), it MUST appear as an entity with is_new: true. Do not drop items that appear mid-chain.
- CRITICAL — dependency chains: when the player says "I need X to do Y" or "I must do A before B", every entity in the chain must be extracted — not just the final goal. Extract all intermediate items, locations, and todos. For each todo in the chain, set the `requires` field to name the prerequisite step. Set status to "blocked" when the prerequisite is not yet met.
  - Example: "I need a fuel cell to power the lift, and I need the lift to reach level 3" → extract Fuel Cell (item), Lift (item/location), Level 3 (location), and todos for each unresolved step with appropriate `requires` links.
  - Never discard the earlier links in a dependency chain just because the player's sentence ends on the goal entity.

Examples:
- "Simone Parker lives in Crew Quarter C" (not in known_entities) → entity: {"name": "Simone Parker", "type": "character", "is_new": true, "fields": {"location": "Crew Quarters C"}}
- "I found a bridge beyond Mu Facility" (not in known_entities) → entity: {"name": "Bridge Beyond Mu", "type": "location", "is_new": true, "fields": {"explored": "partial", "position": "beyond Facility Mu"}}
- "there's a second laser drill near the path from Epsilon South Gate to Kappa" (not in known_entities) → entity: {"name": "Laser Drill near Epsilon South Gate", "type": "item", "is_new": true, "fields": {"category": "equipment", "location": "near path from Epsilon South Gate to Kappa"}}  NOT {"name": "Second Laser Drill", ...}
- "I found a new ore called cryonite" → entity: {"name": "Cryonite", "type": "item", "is_new": true, "fields": {"category": "resource"}}
- "I fixed the reactor" → updates: [{"entity": "Repair Lambda Reactor", "field": "Status", "old_value": "open", "new_value": "completed"}, {"entity": "Repair Lambda Reactor", "field": "Outcome", "old_value": "", "new_value": "Reactor repaired by the player"}]
- "The area west of Theta is unexplored jungle" (not in known_entities) → entity: {"name": "Area West of Theta", "type": "location", "is_new": true, "fields": {"explored": "no", "position": "west of Facility Theta"}}"""


COREFERENCE_SYSTEM_PROMPT = """You are resolving entity mentions to known entities in a game notebook.

Given a mention (like "the blacksmith", "that key", "the swamp facility") and context, determine if it refers to a known entity.

Output ONLY valid JSON:
{
  "resolved_to": "EntityName" or null,
  "confidence": "certain" | "likely" | "uncertain",
  "reasoning": "brief explanation"
}

Rules:
- Return null for resolved_to if this is clearly a new entity
- Use context clues (recent mentions, location, relationships)
- "certain": Direct name match or unambiguous reference
- "likely": Strong contextual match (only one candidate)
- "uncertain": Multiple candidates or weak match"""


@dataclass
class ExtractionResult:
    """Result from entity extraction."""

    observations: list[str] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)
    updates: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)


@dataclass
class CoreferenceResult:
    """Result from coreference resolution."""

    resolved_to: str | None
    confidence: str
    reasoning: str


class EntityExtractor:
    """Handles entity extraction and coreference resolution."""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    def extract(
        self,
        message: str,
        context: list[str] | None = None,
        known_entities: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        """Extract entities and observations from a message."""
        context_str = ""
        if context:
            context_str = "\n".join(context[-5:])  # Last 5 messages for context

        known_str = ""
        if known_entities:
            known_str = json.dumps(known_entities, indent=2)

        user_prompt = f"""Message: {message}

Recent context:
{context_str if context_str else "(none)"}

Known entities by type:
{known_str if known_str else "(none)"}

Extract structured information from this message."""

        messages = [
            SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        response = self.llm.invoke(messages)
        content = response.content

        # Parse JSON from response
        try:
            # Handle potential markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            data = json.loads(content.strip())

            return ExtractionResult(
                observations=data.get("observations", []),
                entities=data.get("entities", []),
                updates=data.get("updates", []),
                relationships=data.get("relationships", []),
            )
        except (json.JSONDecodeError, IndexError):
            # If parsing fails, return empty result
            return ExtractionResult()

    def resolve_coreference(
        self,
        mention: str,
        context: list[str],
        known_entities: dict[str, list[str]],
    ) -> CoreferenceResult:
        """Resolve a mention to a known entity."""
        context_str = "\n".join(context[-5:]) if context else "(none)"
        known_str = json.dumps(known_entities, indent=2)

        user_prompt = f"""Mention to resolve: "{mention}"

Recent context:
{context_str}

Known entities by type:
{known_str}

Does this mention refer to a known entity?"""

        messages = [
            SystemMessage(content=COREFERENCE_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        response = self.llm.invoke(messages)
        content = response.content

        # Parse JSON from response
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            data = json.loads(content.strip())

            return CoreferenceResult(
                resolved_to=data.get("resolved_to"),
                confidence=data.get("confidence", "uncertain"),
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, IndexError):
            return CoreferenceResult(
                resolved_to=None,
                confidence="uncertain",
                reasoning="Failed to parse response",
            )

    def resolve_entities(
        self,
        entities: list[dict],
        context: list[str],
        known_entities: dict[str, list[str]],
    ) -> list[dict]:
        """Resolve all extracted entities, linking to known ones where appropriate."""
        resolved = []

        # Flatten all known names for fast lookup
        all_known_names = {
            name.lower()
            for names in known_entities.values()
            for name in names
        }

        for entity in entities:
            if entity.get("is_new", True):
                name_lower = entity["name"].lower()

                # Only run coreference if the name is ambiguous (not a clear proper noun
                # or already appears verbatim in the known list). Skip coreference when
                # the name doesn't appear in known_entities at all — it's genuinely new.
                if name_lower in all_known_names:
                    result = self.resolve_coreference(
                        entity["name"],
                        context,
                        known_entities,
                    )
                    if result.resolved_to and result.confidence in ("certain", "likely"):
                        entity["resolved_name"] = result.resolved_to
                        entity["is_new"] = False
                    else:
                        entity["resolved_name"] = entity["name"]
                else:
                    # Name not found in known entities — it's new, skip coreference
                    entity["resolved_name"] = entity["name"]
            else:
                entity["resolved_name"] = entity["name"]

            resolved.append(entity)

        return resolved
