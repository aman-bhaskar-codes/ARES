# V2 model and dependency license inventory

This is the release operator's review list, not legal advice. Software-package licenses and model-weight licenses are separate. Exact downloaded model revisions/hashes must be recorded by the operator before redistribution.

| Capability | Default/candidate | Software license boundary | Model/data boundary |
|---|---|---|---|
| LLM + optional vision | Gemini adapter | hosted proprietary service; SDK license separately pinned in `uv.lock` | provider terms/quota/data-handling apply; no weights redistributed |
| PDF/layout parsing | Docling optional media profile | MIT project; transitive dependencies reviewed per lock/container | parser/model artifacts require exact revision/hash review |
| OCR | RapidOCR/Docling profile | Apache-2.0 components where selected | exact OCR model files/languages recorded during provisioning |
| ASR | faster-whisper | MIT project | Whisper model revision/hash/license recorded separately |
| video preparation | FFmpeg/ffprobe | build-dependent LGPL/GPL obligations; inspect redistributed build | no model by default |
| local embeddings | FastEmbed/ONNX profile | FastEmbed Apache-2.0 | selected embedding model card/license/revision recorded separately |
| PDF viewer | PDF.js | Apache-2.0 | none |
| numeric charts | Apache ECharts 6.1.0 | Apache-2.0 | none |
| evidence graph | `@xyflow/react` 12.12.0 | MIT core | none |
| dynamic-page fallback | Playwright 1.63.0 | Apache-2.0 | bundled browser redistribution terms apply |

## M11 frontend additions

- `echarts@6.1.0`
- `@xyflow/react@12.12.0`
- `react-markdown@10.1.0`
- `remark-gfm@4.0.1`

They are lockfile-controlled dependencies. The release SBOM is generated from `backend/uv.lock` and `pnpm-lock.yaml` with `python scripts/generate_sbom.py`.

## Release evidence to retain

For every optional local model/profile, record model identifier, immutable revision/hash, source URL, license identifier/text, date reviewed, expected memory/disk requirement, supported languages/scripts, and any redistribution limitation. Do not infer a model's license from the Python package that downloads it.
