from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("ares.vlm_ocr")


@dataclass(frozen=True, slots=True)
class VlmOcrResult:
    text: str
    confidence: float
    provider: str
    model: str
    warnings: list[str]


class VlmOcrFallback:
    """Vision-Language Model fallback for low-confidence or degraded scanned document pages."""

    def __init__(
        self,
        *,
        provider: str = "none",
        ollama_base_url: str = "http://127.0.0.1:11434",
        ollama_model: str = "qwen2.5-vl:latest",
        gemini_api_key: str = "",
        gemini_model: str = "gemini-2.5-flash",
        confidence_threshold: float = 0.60,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.provider = provider.lower()
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ollama_model = ollama_model
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.confidence_threshold = confidence_threshold
        self.timeout_seconds = timeout_seconds

    def should_fallback(self, page_confidence: float | None, text: str) -> bool:
        """Determine if page OCR quality is insufficient and warrants VLM transcription."""
        if not text.strip():
            return True
        if page_confidence is not None and page_confidence < self.confidence_threshold:
            return True
        return False

    def transcribe_page_image(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/png",
        page_no: int = 1,
    ) -> VlmOcrResult | None:
        """Invoke configured VLM to transcribe the document page image."""
        if self.provider == "none" or not self.provider:
            return None

        prompt = (
            "You are an expert OCR and document digitization engine. "
            "Transcribe all visible text, numbers, headings, captions, and tables from this scanned document page with 100% fidelity. "
            "Preserve layout order and structured table formats where present. "
            "Do NOT summarize, comment, hallucinate, or add metadata. Output ONLY the transcribed page text."
        )

        if self.provider == "ollama":
            return self._transcribe_ollama(image_bytes, prompt=prompt)
        elif self.provider == "gemini":
            return self._transcribe_gemini(image_bytes, mime_type=mime_type, prompt=prompt)
        else:
            logger.warning("Unsupported VLM provider: %s", self.provider)
            return None

    def _transcribe_ollama(self, image_bytes: bytes, *, prompt: str) -> VlmOcrResult | None:
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "images": [b64_image],
            "stream": False,
            "options": {
                "temperature": 0.0,
            },
        }
        url = f"{self.ollama_base_url}/api/generate"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, json=payload)
                if response.status_code != 200:
                    logger.warning("Ollama vision fallback returned status %d: %s", response.status_code, response.text[:200])
                    return None
                data = response.json()
                text = str(data.get("response", "")).strip()
                if not text:
                    return None
                return VlmOcrResult(
                    text=text,
                    confidence=0.88,
                    provider="ollama",
                    model=self.ollama_model,
                    warnings=["Transcribed using local Vision-Language Model fallback (Ollama)."],
                )
        except Exception as exc:
            logger.warning("Ollama vision fallback request failed: %s", exc)
            return None

    def _transcribe_gemini(
        self, image_bytes: bytes, *, mime_type: str, prompt: str
    ) -> VlmOcrResult | None:
        if not self.gemini_api_key:
            logger.warning("Gemini vision fallback requested but no API key configured.")
            return None
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_api_key)
            contents: list[Any] = [
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ]
            response = client.models.generate_content(
                model=self.gemini_model,
                contents=contents,
            )
            text = (response.text or "").strip()
            if not text:
                return None
            return VlmOcrResult(
                text=text,
                confidence=0.92,
                provider="gemini",
                model=self.gemini_model,
                warnings=["Transcribed using Gemini Vision fallback."],
            )
        except Exception as exc:
            logger.warning("Gemini vision fallback request failed: %s", exc)
            return None
