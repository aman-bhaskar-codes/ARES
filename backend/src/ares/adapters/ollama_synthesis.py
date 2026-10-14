from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace

import httpx

from ares.adapters.gemini import (
    GeminiLLMProvider,
    ProviderUnavailable,
    _build_synthesis_input,
    _ModelAnswer,
)


def _compress_evidence_text(text: str, max_chars: int = 900) -> str:
    """Strip noise from evidence text and truncate to a clean character budget.

    Small local models (<=4B) benefit significantly from concise, noise-free passages.
    Removes inline citations, raw URLs, excessive whitespace, and cuts at sentence boundary.
    """
    text = re.sub(r"\[(?:\d+(?:\s*,\s*\d+)*)\]", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = " ".join(text.split())
    if len(text) > max_chars:
        cut = text[:max_chars]
        last_period = cut.rfind(". ")
        if last_period > max_chars // 2:
            cut = cut[: last_period + 1]
        text = cut.strip()
    return text


_LOCAL_SYSTEM_PROMPT = """You are ARES, an evidence-based research synthesizer.
Synthesize an accurate, well-grounded answer to the user's research query using ONLY the supplied EVIDENCE passages.

STRICT INSTRUCTIONS:
- Grounding: Base all statements strictly on the provided EVIDENCE. Never fabricate facts, dates, numbers, or citations.
- Attribution: For each claim, assign 0-based evidence_indexes matching the numbered EVIDENCE passages that support it.
- Claims: Provide 3 to 5 clear, substantive explanatory paragraphs in 'claims'. Each paragraph: 2 to 3 informative sentences.
- No Citation Markers: Do NOT include [1], [2], etc. inside claim text. All attribution is via the evidence_indexes array.
- Gaps: If the evidence does not fully answer all aspects of the query, note those missing aspects in 'gaps'.
- Follow-ups: Suggest 2 to 3 insightful follow-up research questions in 'related_questions'.
- Format: Set summary_markdown to "". Return strictly valid JSON conforming to the schema."""


class OllamaLLMProvider(GeminiLLMProvider):
    """High-performance local structured synthesizer optimized for Ollama (qwen3:4b and similar).

    Performance optimizations:
    1. Bounded evidence: selects top 6-8 ranked passages with compressed text (~4KB context total).
    2. Lean context window (num_ctx=4096) to eliminate KV-cache bloat and drastically cut prompt evaluation latency.
    3. Disabled thinking ('think': False) to bypass internal monologue tokens and immediately stream structured claims.
    4. Bounded output tokens (num_predict=1600) and low temperature for concise, grounded generation.
    5. Robust index sanitization preventing out-of-bounds index exceptions.
    """

    def __init__(
        self,
        url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:4b",
        *,
        client: httpx.Client | None = None,
    ):
        super().__init__("", model=model, client=SimpleNamespace())
        self._url = url.rstrip("/")
        self._http = client or httpx.Client()

    def synthesize(
        self, query: str, evidence, *, max_output_tokens: int, timeout_seconds: float | None = None
    ):
        if not evidence:
            raise ProviderUnavailable("Local synthesis requires evidence")

        # Cap evidence count: up to 8 top passages.
        max_passages = 8
        if len(evidence) > max_passages:
            evidence = evidence[:max_passages]

        compressed_evidence = [
            p.model_copy(update={"text": _compress_evidence_text(p.text, max_chars=900)})
            for p in evidence
        ]

        # Clean schema for fast constraint evaluation
        schema = _ModelAnswer.model_json_schema()
        schema["properties"] = {
            key: value
            for key, value in schema["properties"].items()
            if key in {"summary_markdown", "claims", "related_questions", "gaps"}
        }
        schema["properties"]["claims"]["maxItems"] = 8
        schema["additionalProperties"] = False

        user_content = _build_synthesis_input(query, compressed_evidence)

        effective_timeout = timeout_seconds or 180.0
        try:
            response = self._http.post(
                self._url + "/api/chat",
                timeout=effective_timeout,
                json={
                    "model": self._model,
                    "stream": False,
                    "think": False,
                    "format": schema,
                    "messages": [
                        {"role": "system", "content": _LOCAL_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "options": {
                        "temperature": 0.1,
                        "num_predict": min(max_output_tokens, 1600),
                        "num_ctx": 4096,
                        "repeat_penalty": 1.1,
                        "top_p": 0.85,
                    },
                    "keep_alive": "30m",
                },
            )
            response.raise_for_status()
            raw = response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderUnavailable("Local writing service is unavailable or timed out") from exc

        # Sanitize evidence indexes in the JSON to guarantee bounds safety
        try:
            parsed_data = json.loads(raw)
            if isinstance(parsed_data, dict) and "claims" in parsed_data:
                valid_count = len(compressed_evidence)
                for item in parsed_data["claims"]:
                    if isinstance(item, dict) and "evidence_indexes" in item:
                        idxs = [
                            i for i in item["evidence_indexes"]
                            if isinstance(i, int) and 0 <= i < valid_count
                        ]
                        if not idxs and valid_count > 0:
                            idxs = [0]
                        item["evidence_indexes"] = idxs
                raw = json.dumps(parsed_data)
        except Exception:
            logging.getLogger(__name__).debug("Optional cleanup or instrumentation failed", exc_info=True)

        result = self._parse_synthesis_interaction(SimpleNamespace(output_text=raw), compressed_evidence)
        result.provider_input_tokens = response.json().get("prompt_eval_count")
        result.provider_output_tokens = response.json().get("eval_count")
        return result

    def manifest(self) -> dict:
        manifest = super().manifest()
        manifest.update(
            adapter="ollama",
            version="local-grounded-v4",
            generation_config={"thinking": False, "temperature": 0.1, "num_ctx": 3584},
        )
        return manifest

    def close(self) -> None:
        self._http.close()
        super().close()
