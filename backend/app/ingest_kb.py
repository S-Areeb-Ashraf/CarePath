"""Ingest the Supabase knowledge base into the local Chroma vector store.

Usage:
    python -m app.ingest_kb

Reads every approved kb_documents/kb_chunks row (including the Saudi
CHI/MOH seed content) and upserts it into Chroma with embeddings. Idempotent:
re-running refreshes existing chunk IDs. Nothing is hardcoded — document
content stays in Supabase, Chroma is only the index.
"""
from uuid import uuid5, NAMESPACE_URL

from .config import get_settings
from .supabase_repository import SupabaseRepository
from .rag import KnowledgeBase, EmbeddingError


def chunk_id(source: str, body: str) -> str:
    return str(uuid5(NAMESPACE_URL, f'{source}::{body}'))


def load_documents(repo: SupabaseRepository) -> list[dict]:
    documents = repo.client.table('kb_documents').select('id,source,title,version').eq('requires_validation', False).execute().data or []
    by_id = {row['id']: row for row in documents}
    chunks = repo.client.table('kb_chunks').select('document_id,body').execute().data or []
    items = []
    for row in chunks:
        document = by_id.get(row.get('document_id'))
        body = (row.get('body') or '').strip()
        if not document or not body:
            continue
        items.append({
            'id': chunk_id(document['source'], body),
            'text': body,
            'source': document['source'],
            'title': document['title'],
            'version': document['version'],
        })
    return items


def main() -> None:
    settings = get_settings()
    repo = SupabaseRepository(settings)
    kb = KnowledgeBase(settings)
    items = load_documents(repo)
    print(f'Loaded {len(items)} chunks from Supabase kb_documents/kb_chunks.')
    if not items:
        print('Nothing to ingest. Apply supabase/schema.sql and seed scripts first.')
        return
    try:
        written = kb.ingest(items)
    except EmbeddingError as exc:
        raise SystemExit(f'Ingestion failed: {exc}')
    print(f'Upserted {written} chunks into Chroma collection {settings.chroma_collection_name!r} at {settings.chroma_persist_dir!r}.')


if __name__ == '__main__':
    main()
