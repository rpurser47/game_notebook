"""Markdown file storage and parsing."""

import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EntityChunk:
    """A chunk of content representing an entity or journal session."""

    file: str
    entity_name: str
    entity_type: str
    content: str
    status: str | None = None
    location: str | None = None
    related: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        return f"{self.file}::{self.entity_name}"


@dataclass
class FileFrontmatter:
    """Parsed YAML frontmatter from a markdown file."""

    type: str
    description: str = ""
    extra: dict = field(default_factory=dict)


class MarkdownStore:
    """Handles reading, writing, and parsing markdown files."""

    def __init__(self, notebook_path: str | Path):
        self.notebook_path = Path(notebook_path)
        self.notebook_path.mkdir(parents=True, exist_ok=True)

        # Ensure .history directory exists
        self.history_path = self.notebook_path / ".history"
        self.history_path.mkdir(exist_ok=True)

    def list_files(self) -> list[Path]:
        """List all markdown files in the notebook."""
        return [
            f for f in self.notebook_path.glob("*.md")
            if not f.name.startswith(".")
        ]

    def read_file(self, filename: str) -> str:
        """Read a markdown file's content."""
        path = self.notebook_path / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_file(self, filename: str, content: str) -> None:
        """Write content to a markdown file."""
        path = self.notebook_path / filename
        path.write_text(content, encoding="utf-8")

    def parse_frontmatter(self, content: str) -> tuple[FileFrontmatter | None, str]:
        """Extract YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return None, content

        match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
        if not match:
            return None, content

        try:
            yaml_content = yaml.safe_load(match.group(1))
            frontmatter = FileFrontmatter(
                type=yaml_content.get("type", "unknown"),
                description=yaml_content.get("description", ""),
                extra={k: v for k, v in yaml_content.items() if k not in ("type", "description")},
            )
            return frontmatter, match.group(2)
        except yaml.YAMLError:
            return None, content

    def parse_entity_fields(self, content: str) -> dict:
        """Parse **Field:** values from entity content.

        Scans the entire section, including content after history blocks.
        When a field appears multiple times, the last occurrence wins.
        """
        fields = {}

        def _last(pattern: str, text: str) -> str | None:
            """Return the last match for a field pattern (handles duplicate fields)."""
            matches = re.findall(pattern, text)
            return matches[-1].strip() if matches else None

        status = _last(r"\*\*Status:\*\*\s*(.+?)(?:\n|$)", content)
        if status:
            fields["status"] = status.lower()

        location = _last(r"\*\*Location:\*\*\s*(.+?)(?:\n|$)", content)
        if location:
            fields["location"] = location

        role = _last(r"\*\*Role:\*\*\s*(.+?)(?:\n|$)", content)
        if role:
            fields["role"] = role

        category = _last(r"\*\*Category:\*\*\s*(.+?)(?:\n|$)", content)
        if category:
            fields["category"] = category.lower()

        explored = _last(r"\*\*Explored:\*\*\s*(.+?)(?:\n|$)", content)
        if explored:
            fields["explored"] = explored.lower()

        position = _last(r"\*\*Position:\*\*\s*(.+?)(?:\n|$)", content)
        if position:
            fields["position"] = position

        parent_matches = re.findall(r"\*\*Parent:\*\*\s*(.+?)(?:\n|$)", content)
        if parent_matches:
            fields["parent"] = re.findall(r"\[\[(.+?)\]\]", parent_matches[-1])

        subtype = _last(r"\*\*Subtype:\*\*\s*(.+?)(?:\n|$)", content)
        if subtype:
            fields["subtype"] = subtype.lower()

        date = _last(r"\*\*Date:\*\*\s*(.+?)(?:\n|$)", content)
        if date:
            fields["date"] = date

        description = _last(r"\*\*Description:\*\*\s*(.+?)(?:\n|$)", content)
        if description:
            fields["description"] = description

        outcome = _last(r"\*\*Outcome:\*\*\s*(.+?)(?:\n|$)", content)
        if outcome:
            fields["outcome"] = outcome

        # Related: collect wiki-links from the last **Related:** line
        related_matches = re.findall(r"\*\*Related:\*\*\s*(.+?)(?:\n|$)", content)
        if related_matches:
            fields["related"] = re.findall(r"\[\[(.+?)\]\]", related_matches[-1])

        return fields

    def parse_into_chunks(self, filename: str) -> list[EntityChunk]:
        """Parse a markdown file into entity chunks."""
        content = self.read_file(filename)
        if not content:
            return []

        frontmatter, body = self.parse_frontmatter(content)
        file_type = frontmatter.type if frontmatter else "unknown"

        chunks = []

        # Split on ## headers
        sections = re.split(r"\n(?=## )", body)

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Extract header
            header_match = re.match(r"^## (.+?)(?:\n|$)", section)
            if not header_match:
                continue

            entity_name = header_match.group(1).strip()
            entity_content = section

            # Parse fields
            fields = self.parse_entity_fields(entity_content)

            chunk = EntityChunk(
                file=filename,
                entity_name=entity_name,
                entity_type=file_type,
                content=entity_content,
                status=fields.get("status"),
                location=fields.get("location"),
                related=fields.get("related", []),
                metadata=fields,
            )
            chunks.append(chunk)

        return chunks

    def get_all_chunks(self) -> list[EntityChunk]:
        """Parse all markdown files into chunks."""
        all_chunks = []
        for file_path in self.list_files():
            chunks = self.parse_into_chunks(file_path.name)
            all_chunks.extend(chunks)
        return all_chunks

    def get_known_entities(self) -> dict[str, list[str]]:
        """Get all known entity names grouped by type."""
        entities: dict[str, list[str]] = {}
        for chunk in self.get_all_chunks():
            if chunk.entity_type not in entities:
                entities[chunk.entity_type] = []
            entities[chunk.entity_type].append(chunk.entity_name)
        return entities

    def append_to_journal(self, observations: list[str], date: str | None = None) -> None:
        """Append observations to the journal as a new session."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d %H:%M")

        content = self.read_file("journal.md")

        # Build new session entry
        session_entry = f"\n## Session — {date}\n"
        for obs in observations:
            session_entry += f"- {obs}\n"

        # Append to file
        new_content = content.rstrip() + "\n" + session_entry
        self.write_file("journal.md", new_content)

    def update_entity(
        self,
        filename: str,
        entity_name: str,
        updates: dict,
        append_history: str | None = None,
    ) -> bool:
        """Update an entity's fields or append to its history."""
        content = self.read_file(filename)
        if not content:
            return False

        # Find the entity section
        pattern = rf"(## {re.escape(entity_name)}\n)(.*?)(?=\n## |\Z)"
        match = re.search(pattern, content, re.DOTALL)

        if not match:
            return False

        header = match.group(1)
        section_content = match.group(2)

        # Update fields
        for field_name, new_value in updates.items():
            field_pattern = rf"(\*\*{field_name}:\*\*\s*)(.+?)(\n)"
            field_match = re.search(field_pattern, section_content)
            if field_match:
                section_content = re.sub(
                    field_pattern,
                    rf"\g<1>{new_value}\3",
                    section_content,
                )
            else:
                # Field doesn't exist yet — insert after the last **Field:** line
                last_field = list(re.finditer(r"\*\*\w[\w ]*:\*\*[^\n]*\n", section_content))
                insert_pos = last_field[-1].end() if last_field else len(section_content)
                section_content = (
                    section_content[:insert_pos]
                    + f"**{field_name}:** {new_value}\n"
                    + section_content[insert_pos:]
                )

        # Append to history if provided
        if append_history:
            date = datetime.now().strftime("%Y-%m-%d")
            history_entry = f"\n### {date}\n- {append_history}\n"
            section_content = section_content.rstrip() + history_entry

        # Replace in content
        new_section = header + section_content
        new_content = content[: match.start()] + new_section + content[match.end() :]
        self.write_file(filename, new_content)
        return True

    def create_entity(
        self,
        filename: str,
        entity_name: str,
        entity_type: str,
        fields: dict,
    ) -> None:
        """Add a new entity to a file."""
        content = self.read_file(filename)

        # Build entity section
        section = f"\n## {entity_name}\n"

        # characters
        if "role" in fields:
            section += f"**Role:** {fields['role']}\n"
        if "location" in fields:
            section += f"**Location:** {fields['location']}\n"
        if "status" in fields:
            section += f"**Status:** {fields['status']}\n"

        # locations / places
        if "explored" in fields:
            section += f"**Explored:** {fields['explored']}\n"
        if "position" in fields:
            section += f"**Position:** {fields['position']}\n"
        if "parent" in fields:
            parent_val = fields["parent"]
            if isinstance(parent_val, list):
                section += f"**Parent:** {', '.join(f'[[{p}]]' for p in parent_val)}\n"
            else:
                section += f"**Parent:** [[{parent_val}]]\n"

        # items / things
        if "category" in fields:
            section += f"**Category:** {fields['category']}\n"

        # todos
        if "subtype" in fields:
            section += f"**Subtype:** {fields['subtype']}\n"
        if "status" not in fields and entity_type in ("todo", "todos", "quest", "mystery", "plan"):
            section += "**Status:** open\n"
        if "requires" in fields:
            req = fields["requires"]
            if req and req != "(none)":
                section += f"**Requires:** [[{req}]]\n"
            else:
                section += "**Requires:** (none)\n"
        if "part_of" in fields or "part-of" in fields:
            parent_todo = fields.get("part_of") or fields.get("part-of")
            section += f"**Part-of:** [[{parent_todo}]]\n"

        # events
        if "date" in fields:
            section += f"**Date:** {fields['date']}\n"

        # shared
        if "description" in fields:
            section += f"**Description:** {fields['description']}\n"
        if "related" in fields and fields["related"]:
            related = fields["related"]
            if isinstance(related, list):
                related_str = ", ".join(f"[[{r}]]" for r in related)
            else:
                related_str = f"[[{related}]]"
            section += f"**Related:** {related_str}\n"

        # Append to file
        new_content = content.rstrip() + "\n" + section
        self.write_file(filename, new_content)

    def create_topic_file(
        self,
        topic_name: str,
        file_type: str,
        description: str,
    ) -> str:
        """Create a new markdown file for an emerging topic."""
        # Generate filename from topic name
        filename = re.sub(r"[^\w\s-]", "", topic_name.lower())
        filename = re.sub(r"[\s_]+", "_", filename) + ".md"

        content = f"""---
type: {file_type}
description: {description}
---

# {topic_name}

"""
        self.write_file(filename, content)

        # Update README
        self._update_readme(filename, file_type, description)

        return filename

    def _update_readme(self, filename: str, file_type: str, description: str) -> None:
        """Update README.md to include a new file."""
        readme_content = self.read_file("README.md")
        if not readme_content:
            return

        # Find the files table and add entry
        table_pattern = r"(\| File \| Type \| Description \|\n\|.*?\|.*?\|.*?\|\n)((?:\|.*?\|.*?\|.*?\|\n)*)"
        match = re.search(table_pattern, readme_content)

        if match:
            table_header = match.group(1)
            table_rows = match.group(2)
            new_row = f"| `{filename}` | {file_type} | {description} |\n"
            new_table = table_header + table_rows + new_row
            readme_content = readme_content[: match.start()] + new_table + readme_content[match.end() :]
            self.write_file("README.md", readme_content)

    # Conversation history management

    def load_conversation_history(self, limit: int = 20) -> list[dict]:
        """Load recent conversation history."""
        import json

        history_file = self.history_path / "conversation.jsonl"
        if not history_file.exists():
            return []

        messages = []
        with open(history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    messages.append(json.loads(line))

        # Return last N messages
        return messages[-limit:]

    def append_conversation(self, role: str, content: str) -> None:
        """Append a message to conversation history."""
        import json

        history_file = self.history_path / "conversation.jsonl"

        message = {
            "role": role,
            "content": content,
            "ts": datetime.now().isoformat(),
        }

        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(message) + "\n")

    def clear_conversation_history(self) -> None:
        """Clear conversation history."""
        history_file = self.history_path / "conversation.jsonl"
        if history_file.exists():
            history_file.unlink()
