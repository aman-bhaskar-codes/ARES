from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ares.adapters.grounded_synthesis import _SYSTEM_INSTRUCTION as _SYSTEM_INSTRUCTION
from ares.adapters.grounded_synthesis import GroundedSynthesisBase, _answer_style
from ares.adapters.grounded_synthesis import ProviderUnavailable as ProviderUnavailable
from ares.adapters.grounded_synthesis import _build_synthesis_input as _build_synthesis_input
from ares.adapters.grounded_synthesis import _ModelAnswer as _ModelAnswer
from ares.domain.models import SynthesisResult
from ares.domain.research import EvidencePacket


def _interaction_error(exc: Exception) -> ProviderUnavailable:
    if getattr(exc, 'code', getattr(exc, 'status_code', None)) == 429:
        return ProviderUnavailable('Gemini quota or rate limit reached. Retry after the provider quota resets, or configure a model/key with available quota.')
    return ProviderUnavailable('Gemini interaction failed')

class GeminiLLMProvider(GroundedSynthesisBase):

    def __init__(self, api_key: str, model: str='gemini-3.8-flash', *, thinking_level: str='low', timeout_seconds: float=45.0, client: Any | None=None):
        owns_client = client is None
        if client is None:
            if not api_key:
                raise ProviderUnavailable('GEMINI_API_KEY is required for live mode')
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise ProviderUnavailable('google-genai is not installed') from exc
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=max(1, int(float(timeout_seconds) * 1000)), retry_options=types.HttpRetryOptions(attempts=0)))
        self._client = client
        self._runner = asyncio.Runner()
        self._owns_client = owns_client
        self._model = model
        self._thinking_level = thinking_level

    async def _async_synthesize(self, query: str, evidence: list[EvidencePacket], *, max_output_tokens: int) -> SynthesisResult:
        model_input = _build_synthesis_input(query, evidence)
        interaction = await self._client.aio.interactions.create(model=self._model, system_instruction=_SYSTEM_INSTRUCTION, input=model_input, store=False, generation_config={'max_output_tokens': min(max_output_tokens, int(_answer_style(query)['max_output_tokens'])), 'thinking_level': self._thinking_level, 'thinking_summaries': 'none'}, response_format={'type': 'text', 'mime_type': 'application/json', 'schema': self.response_schema()})
        return self._parse_synthesis_interaction(interaction, evidence)

    def synthesize(self, query: str, evidence: list[EvidencePacket], *, max_output_tokens: int, timeout_seconds: float | None=None) -> SynthesisResult:
        if not evidence:
            raise ProviderUnavailable('Gemini synthesis requires evidence')
        if timeout_seconds is not None and getattr(self._client, 'aio', None):
            try:
                return self._runner.run(asyncio.wait_for(self._async_synthesize(query, evidence, max_output_tokens=max_output_tokens), timeout=timeout_seconds))
            except TimeoutError as exc:
                raise ProviderUnavailable('Gemini synthesis timed out') from exc
            except ProviderUnavailable:
                raise
            except Exception as exc:
                logging.getLogger(__name__).warning("gemini: recovery boundary (%s)", type(exc).__name__)
                raise _interaction_error(exc) from exc
        model_input = _build_synthesis_input(query, evidence)
        try:
            interaction = self._client.interactions.create(model=self._model, system_instruction=_SYSTEM_INSTRUCTION, input=model_input, store=False, generation_config={'max_output_tokens': min(max_output_tokens, int(_answer_style(query)['max_output_tokens'])), 'thinking_level': self._thinking_level, 'thinking_summaries': 'none'}, response_format={'type': 'text', 'mime_type': 'application/json', 'schema': self.response_schema()})
        except Exception as exc:
            logging.getLogger(__name__).warning("gemini: recovery boundary (%s)", type(exc).__name__)
            raise _interaction_error(exc) from exc
        return self._parse_synthesis_interaction(interaction, evidence)

    def manifest(self) -> dict:
        import hashlib
        prompt_digest = hashlib.sha256(_SYSTEM_INSTRUCTION.encode()).hexdigest()
        schema_digest = hashlib.sha256(json.dumps(self.response_schema(), sort_keys=True).encode()).hexdigest()
        return {'adapter': 'gemini', 'version': 'm12-v1', 'model': self._model, 'prompt_digest': prompt_digest, 'schema_digest': schema_digest, 'generation_config': {'thinking_level': self._thinking_level, 'thinking_summaries': 'none'}}

    def close(self) -> None:
        try:
            if self._owns_client:
                aio_close = getattr(getattr(self._client, 'aio', None), 'aclose', None)
                if callable(aio_close):
                    self._runner.run(aio_close())
                close = getattr(self._client, 'close', None)
                if callable(close):
                    close()
        finally:
            self._runner.close()

    def _parse_synthesis_interaction(self, interaction: Any, evidence: list[EvidencePacket]) -> SynthesisResult:
        return self.parse_output(getattr(interaction, 'output_text', ''), evidence)
