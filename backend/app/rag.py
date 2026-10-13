"""ChromaDB-backed RAG. Documents live in Supabase (kb_documents/kb_chunks);
Chroma is the local vector index. Embeddings come from any OpenAI-compatible
embeddings endpoint configured via EMBEDDING_* settings — nothing hardcoded."""
from typing import Any
import httpx
from .config import Settings


class EmbeddingError(RuntimeError):
    pass


class EmbeddingClient:
    """OpenAI-compatible /embeddings caller (Gemini, OpenAI, Ollama, etc.)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def _config(self) -> tuple[str, str, str]:
        base_url = (self.settings.embedding_base_url or self.settings.llm_base_url).rstrip('/')
        model = self.settings.embedding_model
        api_key = self.settings.embedding_api_key or self.settings.llm_api_key
        if not base_url or not model or not api_key:
            raise EmbeddingError('Embedding endpoint is not configured. Set EMBEDDING_BASE_URL, EMBEDDING_MODEL, and an API key.')
        return base_url, model, api_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        base_url, model, api_key = self._config()
        try:
            response = httpx.post(
                f'{base_url}/embeddings',
                headers={'Authorization': f'Bearer {api_key}'},
                json={'model': model, 'input': texts},
                timeout=self.settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()['data']
            ordered = sorted(data, key=lambda item: item.get('index', 0))
            return [item['embedding'] for item in ordered]
        except httpx.HTTPStatusError as exc:
            raise EmbeddingError(f'Embedding provider returned HTTP {exc.response.status_code}.') from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise EmbeddingError(f'Embedding request failed: {exc}') from exc


class KnowledgeBase:
    """Persistent Chroma collection over Supabase-sourced documents."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any = None
        self._collection: Any = None
        self.embeddings = EmbeddingClient(settings)

    def _collection_or_none(self) -> Any:
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ImportError as exc:
            raise EmbeddingError('chromadb is not installed. Run: pip install chromadb') from exc
        if self._client is None:
            self._client = chromadb.PersistentClient(path=self.settings.chroma_persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=self.settings.chroma_collection_name,
            metadata={'hnsw:space': 'cosine'},
        )
        return self._collection

    def healthy(self) -> bool:
        try:
            self._collection_or_none()
            self.embeddings._config()
            return True
        except Exception:
            return False

    def ingest(self, documents: list[dict[str, Any]]) -> int:
        """Upsert chunks. Each item: {id, text, source, title, version, url}."""
        if not documents:
            return 0
        collection = self._collection_or_none()
        batch = 32
        count = 0
        for start in range(0, len(documents), batch):
            chunk = documents[start:start + batch]
            vectors = self.embeddings.embed([item['text'] for item in chunk])
            collection.upsert(
                ids=[item['id'] for item in chunk],
                documents=[item['text'] for item in chunk],
                metadatas=[{
                    'source': item.get('source', ''),
                    'title': item.get('title', ''),
                    'version': item.get('version', ''),
                    'url': item.get('url', ''),
                } for item in chunk],
                embeddings=vectors,
            )
            count += len(chunk)
        return count

    def search(self, query: str, top_k: int | None = None, min_score: float | None = None) -> list[dict[str, Any]]:
        settings = self.settings
        limit = top_k or settings.rag_top_k
        floor = settings.rag_min_relevance if min_score is None else min_score
        collection = self._collection_or_none()
        vector = self.embeddings.embed([query])[0]
        response = collection.query(query_embeddings=[vector], n_results=limit, include=['documents', 'metadatas', 'distances'])
        hits: list[dict[str, Any]] = []
        documents = (response.get('documents') or [[]])[0]
        metadatas = (response.get('metadatas') or [[]])[0]
        distances = (response.get('distances') or [[]])[0]
        for text, metadata, distance in zip(documents, metadatas, distances):
            score = 1.0 - float(distance)
            if score < floor:
                continue
            hits.append({
                'source': metadata.get('source', ''),
                'title': metadata.get('title', ''),
                'version': metadata.get('version', ''),
                'url': metadata.get('url', ''),
                'text': text,
                'score': round(score, 4),
            })
        return hits
