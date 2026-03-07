from __future__ import annotations

import uuid
from typing import List

from knowledge.vectordb import vector_store

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


async def ingest_document(
    title: str,
    content: str,
    source_type: str,
    user_id: str,
) -> str:
    """Ingest a document into the vector store. Returns the embedding_id."""
    chunks = chunk_text(content)
    base_id = str(uuid.uuid4())[:12]

    for i, chunk in enumerate(chunks):
        doc_id = f"{base_id}_{i}"
        vector_store.add(
            doc_id=doc_id,
            text=chunk,
            metadata={
                "title": title,
                "source_type": source_type,
                "user_id": user_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
            },
        )

    return base_id
