"""Node implementations for the notebook agent graph."""

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..extraction.entities import EntityExtractor
from ..storage.db import NotebookDB
from ..storage.index import NotebookIndex
from ..storage.markdown import MarkdownStore
from .state import NotebookState


NOTEBOOK_SYSTEM_PROMPT = """You are a notebook assistant for a 1st-person mining RPG. You have perfect memory of everything the player has told you about their game.

Your job:
- Record observations the player shares (people, places, items, events)
- Answer questions about what they've seen and done
- Track open objectives and mysteries
- Remember corrections and update your knowledge

Style:
- Be concise and conversational
- Use second person ("you found", "you've got")
- When recording: acknowledge briefly, confirm key facts
- When correcting: "Noted. [one sentence summary of change]"
- When querying: answer directly, mention related open items if relevant
- Never explain your internal process or mention files

You are not a guide or advisor. You don't give gameplay tips or suggestions. You just remember."""


ROUTER_SYSTEM_PROMPT = """Classify the user's intent. Output ONLY one of these exact words:
- record: User is sharing new information about their game (met someone, found something, discovered a place, stating a fact about a person or location)
- query: User is asking about something they've seen/done (what do I know about X, where is Y, what quests are open)
- update: User is correcting existing information or marking something complete (actually X is Y, mark X as done, I finished X)
- chat: General conversation, greetings, meta questions about the notebook

Examples:
- "I met a blacksmith named Kira" → record
- "What do I know about the reactor?" → query
- "Actually Roger is the captain" → update
- "Hello" → chat
- "I found the key at the fishing hab" → record (this is new info, even though it updates key status)
- "Mark the Theta quest as complete" → update
- "Dieter Yar lives in Crew Quarter C" → record (stating a fact about a person, even if it includes location)
- "Simone Parker lives in Crew Quarter C" → record (new person + location = record, not update)
- "There's a door to the canteen from Crew Quarter C" → record (new observation about a location)
- "I can't open the door because it needs a keycard" → record (blocker/constraint = new fact about a location or item)
- "I can't fix the reactor without a thermo-pump" → record (unmet requirement = new fact)
- "I need the plans for a thermo-pump" → record (missing item/knowledge = new fact)
- "The elevator requires a power cell to run" → record (dependency = new fact about an item or location)

Key rule: if the user mentions a person or place that has NOT been discussed before, it is ALWAYS record, not update.
Only use update when explicitly correcting something already established ("actually", "I was wrong", "mark as done").
Blocker and constraint statements ("I can't X", "I need X", "X requires Y") are ALWAYS record, not chat — they describe game state.

Output only the single word."""


QUERY_ANALYSIS_PROMPT = """Analyze this query and extract search parameters.

Output JSON:
{
  "semantic_query": "search terms for semantic search" or null,
  "filters": {
    "entity_type": "characters|locations|items|todos|events" or null,
    "status": "open|in-progress|blocked|completed|answered|active|resolved" or null,
    "subtype": "quest|plan|mystery" or null
  },
  "entities_mentioned": ["list", "of", "entity", "names"]
}

Entity types:
- "characters" → people, NPCs
- "locations" → places, facilities, rooms, areas
- "items" → things: ores, equipment, key items, access codes, tech components
- "todos" → quests, plans, and mysteries (all open objectives)
- "events" → things that happened (discoveries, deaths, encounters)

IMPORTANT: Only add a status filter if the user EXPLICITLY asks for it (e.g., "open quests", "unsolved mysteries").
Do NOT filter by status when listing all entities of a type (e.g., "who are the people", "list all characters").

Examples:
- "What quests are open?" → {"semantic_query": null, "filters": {"entity_type": "todos", "subtype": "quest", "status": "open"}, "entities_mentioned": []}
- "What should I do?" → {"semantic_query": null, "filters": {"entity_type": "todos", "status": "open"}, "entities_mentioned": []}
- "What are my open tasks?" → {"semantic_query": null, "filters": {"entity_type": "todos", "status": "open"}, "entities_mentioned": []}
- "What's left to do?" → {"semantic_query": null, "filters": {"entity_type": "todos", "status": "open"}, "entities_mentioned": []}
- "List my to-dos" → {"semantic_query": null, "filters": {"entity_type": "todos", "status": "open"}, "entities_mentioned": []}
- "What mysteries are unsolved?" → {"semantic_query": null, "filters": {"entity_type": "todos", "subtype": "mystery", "status": "open"}, "entities_mentioned": []}
- "What plans do I have?" → {"semantic_query": null, "filters": {"entity_type": "todos", "subtype": "plan"}, "entities_mentioned": []}
- "What do I know about Kira?" → {"semantic_query": "Kira", "filters": null, "entities_mentioned": ["Kira"]}
- "Tell me about the Lambda swamp" → {"semantic_query": "Lambda swamp radioactive pools", "filters": {"entity_type": "locations"}, "entities_mentioned": ["Lambda"]}
- "Who are all the people I've met?" → {"semantic_query": null, "filters": {"entity_type": "characters"}, "entities_mentioned": []}
- "List everyone" → {"semantic_query": null, "filters": {"entity_type": "characters"}, "entities_mentioned": []}
- "What places have I explored?" → {"semantic_query": null, "filters": {"entity_type": "locations"}, "entities_mentioned": []}
- "What things do I have?" → {"semantic_query": null, "filters": {"entity_type": "items"}, "entities_mentioned": []}
- "What has happened?" → {"semantic_query": null, "filters": {"entity_type": "events"}, "entities_mentioned": []}
- "What numeric codes do I have?" → {"semantic_query": null, "filters": {"entity_type": "items"}, "entities_mentioned": []}
- "List all known numeric codes" → {"semantic_query": null, "filters": {"entity_type": "items"}, "entities_mentioned": []}
- "What numeric codes do I have that I haven't used?" → {"semantic_query": null, "filters": {"entity_type": "items"}, "entities_mentioned": []}
- "What access codes are known?" → {"semantic_query": null, "filters": {"entity_type": "items"}, "entities_mentioned": []}
- "Do I have any unused codes?" → {"semantic_query": null, "filters": {"entity_type": "items"}, "entities_mentioned": []}

IMPORTANT: Codes, passwords, access codes, key codes, numeric codes, and lock combinations are all stored as items (category: access-code). When the user asks about codes or combinations — even implicitly ("what codes do I have that might work here?") — always set entity_type to "items". Never leave entity_type null for these queries."""


REFLECTION_PROMPT = """You are reviewing search results for relevance to a user's query.

Given a query and a list of retrieved items (each with an ID and a one-line summary), return only the IDs of items that are genuinely relevant to the query.

Output ONLY valid JSON:
{"relevant_ids": ["id1", "id2", ...]}

Be strict. If an item is only tangentially related or shares a keyword but not the actual topic, exclude it.

Examples:
- Query: "what needs a code?" → keep access codes and locked doors, drop drilling rigs and cargo drones
- Query: "what do I know about Roger?" → keep Roger and things directly involving Roger, drop unrelated people and places
- Query: "what quests are open?" → keep open quests, drop completed quests and unrelated items"""


# Lowercase markdown field name → DB field key (used for upsert_field calls)
_FIELD_MAP = {
    "role": "role",
    "status": "status",
    "location": "location",
    "explored": "explored",
    "position": "position",
    "subtype": "subtype",
    "category": "category",
    "date": "date",
    "outcome": "outcome",
    "description": "description",
}

# Lowercase DB field key → Markdown bold label (used for store.update_entity calls)
_MD_FIELD_MAP = {v: k.capitalize() for k, v in _FIELD_MAP.items()}
_MD_FIELD_MAP.update({
    "role": "Role",
    "status": "Status",
    "location": "Location",
    "explored": "Explored",
    "position": "Position",
    "subtype": "Subtype",
    "category": "Category",
    "date": "Date",
    "outcome": "Outcome",
    "description": "Description",
})

_TYPE_TO_FILE = {
    "characters": "people.md",
    "character": "people.md",
    "locations": "places.md",
    "location": "places.md",
    "items": "things.md",
    "item": "things.md",
    "todos": "todos.md",
    "todo": "todos.md",
    "quests": "todos.md",
    "quest": "todos.md",
    "mysteries": "todos.md",
    "mystery": "todos.md",
    "plans": "todos.md",
    "plan": "todos.md",
    "events": "events.md",
    "event": "events.md",
    "equipment": "things.md",
    "hazards": "events.md",
    "hazard": "events.md",
}

# DB entity type → markdown file
_DB_TYPE_TO_FILE = {
    "characters": "people.md",
    "locations": "places.md",
    "items": "things.md",
    "todos": "todos.md",
    "events": "events.md",
}

_UNACQUIRED_STATUSES = {"lost", "not obtained", "not recovered", "unknown"}


def _format_entity_for_context(entity) -> str:
    """Format a DB EntityRow as a compact context block for the LLM prompt."""
    lines = [f"**{entity.name}** ({entity.type})"]
    for field, value in entity.fields.items():
        if field != "status":
            lines.append(f"  {field}: {value}")
    if entity.status:
        lines.append(f"  status: {entity.status}")
    if entity.related:
        lines.append(f"  related: {', '.join(entity.related[:8])}")
    return "\n".join(lines)


class NodeFactory:
    """Factory for creating agent nodes with shared dependencies."""

    def __init__(
        self,
        llm: BaseChatModel,
        store: MarkdownStore,
        index: NotebookIndex,
        db: NotebookDB,
    ):
        self.llm = llm
        self.store = store
        self.index = index
        self.db = db
        self.extractor = EntityExtractor(llm)

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------

    def router(self, state: NotebookState) -> NotebookState:
        """Classify user intent."""
        user_input = state.get("user_input", "")

        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=user_input),
        ]

        response = self.llm.invoke(messages)
        intent = response.content.strip().lower()

        if intent not in ("record", "query", "update", "chat"):
            intent = "chat"

        return {**state, "intent": intent}

    # ------------------------------------------------------------------
    # Extract
    # ------------------------------------------------------------------

    def extract(self, state: NotebookState) -> NotebookState:
        """Extract entities and observations from user input."""
        user_input = state.get("user_input", "")
        messages = state.get("messages", [])

        context = [m.content for m in messages[-10:] if hasattr(m, "content")]
        known_entities = self.db.get_known_entities()

        result = self.extractor.extract(user_input, context, known_entities)

        return {
            **state,
            "extracted_observations": result.observations,
            "extracted_entities": result.entities,
            "extracted_updates": result.updates,
            "extracted_relationships": result.relationships,
        }

    # ------------------------------------------------------------------
    # Resolve
    # ------------------------------------------------------------------

    def resolve(self, state: NotebookState) -> NotebookState:
        """Resolve entity references to known entities."""
        entities = state.get("extracted_entities", [])
        messages = state.get("messages", [])

        if not entities:
            return {**state, "resolved_entities": []}

        context = [m.content for m in messages[-10:] if hasattr(m, "content")]
        known_entities = self.db.get_known_entities()

        resolved = self.extractor.resolve_entities(entities, context, known_entities)

        return {**state, "resolved_entities": resolved}

    # ------------------------------------------------------------------
    # Conflict check
    # ------------------------------------------------------------------

    def conflict_check(self, state: NotebookState) -> NotebookState:
        """Compare proposed updates against DB state. Populate conflicts list."""
        updates = state.get("extracted_updates", [])
        conflicts = self.db.detect_conflicts(updates)
        return {**state, "conflicts": conflicts}

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------

    def persist(self, state: NotebookState) -> NotebookState:
        """Write all extracted data to DB and markdown."""
        intent = state.get("intent", "record")
        user_input = state.get("user_input", "")
        observations = state.get("extracted_observations", [])
        entities = state.get("resolved_entities", [])
        updates = state.get("extracted_updates", [])
        relationships = state.get("extracted_relationships", [])

        files_modified = []

        # Journal (record only)
        if intent == "record" and observations:
            self.store.append_to_journal(observations)
            files_modified.append("journal.md")
            self.index.index_file(self.store, "journal.md")

        # Track which completed entities already have an Outcome in the batch
        entities_with_outcome = {
            u.get("entity", "")
            for u in updates
            if (u.get("field") or "").lower() == "outcome"
        }

        # New entities
        for entity in entities:
            if not entity.get("is_new", True):
                continue

            entity_type = entity.get("type", "todos")
            entity_name = entity.get("resolved_name", entity["name"])
            fields = entity.get("fields", {})
            source = entity.get("source", "player_observed")
            confidence = entity.get("confidence", "certain")

            # DB write
            entity_id = self.db.insert_entity(
                name=entity_name,
                type=self._canonical_type(entity_type),
                status=fields.get("status"),
                source=source,
                confidence=confidence,
                turn_text=user_input,
            )
            for field_key, value in fields.items():
                if field_key in _FIELD_MAP and value and isinstance(value, str):
                    self.db.upsert_field(
                        entity_id, field_key, value,
                        source=source, confidence=confidence, turn_text=user_input,
                    )

            # Markdown write
            filename = _TYPE_TO_FILE.get(entity_type, "todos.md")
            self.store.create_entity(
                filename=filename,
                entity_name=entity_name,
                entity_type=entity_type,
                fields=fields,
            )
            if filename not in files_modified:
                files_modified.append(filename)

        # Field updates
        for update in updates:
            entity_name = update.get("entity", "")
            field = (update.get("field") or "").lower()
            new_value = update.get("new_value", "")
            source = update.get("source", "player_observed")
            confidence = update.get("confidence", "certain")

            if not (entity_name and new_value):
                continue

            # DB write
            db_entity = self.db.get_entity_by_name(entity_name)
            if db_entity and field:
                self.db.upsert_field(
                    db_entity.id, field, new_value,
                    source=source, confidence=confidence, turn_text=user_input,
                )

            # Markdown write
            filename = self._find_entity_file(entity_name)
            if not filename:
                continue

            if field:
                md_field = _MD_FIELD_MAP.get(field, field.capitalize())
                self.store.update_entity(
                    filename=filename,
                    entity_name=entity_name,
                    updates={md_field: new_value},
                )
                if field == "status" and new_value.lower() in ("completed", "answered"):
                    if entity_name not in entities_with_outcome:
                        self.store.update_entity(
                            filename=filename,
                            entity_name=entity_name,
                            updates={"Outcome": user_input},
                        )
                        if db_entity:
                            self.db.upsert_field(
                                db_entity.id, "outcome", user_input,
                                source=source, confidence=confidence, turn_text=user_input,
                            )
                    for f in self._propagate_completion(entity_name, db_entity):
                        if f not in files_modified:
                            files_modified.append(f)
            else:
                self.store.update_entity(
                    filename=filename,
                    entity_name=entity_name,
                    updates={},
                    append_history=new_value,
                )
                if db_entity:
                    self.db.insert_history(db_entity.id, new_value)

            if filename not in files_modified:
                files_modified.append(filename)

        # Relationships
        for rel in relationships:
            from_name = rel.get("from", "")
            to_name = rel.get("to", "")
            relation = rel.get("relation", "related to")
            if not (from_name and to_name):
                continue

            db_entity = self.db.get_entity_by_name(from_name)
            if db_entity:
                self.db.insert_relationship(db_entity.id, to_name, relation)

            filename = self._find_entity_file(from_name)
            if filename:
                self.store.update_entity(
                    filename=filename,
                    entity_name=from_name,
                    updates={},
                    append_history=f"Related to [[{to_name}]]",
                )

        # Re-index modified files
        for filename in files_modified:
            self.index.index_file(self.store, filename)

        return {**state, "files_modified": files_modified}

    # ------------------------------------------------------------------
    # Query path
    # ------------------------------------------------------------------

    def analyze_query(self, state: NotebookState) -> NotebookState:
        """Analyze a query to extract search parameters."""
        user_input = state.get("user_input", "")

        messages = [
            SystemMessage(content=QUERY_ANALYSIS_PROMPT),
            HumanMessage(content=user_input),
        ]

        response = self.llm.invoke(messages)
        content = response.content

        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            data = json.loads(content.strip())

            return {
                **state,
                "semantic_query": data.get("semantic_query"),
                "query_filters": data.get("filters"),
                "_entities_mentioned": data.get("entities_mentioned", []),
            }
        except (json.JSONDecodeError, IndexError):
            return {
                **state,
                "semantic_query": user_input,
                "query_filters": None,
                "_entities_mentioned": [],
            }

    def retrieve(self, state: NotebookState) -> NotebookState:
        """Retrieve: DB exact lookup first, semantic search second."""
        semantic_query = state.get("semantic_query")
        filters = state.get("query_filters") or {}
        entities_mentioned = state.get("_entities_mentioned", [])

        # --- Structured lookup from DB ---
        structured = []

        # Named entity lookups
        for name in entities_mentioned:
            entity = self.db.get_entity_by_name(name)
            if entity:
                structured.append({
                    "source": "db",
                    "entity": entity,
                    "content": _format_entity_for_context(entity),
                })

        # Type/status filtered listing
        entity_type = filters.get("entity_type")
        status_filter = filters.get("status")
        subtype_filter = filters.get("subtype")

        if entity_type and not entities_mentioned:
            db_rows = self.db.get_entities_by_type(
                entity_type,
                status=status_filter,
                subtype=subtype_filter,
            )
            for row in db_rows:
                structured.append({
                    "source": "db",
                    "entity": row,
                    "content": _format_entity_for_context(row),
                })

        # --- Semantic search ---
        index_filters = {}
        if filters.get("entity_type"):
            index_filters["entity_type"] = filters["entity_type"]
        if filters.get("status"):
            index_filters["status"] = filters["status"]
        if filters.get("subtype"):
            index_filters["subtype"] = filters["subtype"]

        top_k = 30 if (not semantic_query and index_filters) else 10

        semantic_chunks = self.index.hybrid_search(
            semantic_query=semantic_query,
            filters=index_filters if index_filters else None,
            top_k=top_k,
        )

        return {
            **state,
            "structured_results": structured,
            "retrieved_chunks": semantic_chunks,
        }

    def reflect(self, state: NotebookState) -> NotebookState:
        """Filter semantic chunks to only those genuinely relevant to the query."""
        chunks = state.get("retrieved_chunks", [])
        if not chunks:
            return state

        user_input = state.get("user_input", "")

        items = []
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "")
            meta = chunk.get("metadata", {})
            name = meta.get("entity_name", chunk_id)
            entity_type = meta.get("entity_type", "")
            status = meta.get("status", "")
            summary_parts = [p for p in [entity_type, status] if p]
            summary = f"{name} ({', '.join(summary_parts)})" if summary_parts else name
            items.append({"id": chunk_id, "summary": summary})

        user_prompt = f"""Query: {user_input}

Items to review:
{json.dumps(items, indent=2)}

Return only the IDs of items that are genuinely relevant to this query."""

        messages = [
            SystemMessage(content=REFLECTION_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        response = self.llm.invoke(messages)
        content = response.content

        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = json.loads(content.strip())
            relevant_ids = set(data.get("relevant_ids", []))
            filtered = [c for c in chunks if c.get("chunk_id") in relevant_ids]
            return {**state, "retrieved_chunks": filtered}
        except (json.JSONDecodeError, IndexError):
            return state

    # ------------------------------------------------------------------
    # Respond
    # ------------------------------------------------------------------

    def respond(self, state: NotebookState) -> NotebookState:
        """Generate a natural response. DB facts first, semantic enrichment second."""
        intent = state.get("intent", "chat")
        user_input = state.get("user_input", "")
        messages = state.get("messages", [])
        conflicts = state.get("conflicts", [])

        context_parts = []

        # Conflict response — don't write, ask player to confirm
        if conflicts:
            conflict_lines = []
            for c in conflicts:
                conflict_lines.append(
                    f"- {c['entity']} / {c['field']}: "
                    f"notebook has \"{c['db_value']}\", "
                    f"you said \"{c['proposed_value']}\""
                )
            context_parts.append(
                "CONFLICTS — the following contradict what's recorded. "
                "Ask the player to confirm before accepting:\n" + "\n".join(conflict_lines)
            )

        elif intent == "query":
            # Authoritative DB results first
            structured = state.get("structured_results", [])
            semantic = state.get("retrieved_chunks", [])

            if structured:
                context_parts.append("Authoritative facts from the notebook:")
                for item in structured:
                    context_parts.append(item["content"])

            # Semantic enrichment second — but only if different from DB results
            if semantic:
                db_names = {
                    item["entity"].name.lower()
                    for item in structured
                    if item.get("entity")
                }
                enrichment = [
                    c for c in semantic
                    if c.get("metadata", {}).get("entity_name", "").lower() not in db_names
                ]
                if enrichment:
                    context_parts.append("\nAdditional context from notes and journal:")
                    for chunk in enrichment[:5]:
                        context_parts.append(f"---\n{chunk.get('content', '')}\n---")
                elif not structured:
                    # No DB hits at all — fall back to full semantic results
                    if len(semantic) > 5:
                        context_parts.append(
                            f"Found {len(semantic)} matching items. Group them logically:"
                        )
                        for chunk in semantic:
                            meta = chunk.get("metadata", {})
                            name = meta.get("entity_name", "Unknown")
                            related_str = meta.get("related", "")
                            if related_str:
                                context_parts.append(f"- {name} (related: {related_str})")
                            else:
                                context_parts.append(f"- {name}")
                    else:
                        context_parts.append("Relevant information from the notebook:")
                        for chunk in semantic:
                            context_parts.append(f"---\n{chunk.get('content', '')}\n---")

        elif intent in ("record", "update"):
            observations = state.get("extracted_observations", [])
            entities = state.get("resolved_entities", [])
            updates = state.get("extracted_updates", [])

            if observations:
                context_parts.append(f"Recorded {len(observations)} observation(s).")
            if intent == "record" and entities:
                new_entities = [e for e in entities if e.get("is_new")]
                if new_entities:
                    names = [e.get("resolved_name", e["name"]) for e in new_entities]
                    context_parts.append(f"New entities added: {', '.join(names)}")

            # Pull related context from DB for entities just touched
            search_names = (
                [e.get("resolved_name", e["name"]) for e in entities]
                + [u.get("entity", "") for u in updates if u.get("entity")]
            )

            related_db = []
            seen_db_ids = set()
            for name in search_names:
                if not name:
                    continue
                entity = self.db.get_entity_by_name(name)
                if entity and entity.id not in seen_db_ids:
                    seen_db_ids.add(entity.id)
                    related_db.append(entity)

            if related_db:
                context_parts.append("\nKnown facts about entities just recorded/updated:")
                for entity in related_db:
                    context_parts.append(_format_entity_for_context(entity))

            # Semantic enrichment from index
            search_queries = search_names + observations
            related_chunks = []
            seen_chunk_ids = set()
            for name in search_queries:
                if not name:
                    continue
                results = self.index.hybrid_search(semantic_query=name, top_k=3)
                for chunk in results:
                    cid = chunk.get("chunk_id")
                    if cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        related_chunks.append(chunk)

            # Open todos related to what was just touched
            combined_query = " ".join(q for q in search_queries if q)
            if combined_query:
                open_todos = self.index.hybrid_search(
                    semantic_query=combined_query,
                    filters={"entity_type": "todos", "status": "open"},
                    top_k=3,
                )
                for chunk in open_todos:
                    cid = chunk.get("chunk_id")
                    if cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        related_chunks.append(chunk)

            if related_chunks:
                context_parts.append("\nRelated context from notes and journal:")
                for chunk in related_chunks:
                    context_parts.append(f"---\n{chunk.get('content', '')}\n---")

        context_str = "\n".join(context_parts) if context_parts else ""

        new_entities = (
            [e for e in state.get("resolved_entities", []) if e.get("is_new")]
            if intent == "record" else []
        )
        new_entity_context = ""
        if new_entities:
            lines = []
            for e in new_entities:
                name = e.get("resolved_name", e.get("name", ""))
                fields = e.get("fields", {})
                field_str = ", ".join(f"{k}: {v}" for k, v in fields.items() if v)
                lines.append(f"- {name} ({e.get('type', '')}){': ' + field_str if field_str else ''}")
            new_entity_context = (
                "\nNewly recorded entities:\n" + "\n".join(lines) +
                "\n\nIf — and only if — a genuinely consequential fact is missing "
                "(something that would affect what the player should do next, e.g. "
                "unknown allegiance of a character tied to a quest, or unknown category "
                "of an item), ask ONE short question at the end of your response. "
                "Use full conversational context before deciding. "
                "Do not ask about cosmetic or low-stakes details. "
                "Do not ask if the entity already has enough context."
            )

        response_prompt = f"""User's message: {user_input}

Intent: {intent}

{context_str}{new_entity_context}

Respond naturally and concisely. Remember:
- For recording: acknowledge what was recorded, then mention any relevant related info AND any open next steps or quests from the notebook context above
- For updates: acknowledge the change, then explicitly mention what is now unblocked or what the next open step is, using the notebook context above
- For queries: answer directly. If authoritative facts are present above, use them as ground truth. Semantic context is supporting detail only.
- For chat: respond naturally
- If CONFLICTS are listed: describe each discrepancy clearly and ask the player which value is correct. Do not confirm the change yet.

Do not explain your process or mention files."""

        conversation_messages = [SystemMessage(content=NOTEBOOK_SYSTEM_PROMPT)]
        for msg in messages[-6:]:
            conversation_messages.append(msg)
        conversation_messages.append(HumanMessage(content=response_prompt))

        response = self.llm.invoke(conversation_messages)

        return {**state, "response": response.content}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _canonical_type(self, entity_type: str) -> str:
        """Normalise extraction type strings to the four canonical DB types."""
        mapping = {
            "character": "characters",
            "characters": "characters",
            "location": "locations",
            "locations": "locations",
            "item": "items",
            "items": "items",
            "equipment": "items",
            "todo": "todos",
            "todos": "todos",
            "quest": "todos",
            "quests": "todos",
            "mystery": "todos",
            "mysteries": "todos",
            "plan": "todos",
            "plans": "todos",
            "event": "events",
            "events": "events",
            "hazard": "events",
            "hazards": "events",
        }
        return mapping.get(entity_type, "todos")

    def _find_entity_file(self, entity_name: str) -> str | None:
        """Find the markdown file for an entity via DB type lookup."""
        entity = self.db.get_entity_by_name(entity_name)
        if entity:
            return _DB_TYPE_TO_FILE.get(entity.type)
        # Fall back to scanning markdown (handles entities not yet in DB)
        for file_path in self.store.list_files():
            chunks = self.store.parse_into_chunks(file_path.name)
            for chunk in chunks:
                if chunk.entity_name.lower() == entity_name.lower():
                    return file_path.name
        return None

    def _propagate_completion(self, todo_name: str, db_entity) -> list[str]:
        """When a todo completes, update status of related items that are unacquired."""
        if not db_entity:
            return []

        files_modified = []
        for related_name in db_entity.related:
            related = self.db.get_entity_by_name(related_name)
            if not related or related.type != "items":
                continue
            current_status = (related.status or "").lower()
            if not any(s in current_status for s in _UNACQUIRED_STATUSES):
                continue

            self.db.upsert_field(
                related.id, "status", "found",
                source="player_observed", confidence="certain",
            )
            filename = _DB_TYPE_TO_FILE.get("items", "things.md")
            self.store.update_entity(
                filename=filename,
                entity_name=related_name,
                updates={"Status": "found"},
            )
            if filename not in files_modified:
                files_modified.append(filename)

        return files_modified
