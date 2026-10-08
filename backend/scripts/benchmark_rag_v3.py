import os
import time
import math
import random
from uuid import uuid4
from datetime import datetime, UTC

from sqlalchemy import text
from ares.adapters.db import build_session_factory, Base
from ares.application.repository import Repository
from ares.domain.models import DocumentStatus
from ares.application.documents import PreparedChunk

def generate_random_vector(dim=384):
    vec = [random.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(v*v for v in vec))
    if norm == 0: norm = 1
    return [v/norm for v in vec]

def run_benchmark(engine, sessions, num_chunks, narrow_filter_size, broad_filter_size):
    print(f"\n--- Benchmarking {num_chunks} chunks ---")
    
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        
    Base.metadata.create_all(engine)
    
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE document_embeddings_pg CASCADE"))
        conn.execute(text("TRUNCATE document_chunks CASCADE"))
        conn.execute(text("TRUNCATE user_documents CASCADE"))
        
    num_docs = max(100, num_chunks // 100)
    chunks_per_doc = num_chunks // num_docs
    
    doc_ids = []
    print(f"Creating {num_docs} documents with {chunks_per_doc} chunks each...")
    
    repository = Repository(sessions)
    for i in range(num_docs):
        chunks = [
            PreparedChunk(j, "test", j*10, j*10+4, None, None, "locator")
            for j in range(chunks_per_doc)
        ]
        
        doc = repository.create_user_document(
            name=f"vector-{i}.txt",
            mime_type="text/plain",
            text="test "*chunks_per_doc,
            raw_bytes=b"test "*chunks_per_doc,
            blob_key=None,
            status=DocumentStatus.READY,
            page_count=None,
            page_map=[],
            warnings=[],
            parser_version="test",
            chunks=chunks,
        )
        doc_ids.append(doc.id)
        
        # Insert vectors
        chunk_rows = repository.get_document_chunks([doc.id])
        embeddings = []
        for chunk in chunk_rows:
            embeddings.append((chunk.id, generate_random_vector()))
            
        repository.store_chunk_embeddings(
            model_id="test",
            dimensions=384,
            embeddings=embeddings,
        )
        if (i+1) % 10 == 0:
            print(f"  Inserted {i+1} / {num_docs} documents")

    def test_search(filter_docs, desc):
        times = []
        for _ in range(5):
            query_vec = generate_random_vector()
            start = time.time()
            ranked = repository.vector_search_document_chunks(
                filter_docs,
                model_id="test",
                dimensions=384,
                query_vector=query_vec,
                limit=30,
            )
            times.append(time.time() - start)
        
        avg_time = sum(times) / len(times)
        print(f"  {desc} filter ({len(filter_docs)} docs) exact search latency: {avg_time*1000:.2f} ms")

    test_search(random.sample(doc_ids, min(len(doc_ids), narrow_filter_size)), "Narrow")
    test_search(random.sample(doc_ids, min(len(doc_ids), broad_filter_size)), "Broad")

def main():
    dsn = os.getenv("ARES_TEST_POSTGRES_URL", "postgresql://ares:ares@localhost:5432/ares")
    engine, sessions = build_session_factory(dsn)
    
    run_benchmark(engine, sessions, 5000, narrow_filter_size=2, broad_filter_size=20)
    run_benchmark(engine, sessions, 50000, narrow_filter_size=2, broad_filter_size=100)
    engine.dispose()
    
if __name__ == "__main__":
    main()
