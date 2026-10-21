from __future__ import annotations

import json
import re

import httpx

from ares.adapters.grounded_synthesis import (
    GroundedSynthesisBase,
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


class OllamaLLMProvider(GroundedSynthesisBase):
    """Bounded local transport sharing the same strict citation parser as Gemini."""

    def __init__(self, url: str = "http://127.0.0.1:11434", model: str = "qwen3:4b", *,
                 client: httpx.Client | None = None, context_tokens: int = 4096,
                 passage_chars: int = 900):
        self._model = model
        self._url = url.rstrip("/")
        self._context_tokens = context_tokens
        self._passage_chars = passage_chars
        self._http = client or httpx.Client(limits=httpx.Limits(max_connections=4, max_keepalive_connections=2))

    def synthesize(self, query: str, evidence, *, max_output_tokens: int,
                   timeout_seconds: float | None = None):
        import time
        if not evidence:
            raise ProviderUnavailable("Local synthesis requires evidence")
        evidence = evidence[:8]
        compressed = [p.model_copy(update={"text": _compress_evidence_text(p.text, self._passage_chars)}) for p in evidence]
        schema = _ModelAnswer.model_json_schema()
        schema["properties"] = {k: v for k, v in schema["properties"].items()
                                 if k in {"summary_markdown", "claims", "related_questions", "gaps"}}
        schema["properties"]["claims"]["maxItems"] = 8
        schema["additionalProperties"] = False
        deadline = time.monotonic() + (timeout_seconds or 180.0)
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderUnavailable("Local synthesis timed out")
            try:
                response = self._http.post(self._url + "/api/chat", timeout=remaining, json={
                    "model": self._model, "stream": False, "think": False,
                    "format": schema if attempt == 0 else "json",
                    "messages": [{"role": "system", "content": _LOCAL_SYSTEM_PROMPT},
                                 {"role": "user", "content": _build_synthesis_input(query, compressed)}],
                    "options": {"temperature": 0.1, "num_predict": min(max_output_tokens, 1600),
                                "num_ctx": self._context_tokens, "repeat_penalty": 1.1, "top_p": 0.85},
                    "keep_alive": "30m"})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderUnavailable("Local writing service is unavailable or timed out") from exc
            try:
                payload = response.json()
                result = self.parse_output(payload["message"]["content"], compressed)
                result.provider_input_tokens = payload.get("prompt_eval_count")
                result.provider_output_tokens = payload.get("eval_count")
                return result
            except (ProviderUnavailable, KeyError, ValueError, TypeError) as exc:
                if attempt == 1:
                    raise ProviderUnavailable("Local writing returned invalid grounded output after retry") from exc
        raise ProviderUnavailable("Local writing returned no output")

    def manifest(self) -> dict:
        import hashlib
        return {"adapter": "ollama", "version": "local-grounded-v5", "model": self._model,
                "prompt_digest": hashlib.sha256(_LOCAL_SYSTEM_PROMPT.encode()).hexdigest(),
                "schema_digest": hashlib.sha256(json.dumps(_ModelAnswer.model_json_schema(), sort_keys=True).encode()).hexdigest(),
                "generation_config": {"thinking": False, "temperature": 0.1, "num_ctx": self._context_tokens,
                                      "passage_chars": self._passage_chars}}

    def close(self) -> None:
        self._http.close()
