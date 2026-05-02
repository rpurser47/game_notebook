"""Vector index for semantic search using ChromaDB."""

import hashlib
from pathlib import Path

import chromadb
from chromadb.config import Settings

from .markdown import EntityChunk, MarkdownStore


class NotebookIndex:
    """Vector index for the notebook using ChromaDB."""

    def __init__(
        self,
        notebook_path: str | Path,
        embedding_provider: str = "local",
    ):
        self.notebook_path = Path(notebook_path)
        self.index_path = self.notebook_path / ".index"
        self.index_path.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB
        self.client = chromadb.PersistentClient(
            path=str(self.index_path / "chromadb"),
            settings=Settings(anonymized_telemetry=False),
        )

        # Set up embedding function
        self.embedding_fn = self._get_embedding_function(embedding_provider)

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="notebook",
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

        # Track content hashes for incremental updates
        self.chunk_hashes: dict[str, str] = {}
        self._load_hashes()

    def _get_embedding_function(self, provider: str):
        """Get the appropriate embedding function."""
        if provider == "openai":
            from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
            import os

            return OpenAIEmbeddingFunction(
                api_key=os.getenv("OPENAI_API_KEY"),
                model_name="text-embedding-3-small",
            )
        else:
            # Use local sentence-transformers
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

            return SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

    def _load_hashes(self) -> None:
        """Load chunk hashes from disk."""
        import json

        hash_file = self.index_path / "hashes.json"
        if hash_file.exists():
            self.chunk_hashes = json.loads(hash_file.read_text())

    def _save_hashes(self) -> None:
        """Save chunk hashes to disk."""
        import json

        hash_file = self.index_path / "hashes.json"
        hash_file.write_text(json.dumps(self.chunk_hashes))

    def _compute_hash(self, content: str) -> str:
        """Compute hash of content."""
        return hashlib.md5(content.encode()).hexdigest()

    def _chunk_to_metadata(self, chunk: EntityChunk) -> dict:
        """Convert chunk to ChromaDB metadata."""
        metadata = {
            "file": chunk.file,
            "entity_name": chunk.entity_name,
            "entity_type": chunk.entity_type,
        }

        if chunk.status:
            metadata["status"] = chunk.status
        if chunk.location:
            metadata["location"] = chunk.location
        if chunk.related:
            metadata["related"] = ",".join(chunk.related)

        # Add any extra metadata
        for key, value in chunk.metadata.items():
            if key not in ("status", "location", "related") and isinstance(value, (str, int, float, bool)):
                metadata[key] = value

        return metadata

    def upsert_chunk(self, chunk: EntityChunk) -> bool:
        """Add or update a chunk in the index. Returns True if changed."""
        chunk_id = chunk.chunk_id
        content_hash = self._compute_hash(chunk.content)

        # Check if content changed
        if self.chunk_hashes.get(chunk_id) == content_hash:
            return False

        # Upsert into ChromaDB
        self.collection.upsert(
            ids=[chunk_id],
            documents=[chunk.content],
            metadatas=[self._chunk_to_metadata(chunk)],
        )

        self.chunk_hashes[chunk_id] = content_hash
        self._save_hashes()
        return True

    def delete_chunk(self, chunk_id: str) -> None:
        """Remove a chunk from the index."""
        try:
            self.collection.delete(ids=[chunk_id])
        except Exception:
            pass  # Chunk might not exist

        if chunk_id in self.chunk_hashes:
            del self.chunk_hashes[chunk_id]
            self._save_hashes()

    def index_file(self, store: MarkdownStore, filename: str) -> int:
        """Index or re-index a single file. Returns number of chunks updated."""
        chunks = store.parse_into_chunks(filename)
        updated = 0

        for chunk in chunks:
            if self.upsert_chunk(chunk):
                updated += 1

        return updated

    def index_all(self, store: MarkdownStore) -> int:
        """Index all markdown files. Returns total chunks updated."""
        total = 0

        # Track which chunk IDs are still valid
        valid_chunk_ids = set()

        for file_path in store.list_files():
            chunks = store.parse_into_chunks(file_path.name)
            for chunk in chunks:
                valid_chunk_ids.add(chunk.chunk_id)
                if self.upsert_chunk(chunk):
                    total += 1

        # Remove orphaned chunks (from renamed/deleted files or entities)
        orphaned = set(self.chunk_hashes.keys()) - valid_chunk_ids
        for chunk_id in orphaned:
            self.delete_chunk(chunk_id)
            total += 1  # Count removals as updates

        return total

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Semantic search with optional metadata filters."""
        where_clause = None

        if filters:
            # Build ChromaDB where clause
            conditions = []
            for key, value in filters.items():
                if value is not None:
                    conditions.append({key: {"$eq": value}})

            if len(conditions) == 1:
                where_clause = conditions[0]
            elif len(conditions) > 1:
                where_clause = {"$and": conditions}

        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_clause,
            include=["documents", "metadatas", "distances"],
        )

        # Format results
        formatted = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                formatted.append({
                    "chunk_id": chunk_id,
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                })

        return formatted

    def search_by_entity_type(
        self,
        entity_type: str,
        status: str | None = None,
        top_k: int = 50,
    ) -> list[dict]:
        """Get all entities of a type, optionally filtered by status."""
        filters = {"entity_type": entity_type}
        if status:
            filters["status"] = status

        # Use a broad query since we're filtering by metadata
        results = self.collection.get(
            where=filters if len(filters) > 0 else None,
            include=["documents", "metadatas"],
            limit=top_k,
        )

        formatted = []
        if results["ids"]:
            for i, chunk_id in enumerate(results["ids"]):
                formatted.append({
                    "chunk_id": chunk_id,
                    "content": results["documents"][i] if results["documents"] else "",
                    "metadata": results["metadatas"][i] if results["metadatas"] else {},
                })

        return formatted

    def hybrid_search(
        self,
        semantic_query: str | None = None,
        filters: dict | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """Combine semantic search with structured filters."""
        if semantic_query:
            return self.search(semantic_query, top_k=top_k, filters=filters)
        elif filters:
            # Metadata-only search
            where_clause = None
            conditions = []
            for key, value in filters.items():
                if value is not None:
                    conditions.append({key: {"$eq": value}})

            if len(conditions) == 1:
                where_clause = conditions[0]
            elif len(conditions) > 1:
                where_clause = {"$and": conditions}

            results = self.collection.get(
                where=where_clause,
                include=["documents", "metadatas"],
                limit=top_k,
            )

            formatted = []
            if results["ids"]:
                for i, chunk_id in enumerate(results["ids"]):
                    formatted.append({
                        "chunk_id": chunk_id,
                        "content": results["documents"][i] if results["documents"] else "",
                        "metadata": results["metadatas"][i] if results["metadatas"] else {},
                    })
            return formatted
        else:
            return []

    def get_stats(self) -> dict:
        """Get index statistics."""
        return {
            "total_chunks": self.collection.count(),
            "tracked_hashes": len(self.chunk_hashes),
        }
