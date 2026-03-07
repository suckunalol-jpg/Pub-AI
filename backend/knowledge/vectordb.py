from __future__ import annotations

from typing import Dict, List, Optional

try:
    import chromadb
except Exception:
    chromadb = None


class VectorStore:
    """ChromaDB integration for semantic search over knowledge entries."""

    def __init__(self):
        self._client: Optional[chromadb.ClientAPI] = None
        self._collection = None

    def _ensure_init(self):
        if self._client is None:
            if chromadb is None:
                raise RuntimeError("chromadb is not installed or not supported on this Python version")
            self._client = chromadb.EphemeralClient()  # In-memory for dev; use PersistentClient for prod
            self._collection = self._client.get_or_create_collection(
                name="pub_knowledge",
                metadata={"hnsw:space": "cosine"},
            )

    def add(
        self,
        doc_id: str,
        text: str,
        metadata: Dict = {},
    ):
        self._ensure_init()
        self._collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata],
        )

    def query(
        self,
        query: str,
        top_k: int = 5,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        self._ensure_init()
        count = self._collection.count()
        if count == 0:
            return []
        where = {"user_id": user_id} if user_id else None
        n_results = min(top_k, count)
        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
        )

        entries = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                entry = {
                    "id": results["ids"][0][i] if results["ids"] else None,
                    "content": doc,
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                }
                entries.append(entry)
        return entries

    def delete(self, doc_id: str):
        self._ensure_init()
        self._collection.delete(ids=[doc_id])


vector_store = VectorStore()
