"""E2E: querying the notebook."""

import pytest


@pytest.mark.e2e
class TestQueryKnownNPC:
    def test_returns_rupert_details(self, agent):
        response = agent.chat("What do I know about Rupert Sanford?")
        lower = response.lower()
        assert "custodian" in lower or "cleaning" in lower or "supplies" in lower

    def test_returns_roger_details(self, agent):
        response = agent.chat("What do I know about Roger?")
        lower = response.lower()
        assert "key" in lower or "loadmaster" in lower


@pytest.mark.e2e
class TestQueryOpenQuests:
    def test_open_quests_returned_correctly(self, agent):
        """Open quests listed; no hallucinated completions."""
        response = agent.chat("What quests are still open?")
        lower = response.lower()
        assert "epsilon" in lower or "key" in lower or "storage" in lower
        assert "completed" not in lower


@pytest.mark.e2e
class TestQueryOpenMysteries:
    def test_mysteries_returned(self, agent):
        response = agent.chat("What mysteries am I tracking?")
        lower = response.lower()
        assert "lambda" in lower or "radiation" in lower or "supplies" in lower or "rupert" in lower


@pytest.mark.e2e
class TestQueryNumericCodes:
    """Regression: asking about codes returned nothing on first ask.

    Uses a class-scoped agent so seed_codes runs once for all three assertions.
    """

    @pytest.fixture(scope="class")
    def agent_with_codes(self, tmp_path_factory):
        """Class-scoped agent seeded with three codes."""
        import os
        from dotenv import load_dotenv
        from langchain_openai import ChatOpenAI
        from src.storage.markdown import MarkdownStore
        from src.storage.index import NotebookIndex
        from src.storage.db import NotebookDB
        from src.storage.migrate import migrate
        from src.agent.graph import NotebookAgent

        load_dotenv()
        nb = tmp_path_factory.mktemp("codes_notebook")
        store = MarkdownStore(nb)

        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n")
        store.write_file("places.md", "---\ntype: locations\ndescription: Locations\n---\n")
        store.write_file("todos.md", "---\ntype: todos\ndescription: Quests\n---\n")
        store.write_file("journal.md", "---\ntype: observations\ndescription: Journal\n---\n\n# Journal\n")

        llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o"), temperature=0.3)
        index = NotebookIndex(nb, embedding_provider="local")
        index.index_all(store)
        db = NotebookDB(nb)
        migrate(nb, db)
        a = NotebookAgent(llm, store, index, db)

        a.chat("I found a crate code: 1234. Target lock not identified yet.")
        a.chat("I found another crate code: 5678. Haven't used it.")
        a.chat("I opened a locked box using code 9999.")
        return a

    def test_all_codes_listed_and_query_not_empty(self, agent_with_codes):
        """All three codes returned on direct request; no false 'none' claim."""
        response = agent_with_codes.chat("list all known numeric codes")
        assert "1234" in response
        assert "5678" in response
        assert "9999" in response

    def test_unused_codes_returned_on_first_ask(self, agent_with_codes):
        """Regression: unused codes should surface without rephrasing."""
        response = agent_with_codes.chat("what numeric codes do I have that I haven't used?")
        assert "1234" in response or "5678" in response

    def test_does_not_claim_no_codes_exist(self, agent_with_codes):
        response = agent_with_codes.chat("what numeric codes do I have?")
        lower = response.lower()
        assert "no codes" not in lower
        assert "haven't told me any" not in lower
        assert "none recorded" not in lower


@pytest.mark.e2e
class TestQueryDoesNotModifyFiles:
    def test_query_leaves_files_unchanged(self, agent):
        import time
        people_path = agent.store.notebook_path / "people.md"
        before_mtime = people_path.stat().st_mtime
        time.sleep(0.1)
        agent.chat("What do I know about Roger?")
        after_mtime = people_path.stat().st_mtime
        assert before_mtime == after_mtime
