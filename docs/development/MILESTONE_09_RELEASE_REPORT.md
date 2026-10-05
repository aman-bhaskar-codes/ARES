# Milestone 09 Release Report — Audio and short-video evidence

**Candidate:** ARES `0.9.0` / schema `0010`  
**Baseline:** supplied M08 release-candidate archive; M09 is an additive continuation, not a rewrite.  
**Date:** 4 October 2026

## Implemented scope

M09 extends the M08 `AssetVersion -> ExtractionVersion -> EvidenceSegment -> compatibility document/chunk` lineage to time-based media. Audio and video reuse the existing durable ingestion queue, lease/fencing rules, workspace authorization, blob storage and research retrieval path. No second media database, second tenant model or media-only research engine was introduced.

Audio admission supports configured WAV, MP3, M4A/MP4-audio, Ogg and WebM-audio. Local transcription is implemented behind `ports/transcription.py` with a `faster-whisper` adapter that executes in a constrained child process. Model files are required to be provisioned before jobs are accepted; request-time model download is disabled. The transcript preserves source language metadata, segment start/end milliseconds, model revision and no-speech warnings. Translation is not substituted for the source transcript.

Video admission supports uploaded MP4 and WebM only. FFmpeg/ffprobe operate on staged local files with argument arrays, no shell interpolation, a file/pipe protocol allowlist, bounded subprocess resources and cancellation polling. Video reuses the audio transcription path when ASR is ready. A bounded periodic plus scene-change sampler stores exact decoded presentation timestamps, deduplicates selected frames and records an explicit warning that sparse sampling is not exhaustive. Optional OCR over a bounded selected-frame subset becomes `frame_region` evidence; transcript evidence uses `time_range` locators.

The compatibility document path is retained intentionally: transcript/frame text is published as ordinary research chunks whose `evidence_segment_id` points back to the time/frame locator. Existing lexical/hybrid retrieval, claims and answer evidence therefore continue to work without a new media-only query subsystem. Transcript, frame OCR and optional model observations originating from the same recording share origin lineage rather than being counted as independent sources.

Migration `0010_media_metadata` adds asset cloud-media consent/metadata, worker capability heartbeats, `media_tracks` and `media_frames`. New tenant-bearing media tables include workspace ownership, PostgreSQL RLS policy/grants and immutable rendition references. Asset/document deletion collects original and derived media blob keys so sampled frames do not remain orphaned merely because SQLite demo mode lacks PostgreSQL cascade behavior.

## API and UI integration

`/api/v1/system/status` distinguishes configured from ready audio/video capability. Production admission requires a live worker advertising the required capability; demo admission probes local FFmpeg/ffprobe, the optional faster-whisper runtime and provisioned model files. Configuring a flag alone therefore does not create a permanently failing media queue.

`/api/v2/assets/{id}/storyboard` exposes bounded track/frame metadata, sampled timestamps, waveform peaks and coverage warnings through the same authorization boundary as the original asset. Sampled frame bytes use authenticated rendition endpoints. The existing evidence drawer adds time-range playback/seek and sampled-frame inspection rather than introducing a separate media application. The workspace accepts media types only when the server reports them ready and adds optional push-to-record microphone input. Microphone capture is disabled by default and requires server readiness plus browser secure-context permission behavior.

A typed optional Gemini visual-observation adapter accepts only application-selected image regions with server-generated region IDs. It does not fetch URLs, generate locators or silently upload raw recordings. Cloud-media consent is an explicit asset-level flag and is separate from local ingestion.

## Security and resource boundaries

- media parsers receive staged local files, not arbitrary URLs;
- FFmpeg/ffprobe use explicit protocol restrictions and no shell interpolation;
- ASR runs in a subprocess with a scrubbed environment rather than inheriting database/provider credentials;
- heavy media processing stays in the media/combined worker profile, not FastAPI request handlers;
- audio/video byte, decoded-duration, source-pixel, frame-count, process-time, CPU and memory bounds are configurable;
- cancellation/stale leases fence publication and terminate local child work at polling boundaries;
- asset upload has a dedicated raw-body ceiling, while normal API mutations retain the smaller request limit;
- byte-range serving and all storyboard/rendition lookups remain workspace-authorized;
- media deletion removes derivative metadata/blob references before asset cleanup;
- cloud media is disabled by default and does not change the no-egress media-worker posture.

## Validation executed in this sandbox

The following gates were freshly executed against this working tree:

- full backend suite: **142 passed / 6 skipped**; all six skips require `ARES_TEST_POSTGRES_URL`;
- focused M09 suite: **22 passed** across media processing, admission readiness, body-size enforcement, multimodal region validation and worker lease behavior;
- real local FFmpeg/ffprobe integration fixtures exercised timestamped WAV processing, generated MP4 audio/video, bounded decoded presentation-time frame sampling, storyboard publication, range-authorized media access and derived-blob deletion;
- migration compatibility: **PASS** for empty -> `0010`, direct M08 `0009` -> `0010`, representative `0007` -> `0010`, and representative `0006` -> `0010`;
- `python -m compileall` across backend/tests/scripts: **PASS**;
- deterministic secret-shaped-material scan: **PASS** across 241 candidate source paths;
- `uv lock --project backend --check`: **PASS**;
- OpenAPI regenerated as ARES `0.9.0` and frontend generated API contracts refreshed;
- `git diff --check`: **PASS**.

The environment contains FFmpeg/ffprobe, so decoder/frame integration was executed. It does **not** contain `faster-whisper`, its CTranslate2/PyAV transitive environment or a provisioned Whisper model; therefore this report does not claim a real ASR quality/speed run. The code exercises ASR integration with a deterministic transcriber fixture, while real WER/RTF/memory evaluation remains a release gate.

The frontend source and API contract were reviewed, but a fresh `pnpm install --frozen-lockfile`, project TypeScript typecheck, Vitest and Vite production build cannot be completed in this sandbox because the pinned npm dependency tree is absent and registry access is unavailable. Running global `tsc` without the project dependency tree only reports missing React/TanStack/Lucide/Vite/Vitest modules and is not counted as a valid frontend typecheck.

## Evaluation tooling

`scripts/eval_media.py` provides a licensed-manifest evaluation path for WER, real-time factor, timestamp mean absolute error, sampled-frame timestamps and child-process peak RSS. `scripts/provision_whisper_model.py` requires an explicit revision and operator license-review acknowledgement so model provisioning is a deployment step, not a first-upload network side effect.

The V2 plan requires at least 20 diverse licensed audio clips and 10 videos including silence, noise, code-switching, corrupt input, no-audio video, variable FPS and an event between sampled frames. Those external-quality fixtures are not fabricated in this source archive. WER by language/noise condition, real-time factor, peak RSS, timestamp error and sampled-frame coverage must be published from the operator's target hardware before production promotion.

## Promotion gates still external

Do not label M09 production-complete until the target environment executes:

1. PostgreSQL/pgvector/FORCE-RLS tests with intended API and worker roles against schema `0010`, including the new media tables;
2. fresh `pnpm install --frozen-lockfile`, TypeScript project typecheck, Vitest and Vite production build;
3. production core/media image builds and Compose runtime checks with FFmpeg present in the media image;
4. provisioned pinned Whisper model + faster-whisper runtime and the licensed media evaluation manifest;
5. M08's still-open Docling/RapidOCR/FastEmbed/OCR/table-quality gates;
6. live OIDC/provider smoke tests and controlled optional Gemini visual-observation tests where operator policy allows cloud media.

## Rollback

Disable `AUDIO_ENABLED`, `VIDEO_ENABLED`, `MICROPHONE_ENABLED` and `CLOUD_MEDIA_ENABLED` independently. Keep schema `0010` and already completed media provenance; text/document research continues to function when the media worker is stopped. Existing authorized recordings can remain playable/readable while new media admission is disabled. Do not destructively downgrade shared data merely to turn off optional media capabilities.

## M10 entry condition

M10 should build faster/stronger live research on the existing M07–M09 contracts. Do not introduce concurrency/caching/browser changes by bypassing media origin grouping, time/frame locators, shared run budgets, workspace authorization or the established Safe HTTP/worker boundaries. Production promotion of M09 remains evidence-gated by the external checks above even if M10 source development proceeds on this candidate.
