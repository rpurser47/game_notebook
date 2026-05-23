"""CLI interface for the notebook agent."""

import sys

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme


class NotebookCLI:
    """Terminal interface for the notebook agent."""

    def __init__(self, agent):
        self.agent = agent
        self.console = Console()
        # Console with light purple theme for responses
        self.response_console = Console(
            theme=Theme({
                "markdown.paragraph": "plum1",
                "markdown.text": "plum1",
                "markdown.item.bullet": "plum1",
                "markdown.item.number": "plum1",
                "markdown.emph": "italic plum1",
                "markdown.strong": "bold plum1",
                "markdown.code": "bright_white on grey23",
                "markdown.code_block": "bright_white on grey23",
                "markdown.h1": "bold plum1",
                "markdown.h2": "bold plum1",
                "markdown.h3": "bold plum1",
                "markdown.link": "underline plum1",
            })
        )

    def display_banner(self) -> None:
        """Display startup banner."""
        banner = Panel(
            Text.from_markup(
                "[bold]Game Notebook[/bold]\n"
                "[dim]A memory for your adventures[/dim]"
            ),
            border_style="blue",
        )
        self.console.print(banner)
        self.console.print()

    def display_stats(self, stats: dict) -> None:
        """Display index statistics."""
        entity_part = f" · {stats['entities']} entities" if "entities" in stats else ""
        self.console.print(
            f"[dim]Loaded {stats['total_chunks']} chunks from {stats['files']} files{entity_part}.[/dim]"
        )

    def display_history(self, history: list[dict]) -> None:
        """Display conversation history."""
        if not history:
            self.console.print("[dim]No previous conversation.[/dim]")
            return

        self.console.print(f"[dim]Restored {len(history)} messages.[/dim]")
        self.console.print()
        self.console.rule(style="dim")
        self.console.print()

        for msg in history:
            if msg["role"] == "user":
                self.console.print(f"[dim]>[/dim] [dim]{msg['content']}[/dim]")
            else:
                # Render assistant response as markdown (dimmed for history)
                self.console.print("[dim magenta]notebook:[/dim magenta]")
                self.console.print(f"[dim]{msg['content']}[/dim]")
            self.console.print()

        self.console.rule(style="dim")
        self.console.print()

    def display_response(self, response: str) -> None:
        """Display agent response with markdown rendering."""
        self.console.print("[medium_purple1]notebook:[/medium_purple1]")
        self.response_console.print(Markdown(response))
        self.console.print()

    def display_error(self, error: str) -> None:
        """Display an error message."""
        self.console.print(f"[red]Error:[/red] {error}")

    def display_status(self) -> None:
        """Display current status."""
        stats = self.agent.get_stats()
        entity_part = f" | Entities: {stats['entities']}" if "entities" in stats else ""
        self.console.print(
            f"[dim]Chunks: {stats['total_chunks']} | "
            f"Files: {stats['files']}{entity_part} | "
            f"Messages in memory: {stats['messages_in_memory']}[/dim]"
        )

    def handle_command(self, command: str) -> bool:
        """Handle a slash command. Returns True to continue, False to exit."""
        command = command.strip().lower()

        if command in ("/quit", "/exit", "/q"):
            self.console.print("[dim]Goodbye![/dim]")
            return False

        elif command == "/status":
            self.display_status()

        elif command == "/reindex":
            self.console.print("[dim]Reindexing...[/dim]")
            count = self.agent.index.index_all(self.agent.store)
            stats = self.agent.index.get_stats()
            self.console.print(f"[dim]Updated {count} chunks ({stats['total_chunks']} total).[/dim]")

        elif command == "/rebuild":
            self.console.print("[dim]Rebuilding index from scratch...[/dim]")
            # Clear the collection
            self.agent.index.collection.delete(where={})
            self.agent.index.chunk_hashes.clear()
            self.agent.index._save_hashes()
            # Re-index everything
            count = self.agent.index.index_all(self.agent.store)
            self.console.print(f"[dim]Rebuilt index with {count} chunks.[/dim]")

        elif command == "/clear":
            self.agent.store.clear_conversation_history()
            self.agent.messages = []
            self.console.print("[dim]Conversation history cleared.[/dim]")

        elif command == "/help":
            help_text = """
[bold]Commands:[/bold]
  /quit, /exit, /q  - Exit the notebook
  /status           - Show index statistics
  /reindex          - Re-index changed files
  /rebuild          - Delete and rebuild entire index
  /clear            - Clear conversation history
  /help             - Show this help
            """
            self.console.print(help_text.strip())

        else:
            self.console.print(f"[dim]Unknown command: {command}[/dim]")

        return True

    def run(self) -> None:
        """Run the main CLI loop."""
        # Display startup
        self.display_banner()

        # Load and display history
        try:
            history = self.agent.load_history(limit=20)
            stats = self.agent.get_stats()
            self.display_stats(stats)
            self.display_history(history)
        except Exception as e:
            self.display_error(f"Failed to load history: {e}")

        # Main loop
        while True:
            try:
                # Get input
                user_input = self.console.input("[bold yellow]>[/bold yellow] ").strip()

                if not user_input:
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    if not self.handle_command(user_input):
                        break
                    continue

                # Process with agent
                response = self.agent.chat(user_input)
                self.display_response(response)

            except KeyboardInterrupt:
                self.console.print("\n[dim]Use /quit to exit.[/dim]")

            except EOFError:
                self.console.print("\n[dim]Goodbye![/dim]")
                break

            except Exception as e:
                self.display_error(str(e))


def run_cli(agent) -> None:
    """Run the CLI with the given agent."""
    cli = NotebookCLI(agent)
    cli.run()
