"""One-time migration: parse existing markdown files into SQLite.

Run with:
    uv run python -m src.storage.migrate

Idempotent — safe to re-run. Uses INSERT OR IGNORE on (name, type) so
existing entities are not duplicated. Field values are overwritten on
re-run (last-write-wins), which is fine since the markdown is the source
of truth during migration.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .db import NotebookDB
from .markdown import MarkdownStore


# ---------------------------------------------------------------------------
# Type mapping: markdown file frontmatter type → DB entity type
# ---------------------------------------------------------------------------
FILE_TO_TYPE: dict[str, str] = {
    "characters": "characters",
    "locations": "locations",
    "items": "items",
    "todos": "todos",
    "events": "events",
    "equipment": "items",
    "hazards": "events",
    "observations": "observations",
}

# Files to skip entirely
SKIP_FILES = {"README.md", "journal.md"}


@dataclass
class MigrationReport:
    entities_inserted: int = 0
    fields_written: int = 0
    relationships_written: int = 0
    history_entries_written: int = 0
    aliases_extracted: int = 0
    skipped_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _parse_history_entries(section_content: str) -> list[tuple[str, str]]:
    """
    Extract ### YYYY-MM-DD history blocks from a section.
    Returns list of (date, note) tuples, one per bullet point.
    Skips bare 'Related to [[X]]' bullets (those go into relationships).
    """
    entries = []
    # Find all ### date headers and capture their bullet content
    pattern = re.compile(r"### (\d{4}-\d{2}-\d{2})\n((?:- .+\n?)*)", re.MULTILINE)
    for match in pattern.finditer(section_content):
        date = match.group(1)
        bullets_text = match.group(2)
        for bullet in re.finditer(r"^- (.+)$", bullets_text, re.MULTILINE):
            note = bullet.group(1).strip()
            # Skip pure relationship entries — they're captured separately
            if re.match(r"^Related to \[\[.+\]\]$", note):
                continue
            entries.append((date, note))
    return entries


def _extract_inline_aliases(entity_name: str, content: str) -> list[str]:
    """
    Heuristically extract alternate names from prose bullets.
    Looks for patterns like:
      - Full name: Foo Bar (confirmed ...)
      - Known as "Sam"
      - Also called X
    """
    aliases = []

    # "Full name: X", "Full name appears to be X", or "Full name is X"
    m = re.search(r"[Ff]ull name(?:\s+(?:appears\s+to\s+be|is))?:?\s+([A-Z][^\n(]+?)(?:\s*\(|$)", content)
    if m:
        candidate = m.group(1).strip().rstrip(".")
        if candidate.lower() != entity_name.lower():
            aliases.append(candidate)

    # Known as "X" or known as X
    for m in re.finditer(r'[Kk]nown as ["“]?([A-Z][a-zA-Z]+)["”]?', content):
        candidate = m.group(1).strip()
        if candidate.lower() != entity_name.lower():
            aliases.append(candidate)

    return aliases


def migrate(notebook_path: Path, db: NotebookDB) -> MigrationReport:
    """Parse all markdown files and populate the SQLite database."""
    store = MarkdownStore(notebook_path)
    report = MigrationReport()

    for md_file in sorted(notebook_path.glob("*.md")):
        if md_file.name in SKIP_FILES:
            report.skipped_files.append(md_file.name)
            continue

        content = md_file.read_text(encoding="utf-8")
        frontmatter, body = store.parse_frontmatter(content)

        if not frontmatter:
            report.warnings.append(f"{md_file.name}: no frontmatter, skipping")
            continue

        raw_type = frontmatter.type
        entity_type = FILE_TO_TYPE.get(raw_type, raw_type)

        # Split into ## sections
        sections = re.split(r"\n(?=## )", body)

        for section in sections:
            section = section.strip()
            if not section:
                continue

            header_match = re.match(r"^## (.+?)(?:\n|$)", section)
            if not header_match:
                continue

            entity_name = header_match.group(1).strip()
            section_body = section[header_match.end():]

            # Parse all **Field:** values from the entire section (including
            # content that appears after history blocks — some entries have
            # fields scattered throughout)
            fields = store.parse_entity_fields(section)
            status = fields.get("status")

            # Insert entity
            entity_id = db.insert_entity(
                name=entity_name,
                type=entity_type,
                status=status,
                source="narrator",
                confidence="certain",
            )
            report.entities_inserted += 1

            # Insert all fields
            field_map = {
                "role": "role",
                "location": "location",
                "status": "status",
                "explored": "explored",
                "position": "position",
                "category": "category",
                "subtype": "subtype",
                "date": "date",
                "description": "description",
                "outcome": "outcome",
            }

            for key, db_field in field_map.items():
                value = fields.get(key)
                if value and isinstance(value, str):
                    db.upsert_field(
                        entity_id, db_field, value,
                        source="narrator", confidence="certain",
                    )
                    report.fields_written += 1

            # Parent field (list → comma-separated string)
            parent = fields.get("parent")
            if parent:
                if isinstance(parent, list):
                    parent_str = ", ".join(parent)
                else:
                    parent_str = str(parent)
                db.upsert_field(
                    entity_id, "parent", parent_str,
                    source="narrator", confidence="certain",
                )
                report.fields_written += 1

            # Related links → relationships table
            related = fields.get("related", [])
            if isinstance(related, list):
                for to_name in related:
                    db.insert_relationship(entity_id, to_name, "related to")
                    report.relationships_written += 1

            # History entries → entity_history table
            for date, note in _parse_history_entries(section_body):
                db.insert_history(entity_id, note, recorded_at=date)
                report.history_entries_written += 1

            # Inline alias extraction
            for alias in _extract_inline_aliases(entity_name, section_body):
                db.insert_alias(entity_id, alias)
                report.aliases_extracted += 1

    return report


def verify(notebook_path: Path, db: NotebookDB) -> list[str]:
    """
    Spot-check the migration: compare entity count in DB vs ## headers
    in each markdown file. Returns a list of discrepancy messages.
    """
    store = MarkdownStore(notebook_path)
    issues = []

    for md_file in sorted(notebook_path.glob("*.md")):
        if md_file.name in SKIP_FILES:
            continue

        content = md_file.read_text(encoding="utf-8")
        frontmatter, body = store.parse_frontmatter(content)
        if not frontmatter:
            continue

        raw_type = frontmatter.type
        entity_type = FILE_TO_TYPE.get(raw_type, raw_type)

        md_count = len(re.findall(r"^## ", body, re.MULTILINE))

        db_rows = db._conn.execute(
            "SELECT COUNT(*) FROM entities WHERE type = ?", (entity_type,)
        ).fetchone()[0]

        # DB may have more than one file mapping to the same type (e.g. items + equipment → items)
        # so we only flag when DB has fewer than markdown
        if db_rows < md_count:
            issues.append(
                f"{md_file.name}: {md_count} sections in markdown, "
                f"only {db_rows} '{entity_type}' entities in DB"
            )

    return issues


def main() -> None:
    load_dotenv()

    import os
    notebook_path = Path(os.getenv("NOTEBOOK_PATH", "./notebook"))

    if not notebook_path.exists():
        print(f"Error: notebook path does not exist: {notebook_path}")
        sys.exit(1)

    print(f"Migrating {notebook_path} to SQLite...")

    db = NotebookDB(notebook_path)

    report = migrate(notebook_path, db)

    print(f"\nMigration complete:")
    print(f"  Entities inserted:       {report.entities_inserted}")
    print(f"  Fields written:          {report.fields_written}")
    print(f"  Relationships written:   {report.relationships_written}")
    print(f"  History entries written: {report.history_entries_written}")
    print(f"  Aliases extracted:       {report.aliases_extracted}")

    if report.warnings:
        print(f"\nWarnings ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  ! {w}")

    print("\nVerifying...")
    issues = verify(notebook_path, db)
    if issues:
        print(f"\nDiscrepancies found ({len(issues)}):")
        for issue in issues:
            print(f"  ! {issue}")
    else:
        print("  OK — entity counts match.")

    db_stats = db.get_stats()
    print(f"\nDB stats: {db_stats['entities']} entities, "
          f"{db_stats['relationships']} relationships, "
          f"{db_stats['facts']} facts")

    db.close()


if __name__ == "__main__":
    main()
