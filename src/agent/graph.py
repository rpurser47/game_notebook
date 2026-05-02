"""LangGraph definition for the notebook agent."""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph

from ..storage.index import NotebookIndex
from ..storage.markdown import MarkdownStore
from .nodes import NodeFactory
from .state import NotebookState


def route_by_intent(state: NotebookState) -> Literal["record", "query", "update", "chat"]:
    """Route to the appropriate branch based on intent."""
    return state.get("intent", "chat")


def create_graph(
    llm: BaseChatModel,
    store: MarkdownStore,
    index: NotebookIndex,
) -> StateGraph:
    """Create the notebook agent graph."""
    # Create node factory
    factory = NodeFactory(llm, store, index)

    # Create graph
    graph = StateGraph(NotebookState)

    # Add nodes
    graph.add_node("router", factory.router)
    graph.add_node("extract", factory.extract)
    graph.add_node("resolve", factory.resolve)
    graph.add_node("analyze_query", factory.analyze_query)
    graph.add_node("retrieve", factory.retrieve)
    graph.add_node("write", factory.write)
    graph.add_node("modify", factory.modify)
    graph.add_node("respond", factory.respond)

    # Set entry point
    graph.set_entry_point("router")

    # Add conditional edges from router
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

    # Record flow: extract -> resolve -> write -> respond
    graph.add_edge("extract", "resolve")

    # After resolve, check intent for next step
    def route_after_resolve(state: NotebookState) -> Literal["write", "modify"]:
        intent = state.get("intent", "record")
        if intent == "update":
            return "modify"
        return "write"

    graph.add_conditional_edges(
        "resolve",
        route_after_resolve,
        {
            "write": "write",
            "modify": "modify",
        },
    )

    graph.add_edge("write", "respond")
    graph.add_edge("modify", "respond")

    # Query flow: analyze_query -> retrieve -> respond
    graph.add_edge("analyze_query", "retrieve")
    graph.add_edge("retrieve", "respond")

    # End after respond
    graph.add_edge("respond", END)

    return graph.compile()


class NotebookAgent:
    """High-level interface for the notebook agent."""

    def __init__(
        self,
        llm: BaseChatModel,
        store: MarkdownStore,
        index: NotebookIndex,
    ):
        self.llm = llm
        self.store = store
        self.index = index
        self.graph = create_graph(llm, store, index)
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

        # Add user message to history
        self.messages.append(HumanMessage(content=user_input))

        # Run graph
        state: NotebookState = {
            "messages": self.messages.copy(),
            "user_input": user_input,
        }

        result = self.graph.invoke(state)

        response = result.get("response", "I'm not sure how to respond to that.")

        # Add assistant message to history
        self.messages.append(AIMessage(content=response))

        # Persist conversation
        self.store.append_conversation("user", user_input)
        self.store.append_conversation("assistant", response)

        # Trim messages if too long
        if len(self.messages) > 40:
            self.messages = self.messages[-40:]

        return response

    def get_stats(self) -> dict:
        """Get agent statistics."""
        index_stats = self.index.get_stats()
        return {
            "messages_in_memory": len(self.messages),
            "total_chunks": index_stats["total_chunks"],
            "files": len(self.store.list_files()),
        }
