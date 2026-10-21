# ARES Expansion Roadmap

Oct 17, 2026 · @Aman

## Where ARES stands today

ARES has the plumbing for OCR and multimodal work, but it is switched off by default, retrieval is text-only, and there is no long-term memory. Fix the three must-fix items from the review first (auth in production, the schema revision check, the SearXNG secret); everything below builds on that.

| Area | What exists | Gap |
| --- | --- | --- |
| OCR | Docling with RapidOCR in a sandboxed subprocess | `RICH_PARSER_ENABLED` and `OCR_ENABLED` default to false; model cache must be provisioned by hand; not run end to end in this review |
| Multimodal | Gemini describes selected image regions; faster-whisper for audio; ffmpeg frames for video | Retrieval is text-only; no local vision model; no image embeddings |
| Retrieval | pgvector exact cosine search, Postgres full-text search, bge-small embeddings (384 dimensions), MiniLM cross-encoder reranker | No HNSW index found; fixed-size paragraph chunking |
| Memory | Conversations and runs | No long-term memory layer found; follow-ups reuse nothing durable |

## 1. Memory system

This is the biggest upgrade. Build it on Postgres, since ARES already has pgvector, full-text search and row-level security. Use four tiers:

- **Working memory:** the current run's plan and evidence. This already exists.
- **Episodic memory:** summaries of past runs and conversations, embedded and searchable.
- **Semantic memory:** extracted facts and entities, each with source evidence, a confidence score and a "superseded by" link, so contradictions get resolved instead of piling up.
- **Preference memory:** per-user settings such as depth, source preferences and domains.

Key design rules:

- Only store claims that passed the citation-integrity check. Web content is untrusted, so otherwise a poisoned page becomes a permanent memory.
- Retrieval combines vector search, full-text search, recency decay and importance, then reranks.
- A background job consolidates memory: it dedupes, summarizes and flags contradictions.
- Users can see, edit, delete and export their memory. Scope it per workspace using the existing row-level security.

Mem0, Zep/Graphiti and Letta are worth reading for ideas. Start without them, and add a graph layer only if relationship queries justify it.

## 2. Retrieval upgrades

Memory depends on good retrieval, so do this before the memory tiers. Measure recall@k and nDCG before and after each change.

- Add an HNSW index, using `halfvec` to save space.
- Use a multilingual embedding model such as bge-m3 or Qwen3-embedding. The existing `embedding_profiles` table already supports swapping models.
- Replace the fixed-size chunker with layout-aware chunking from Docling's structure, and add contextual or parent-child chunks.
- Add multi-query rewriting, RRF fusion and a stronger reranker such as bge-reranker-v2-m3.
- Add an NLI check that each cited sentence is actually supported by its evidence.

## 3. OCR that actually works

The goal is OCR that runs after one command, handles hard pages, and lets a citation point at the exact spot in the source.

- Ship `make provision-ocr` plus a compose profile, so setup is one command instead of a manual model download.
- Decide per page whether it is scanned or digital, and only OCR the scanned ones.
- Add preprocessing (deskew, denoise) and Hindi and German language packs.
- Send low-confidence pages to a vision-language model fallback. Local options like Qwen2.5-VL or PaddleOCR-VL are worth testing; check current versions before committing.
- Store bounding boxes and confidence for each region, so a citation can highlight the exact spot in the PDF. `pdfjs` is already in the frontend.
- Extract tables into structured data (Docling's table model) and feed them to the existing table operations.
- Build a small OCR test set and track character error rate.

## 4. Multimodal evidence and retrieval

Start cheap by embedding captions plus OCR text into the existing text index, then add image-aware retrieval as a second embedding profile.

- Extend `EvidencePacket` with a modality (text, image region, table, audio segment, video frame) and a locator (bounding box or timestamp).
- Add image-aware retrieval as a second embedding profile, using SigLIP or CLIP, or ColPali/ColQwen for page-image search.
- Add a local vision model through Ollama (Qwen2.5-VL, Gemma 3, Llama 3.2 Vision), so the zero-cost mode keeps working.
- Add chart-to-data extraction feeding the visualization workspace, and align video frames with the transcript timeline.
- Keep the current rule that image content is untrusted, since prompt injection through images is real.

## 5. Full-stack and tooling

- **Backend:** move blobs to S3/MinIO, add LLM tracing (Langfuse or Phoenix next to the existing OpenTelemetry), and add a provider registry for models.
- **Agent loop:** an optional LangGraph rewrite with a Postgres checkpointer, human-in-the-loop interrupts and a plan/act/reflect cycle. The custom state machine works, so this is only worth it if you want to learn and show LangGraph.
- **MCP:** ARES already consumes MCP tools, so also expose ARES itself as an MCP server.
- **Frontend:** collections and workspaces, a memory manager, a side-by-side source viewer with highlights, and an eval dashboard.
- **DevEx:** one-command `make dev`, a devcontainer, pre-commit hooks, Playwright end-to-end tests and load tests.

## Suggested order and benchmark

Build retrieval before memory, and memory before the multimodal work, because each layer depends on the one before it.

1. Fix the three must-fix items, then the router refactor.
2. Retrieval upgrades (HNSW, chunking, reranking).
3. Memory tiers 1–3 with the write and retrieval policies.
4. OCR provisioning, then the multimodal evidence model.
5. Local vision model, image retrieval and the UI work.

Build an ARES benchmark alongside all of this, covering memory recall, OCR error rate, multimodal question answering and citation faithfulness. Given the evaluation research direction, that benchmark is probably the most publishable piece.
