# PDF upload and parsing fix — 17 October 2026

The report was reproduced with real generated PDFs, not only mocked parser responses.

## Root causes and changes

1. The parent joined the parser child before draining its multiprocessing queue. Results larger than the OS pipe blocked the child's feeder and produced a false parsing timeout. The parent now drains the result first, then reaps the child; timeouts terminate/kill and close worker resources.
2. Mixed digital/scanned PDFs returned parser status `mixed`, which is not a valid persisted DocumentStatus and caused HTTP 500. Both compatibility ingestion paths now publish usable pages as `partial`, preserving OCR warnings.
3. Stripping the final PDF text shifted page offsets after blank covers. The parser now preserves its exact page concatenation. Document chunk preparation restores the shared chunker's leading/trailing whitespace offsets to the original text before storing page/citation locators.
4. Upload errors were shown behind the open Library drawer. They now render inside Library, with an uploading/reading status while the request is pending.

## Verification

New regressions were observed failing before each fix: text-heavy parser timeout; blank-cover page slice mismatch; mixed-PDF upload HTTP 500; persisted chunk offset mismatch. A worker timeout test also verifies no child is left running.

- Full backend suite: **275 passed, 8 skipped** (optional PostgreSQL/tool-dependent cases; not configured for this run).
- Frontend: **28 passed**, typecheck and production build passed. Ruff and whitespace checks passed. Existing optional chart chunk size warning remains.
- Actual browser + button upload of the formerly failing 20-page, ~175 KB PDF succeeded, appeared once in Library and was selected as a document source. Its 174,188-character parser result completed in ~0.49 seconds in the standalone reproduction, compared with the former 8-second forced timeout.
- Live database verification: **167 stored chunks, 5 lexical retrieval hits**, every chunk matched its exact stored text offsets.
- Mixed 2-page PDF: HTTP 201, `partial`, lexical-ready, preserved OCR warning, 1 stored chunk and retrieval hit with correct page/character offsets.
- Invalid PDF: HTTP 422, visible `file signature is not a PDF` message in Library. No invalid document row is published.

Evidence: `/tmp/ares-pdf-debug/live-result.json`, `/tmp/ares-pdf-debug/upload-passed.png`. These are synthetic test PDFs; this check does not certify every possible PDF or provision OCR for image-only documents. Scanned-only PDFs still require an available OCR capability and must not be represented as searchable digital text.

The API was restarted with the corrected code and its existing local SQLite database. No user-uploaded document was deleted; only hash-matched synthetic test uploads were removed after verification. The local API and frontend remain available for re-uploading the previously failed PDF.
