import json
import os
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import ollama
from qdrant_client import QdrantClient, models

try:
    import fcntl
except ImportError:  # pragma: no cover - the deployed macOS/Linux services have fcntl
    fcntl = None

from .analytics import record_ollama_call
from .extractors import extract_file, iter_course_files
from .schemas import RetrievedChunk

COLLECTION_NAME = "course_materials"
MANIFEST_FILE = "manifest.json"


def chunk_text(text: str, size: int = 350, overlap: int = 50) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(end - overlap, start + 1)
    return chunks


class CourseIndex:
    def __init__(self, db_path: Path, embed_model: str):
        self.db_path = db_path
        self.embed_model = embed_model
        self.db_path.mkdir(parents=True, exist_ok=True)
        # Qdrant's embedded/local client takes an exclusive filesystem lock.
        # The faculty portal and student service are separate processes, so
        # serialize their short-lived clients with our own course-local lock.
        self._lock_file = (self.db_path.parent / ".qdrant-client.lock").open("a+")
        if fcntl is not None:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX)
        try:
            self.client = QdrantClient(path=str(self.db_path))
        except Exception:
            if fcntl is not None:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
            raise
        ollama_host = os.environ.get("OLLAMA_HOST")
        self.ollama = (
            ollama.Client(host=ollama_host) if ollama_host else ollama.Client()
        )

    @property
    def manifest_path(self) -> Path:
        return self.db_path.parent / MANIFEST_FILE

    def close(self) -> None:
        self.client.close()
        if fcntl is not None:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
        self._lock_file.close()

    def exists(self) -> bool:
        return self.client.collection_exists(COLLECTION_NAME)

    def status(self) -> dict:
        if not self.manifest_path.is_file():
            return {"document_count": 0, "chunk_count": 0, "indexed_at": None}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def _embed(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), 32):
            response = self.ollama.embed(
                model=self.embed_model,
                input=texts[start : start + 32],
            )
            record_ollama_call(
                response,
                operation="embedding",
                model=self.embed_model,
                item_count=len(texts[start : start + 32]),
            )
            embeddings.extend(response["embeddings"])
        return embeddings

    def rebuild(self, course_dir: Path, course_id: str) -> dict:
        records: list[dict] = []
        documents: list[dict] = []

        for path in iter_course_files(course_dir):
            relative_path = str(path.relative_to(course_dir))
            digest = sha256(path.read_bytes()).hexdigest()
            source_type = path.relative_to(course_dir).parts[0]
            sections = extract_file(path)
            document_chunks = 0
            for section in sections:
                for part_number, text in enumerate(chunk_text(section.text), start=1):
                    chunk_id = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"{course_id}:{relative_path}:{section.locator}:{part_number}:{digest}",
                        )
                    )
                    records.append(
                        {
                            "id": chunk_id,
                            "text": text,
                            "source": relative_path,
                            "source_type": source_type,
                            "locator": section.locator,
                            "course_id": course_id,
                            "sha256": digest,
                        }
                    )
                    document_chunks += 1
            documents.append(
                {
                    "source": relative_path,
                    "sha256": digest,
                    "chunks": document_chunks,
                }
            )

        if not records:
            raise ValueError(
                f"No extractable course content found in {course_dir}. "
                "Add PDF, PPTX, DOCX, TXT, or Markdown files before indexing."
            )

        vectors = self._embed([record["text"] for record in records])
        vector_size = len(vectors[0])

        if self.exists():
            self.client.delete_collection(COLLECTION_NAME)
        self.client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

        for start in range(0, len(records), 100):
            points = []
            for record, vector in zip(
                records[start : start + 100], vectors[start : start + 100]
            ):
                payload = {key: value for key, value in record.items() if key != "id"}
                points.append(
                    models.PointStruct(id=record["id"], vector=vector, payload=payload)
                )
            self.client.upsert(COLLECTION_NAME, points=points, wait=True)

        manifest = {
            "course_id": course_id,
            "embedding_model": self.embed_model,
            "document_count": len(documents),
            "chunk_count": len(records),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "documents": documents,
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def search(self, query: str, limit: int) -> list[RetrievedChunk]:
        if not self.exists():
            raise RuntimeError("Course index does not exist. Publish the course first.")
        vector = self._embed([query])[0]
        response = self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        results = []
        for point in response.points:
            payload = point.payload or {}
            results.append(
                RetrievedChunk(
                    chunk_id=str(point.id),
                    text=str(payload.get("text", "")),
                    source=str(payload.get("source", "")),
                    source_type=str(payload.get("source_type", "other")),
                    locator=str(payload.get("locator", "")),
                    score=float(point.score),
                )
            )
        return results
