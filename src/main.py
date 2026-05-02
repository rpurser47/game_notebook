"""Main entry point for the notebook agent."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def get_llm(provider: str, model: str | None = None):
    """Get the appropriate LLM based on provider."""
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or os.getenv("OPENAI_MODEL", "gpt-4o"),
            temperature=0.7,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            temperature=0.7,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def main():
    """Main entry point."""
    # Load environment variables
    load_dotenv()

    # Get configuration
    notebook_path = os.getenv("NOTEBOOK_PATH", "./notebook")
    llm_provider = os.getenv("LLM_PROVIDER", "openai")
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "local")

    # Validate notebook path
    notebook_path = Path(notebook_path)
    if not notebook_path.exists():
        print(f"Error: Notebook path does not exist: {notebook_path}")
        print("Please create the notebook directory or set NOTEBOOK_PATH in .env")
        sys.exit(1)

    # Initialize components
    print("Initializing notebook...")

    try:
        # Get LLM
        llm = get_llm(llm_provider)

        # Initialize storage
        from .storage.markdown import MarkdownStore
        from .storage.index import NotebookIndex

        store = MarkdownStore(notebook_path)
        index = NotebookIndex(notebook_path, embedding_provider)

        # Reindex all files on startup (cleans up orphaned chunks)
        print("Reindexing knowledge base...")
        updated_count = index.index_all(store)
        stats = index.get_stats()
        print(f"Indexed {stats['total_chunks']} chunks ({updated_count} updated).")

        # Create agent
        from .agent.graph import NotebookAgent

        agent = NotebookAgent(llm, store, index)

        # Run CLI
        from .cli.interface import run_cli

        run_cli(agent)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
