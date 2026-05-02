"""Node implementations for the notebook agent graph."""

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..extraction.entities import EntityExtractor
from ..storage.index import NotebookIndex
from ..storage.markdown import MarkdownStore
from .state import NotebookState


# System prompt for the notebook agent
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

Key rule: if the user mentions a person or place that has NOT been discussed before, it is ALWAYS record, not update.
Only use update when explicitly correcting something already established ("actually", "I was wrong", "mark as done").

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
- "What has happened?" → {"semantic_query": null, "filters": {"entity_type": "events"}, "entities_mentioned": []}"""


REFLECTION_PROMPT = """You are reviewing search results for relevance to a user's query.

Given a query and a list of retrieved items (each with an ID and a one-line summary), return only the IDs of items that are genuinely relevant to the query.

Output ONLY valid JSON:
{"relevant_ids": ["id1", "id2", ...]}

Be strict. If an item is only tangentially related or shares a keyword but not the actual topic, exclude it.

Examples:
- Query: "what needs a code?" → keep access codes and locked doors, drop drilling rigs and cargo drones
- Query: "what do I know about Roger?" → keep Roger and things directly involving Roger, drop unrelated people and places
- Query: "what quests are open?" → keep open quests, drop completed quests and unrelated items"""


class NodeFactory:
    """Factory for creating agent nodes with shared dependencies."""

    def __init__(
        self,
        llm: BaseChatModel,
        store: MarkdownStore,
        index: NotebookIndex,
    ):
        self.llm = llm
        self.store = store
        self.index = index
        self.extractor = EntityExtractor(llm)

    def router(self, state: NotebookState) -> NotebookState:
        """Classify user intent."""
        user_input = state.get("user_input", "")

        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=user_input),
        ]

        response = self.llm.invoke(messages)
        intent = response.content.strip().lower()

        # Validate intent
        if intent not in ("record", "query", "update", "chat"):
            intent = "chat"

        return {**state, "intent": intent}

    def extract(self, state: NotebookState) -> NotebookState:
        """Extract entities and observations from user input."""
        user_input = state.get("user_input", "")
        messages = state.get("messages", [])

        # Get conversation context
        context = [m.content for m in messages[-10:] if hasattr(m, "content")]

        # Get known entities
        known_entities = self.store.get_known_entities()

        # Extract
        result = self.extractor.extract(user_input, context, known_entities)

        return {
            **state,
            "extracted_observations": result.observations,
            "extracted_entities": result.entities,
            "extracted_updates": result.updates,
            "extracted_relationships": result.relationships,
        }

    def resolve(self, state: NotebookState) -> NotebookState:
        """Resolve entity references to known entities."""
        entities = state.get("extracted_entities", [])
        messages = state.get("messages", [])

        if not entities:
            return {**state, "resolved_entities": []}

        context = [m.content for m in messages[-10:] if hasattr(m, "content")]
        known_entities = self.store.get_known_entities()

        resolved = self.extractor.resolve_entities(entities, context, known_entities)

        return {**state, "resolved_entities": resolved}

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
            }
        except (json.JSONDecodeError, IndexError):
            # Fall back to using input as semantic query
            return {
                **state,
                "semantic_query": user_input,
                "query_filters": None,
            }

    def retrieve(self, state: NotebookState) -> NotebookState:
        """Retrieve relevant chunks from the index."""
        semantic_query = state.get("semantic_query")
        filters = state.get("query_filters")

        # Convert filters to index format
        index_filters = {}
        if filters:
            if filters.get("entity_type"):
                index_filters["entity_type"] = filters["entity_type"]
            if filters.get("status"):
                index_filters["status"] = filters["status"]
            if filters.get("subtype"):
                index_filters["subtype"] = filters["subtype"]

        # Use higher limit for listing queries (no semantic query, just filters)
        top_k = 30 if (not semantic_query and index_filters) else 10

        results = self.index.hybrid_search(
            semantic_query=semantic_query,
            filters=index_filters if index_filters else None,
            top_k=top_k,
        )

        return {**state, "retrieved_chunks": results}

    def reflect(self, state: NotebookState) -> NotebookState:
        """Filter retrieved chunks to only those genuinely relevant to the query."""
        chunks = state.get("retrieved_chunks", [])
        if not chunks:
            return state

        user_input = state.get("user_input", "")

        # Build a compact item list for the LLM — ID + one-line summary
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
            # On parse failure, pass all chunks through rather than dropping data
            return state

    def persist(self, state: NotebookState) -> NotebookState:
        """Write all extracted data to storage (handles both record and update intents)."""
        intent = state.get("intent", "record")
        observations = state.get("extracted_observations", [])
        entities = state.get("resolved_entities", [])
        updates = state.get("extracted_updates", [])
        relationships = state.get("extracted_relationships", [])

        files_modified = []

        field_map = {
            "role": "Role",
            "status": "Status",
            "location": "Location",
            "explored": "Explored",
            "position": "Position",
            "subtype": "Subtype",
            "category": "Category",
            "date": "Date",
        }

        # Journal — only for record intent (new observations, not corrections)
        if intent == "record" and observations:
            self.store.append_to_journal(observations)
            files_modified.append("journal.md")
            self.index.index_file(self.store, "journal.md")

        # New entities
        for entity in entities:
            if entity.get("is_new", True):
                entity_type = entity.get("type", "mysteries")
                filename = self._get_file_for_type(entity_type)
                self.store.create_entity(
                    filename=filename,
                    entity_name=entity.get("resolved_name", entity["name"]),
                    entity_type=entity_type,
                    fields=entity.get("fields", {}),
                )
                if filename not in files_modified:
                    files_modified.append(filename)

        # Field updates
        for update in updates:
            entity_name = update.get("entity", "")
            field = update.get("field", "")
            new_value = update.get("new_value", "")

            if not (entity_name and new_value):
                continue

            filename = self._find_entity_file(entity_name)
            if not filename:
                continue

            if field:
                mapped_field = field_map.get(field.lower(), field.capitalize())
                self.store.update_entity(
                    filename=filename,
                    entity_name=entity_name,
                    updates={mapped_field: new_value},
                )
                if mapped_field == "Status" and new_value.lower() in ("completed", "answered"):
                    for f in self._propagate_completion_to_related(entity_name, filename):
                        if f not in files_modified:
                            files_modified.append(f)
            else:
                self.store.update_entity(
                    filename=filename,
                    entity_name=entity_name,
                    updates={},
                    append_history=new_value,
                )

            if filename not in files_modified:
                files_modified.append(filename)

        # Relationships
        for rel in relationships:
            from_entity = rel.get("from", "")
            to_entity = rel.get("to", "")
            if from_entity and to_entity:
                filename = self._find_entity_file(from_entity)
                if filename:
                    self.store.update_entity(
                        filename=filename,
                        entity_name=from_entity,
                        updates={},
                        append_history=f"Related to [[{to_entity}]]",
                    )

        # Re-index everything touched
        for filename in files_modified:
            self.index.index_file(self.store, filename)

        return {**state, "files_modified": files_modified}

    def respond(self, state: NotebookState) -> NotebookState:
        """Generate natural response based on intent and results."""
        intent = state.get("intent", "chat")
        user_input = state.get("user_input", "")
        messages = state.get("messages", [])

        # Build context for response
        context_parts = []

        if intent == "query":
            chunks = state.get("retrieved_chunks", [])
            if chunks:
                # For listing queries (many results), pass names + related tags to LLM for grouping
                if len(chunks) > 5:
                    context_parts.append(f"Found {len(chunks)} matching items. Group them logically when presenting to the user:")
                    for chunk in chunks:
                        meta = chunk.get('metadata', {})
                        name = meta.get('entity_name', 'Unknown')
                        related_str = meta.get('related', '')
                        if related_str:
                            context_parts.append(f"- {name} (related: {related_str})")
                        else:
                            context_parts.append(f"- {name}")
                else:
                    # For specific queries, show full content
                    context_parts.append("Relevant information from the notebook:")
                    for chunk in chunks:
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

            # Collect search queries: entity names + observation text
            search_queries = [
                e.get("resolved_name", e["name"])
                for e in entities
            ] + [
                u.get("entity", "") for u in updates if u.get("entity")
            ] + observations

            # Fetch related context for each query
            related_chunks = []
            seen_ids = set()
            for name in search_queries:
                if not name:
                    continue
                results = self.index.hybrid_search(semantic_query=name, top_k=3)
                for chunk in results:
                    cid = chunk.get("chunk_id")
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        related_chunks.append(chunk)

            # Also pull open todos related to what was just recorded/updated,
            # so the response can mention unblocked next steps
            combined_query = " ".join(q for q in search_queries if q)
            if combined_query:
                open_todos = self.index.hybrid_search(
                    semantic_query=combined_query,
                    filters={"entity_type": "todos", "status": "open"},
                    top_k=3,
                )
                for chunk in open_todos:
                    cid = chunk.get("chunk_id")
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        related_chunks.append(chunk)

            if related_chunks:
                context_parts.append("\nRelated information from the notebook:")
                for chunk in related_chunks:
                    context_parts.append(f"---\n{chunk.get('content', '')}\n---")

        # Build response prompt
        context_str = "\n".join(context_parts) if context_parts else ""

        response_prompt = f"""User's message: {user_input}

Intent: {intent}

{context_str}

Respond naturally and concisely. Remember:
- For recording: acknowledge what was recorded, then mention any relevant related info AND any open next steps or quests from the notebook context above
- For updates: acknowledge the change, then explicitly mention what is now unblocked or what the next open step is, using the notebook context above
- For queries: answer directly using the retrieved information
- For chat: respond naturally

Do not explain your process or mention files."""

        # Include recent conversation for context
        conversation_messages = [
            SystemMessage(content=NOTEBOOK_SYSTEM_PROMPT),
        ]

        # Add recent messages
        for msg in messages[-6:]:
            conversation_messages.append(msg)

        conversation_messages.append(HumanMessage(content=response_prompt))

        response = self.llm.invoke(conversation_messages)

        return {**state, "response": response.content}

    def _propagate_completion_to_related(self, todo_name: str, todo_file: str) -> list[str]:
        """When a todo is completed, update the Status of related items to 'found'.

        Only propagates to item entities (things.md) whose current status
        indicates they haven't been obtained yet (lost, not obtained, not recovered).
        """
        chunks = self.store.parse_into_chunks(todo_file)
        todo_chunk = next((c for c in chunks if c.entity_name.lower() == todo_name.lower()), None)
        if not todo_chunk:
            return []

        files_modified = []
        unacquired = {"lost", "not obtained", "not recovered", "unknown"}

        for related_name in todo_chunk.related:
            related_file = self._find_entity_file(related_name)
            if not related_file or related_file not in ("things.md",):
                continue
            related_chunks = self.store.parse_into_chunks(related_file)
            related_chunk = next(
                (c for c in related_chunks if c.entity_name.lower() == related_name.lower()), None
            )
            if not related_chunk:
                continue
            current_status = (related_chunk.status or "").lower()
            if any(s in current_status for s in unacquired):
                self.store.update_entity(
                    filename=related_file,
                    entity_name=related_name,
                    updates={"Status": "found"},
                )
                if related_file not in files_modified:
                    files_modified.append(related_file)

        return files_modified

    def _get_file_for_type(self, entity_type: str) -> str:
        """Get the filename for an entity type."""
        type_to_file = {
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
        return type_to_file.get(entity_type, "todos.md")

    def _find_entity_file(self, entity_name: str) -> str | None:
        """Find which file contains an entity."""
        for file_path in self.store.list_files():
            chunks = self.store.parse_into_chunks(file_path.name)
            for chunk in chunks:
                if chunk.entity_name.lower() == entity_name.lower():
                    return file_path.name
        return None
