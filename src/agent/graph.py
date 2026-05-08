"""LangGraph definition for the notebook agent."""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph

from ..storage.db import NotebookDB
from ..storage.index import NotebookIndex
from ..storage.markdown import MarkdownStore
from .nodes import NodeFactory
from .state import NotebookState


def route_by_intent(state: NotebookState) -> Literal["record", "query", "update", "chat"]:
    return state.get("intent", "chat")


def route_after_conflict_check(state: NotebookState) -> Literal["persist", "respond"]:
    """Skip persist and go straight to respond if conflicts were found."""
    if state.get("conflicts"):
        return "respond"
    return "persist"


def create_graph(
    llm: BaseChatModel,
    store: MarkdownStore,
    index: NotebookIndex,
    db: NotebookDB,
) -> StateGraph:
    """Create the notebook agent graph."""
    factory = NodeFactory(llm, store, index, db)

    graph = StateGraph(NotebookState)

    graph.add_node("router", factory.router)
    graph.add_node("extract", factory.extract)
    graph.add_node("resolve", factory.resolve)
    graph.add_node("conflict_check", factory.conflict_check)
    graph.add_node("analyze_query", factory.analyze_query)
    graph.add_node("retrieve", factory.retrieve)
    graph.add_node("reflect", factory.reflect)
    graph.add_node("persist", factory.persist)
    graph.add_node("respond", factory.respond)

    graph.set_entry_point("router")

    graph.add_conditional_edges(
        "router",
        route_by_intent,
        {
            "record": "extract",
            "query": "analyze_query",
            "update": "extract",
            "chat": "respond",
        },
    )

    # Record/update flow: extract -> resolve -> conflict_check -> persist|respond
    graph.add_edge("extract", "resolve")
    graph.add_edge("resolve", "conflict_check")
    graph.add_conditional_edges(
        "conflict_check",
        route_after_conflict_check,
        {
            "persist": "persist",
            "respond": "respond",
        },
    )
    graph.add_edge("persist", "respond")

    # Query flow: analyze_query -> retrieve -> reflect -> respond
    graph.add_edge("analyze_query", "retrieve")
    graph.add_edge("retrieve", "reflect")
    graph.add_edge("reflect", "respond")

    graph.add_edge("respond", END)

    return graph.compile()


class NotebookAgent:
    """High-level interface for the notebook agent."""

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
        self.graph = create_graph(llm, store, index, db)
        self.messages = []

    def load_history(self, limit: int = 20) -> list[dict]:
        """Load conversation history from storage."""
        from langchain_core.messages import AIMessage, HumanMessage

        history = self.store.load_conversation_history(limit)
        self.messages = []

        for msg in history:
            if msg["role"] == "user":
                self.messages.append(HumanMessage(content=msg["content"]))
            else:
                self.messages.append(AIMessage(content=msg["content"]))

        return history

    def chat(self, user_input: str) -> str:
        """Process user input and return response."""
        from langchain_core.messages import AIMessage, HumanMessage

        self.messages.append(HumanMessage(content=user_input))

        state: NotebookState = {
            "messages": self.messages.copy(),
            "user_input": user_input,
        }

        result = self.graph.invoke(state)

        response = result.get("response", "I'm not sure how to respond to that.")

        self.messages.append(AIMessage(content=response))
        self.store.append_conversation("user", user_input)
        self.store.append_conversation("assistant", response)

        if len(self.messages) > 40:
            self.messages = self.messages[-40:]

        return response

    def get_stats(self) -> dict:
        """Get agent statistics."""
        index_stats = self.index.get_stats()
        db_stats = self.db.get_stats()
        return {
            "messages_in_memory": len(self.messages),
            "total_chunks": index_stats["total_chunks"],
            "files": len(self.store.list_files()),
            "entities": db_stats["entities"],
            "relationships": db_stats["relationships"],
        }
