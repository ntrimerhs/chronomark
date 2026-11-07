"""DeepSeek client. All API-shape differences live here and nowhere else.

Verified against https://api-docs.deepseek.com/guides/vision/ :
  - model id "deepseek-flash" accepts images
  - OpenAI-compatible image_url content blocks with base64 data URLs
  - detail="low" downscales to 512x512
  - each image costs at most 1024 tokens, whatever its pixel size
"""
import base64
import time
import logging
from pathlib import Path
from typing import Iterable

from openai import OpenAI

from pipeline import utils
from pipeline.config import Settings


class Usage:
    """Token accounting for the run manifest."""

    def __init__(self) -> None:
        self.requests = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def add(self, usage) -> None:
        self.requests += 1
        if usage is None:
            return
        self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
        self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
        }


class DeepSeekClient:
    def __init__(self, settings: Settings, usage: Usage | None = None) -> None:
        if not settings.api_key or settings.api_key == "replace_me":
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        if not settings.vision_model:
            raise RuntimeError("DEEPSEEK_VISION_MODEL is not set")
        self.settings = settings
        self.usage = usage or Usage()
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.request_timeout_sec,
        )

    def _rebuild(self) -> None:
        """Replace the HTTP client.

        httpx keeps connections alive between requests. When the server closes
        an idle one, every retry reuses the same dead connection and fails
        identically -- which is exactly what produced bursts of
        "Connection error" that survived all three attempts. A fresh client has
        a fresh pool.
        """
        self.client = OpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            timeout=self.settings.request_timeout_sec,
        )

    def _call(self, factory):
        """Run `factory`, rebuilding the connection on transport failures."""
        last_error = None
        for attempt in range(self.settings.max_retries):
            try:
                return factory()
            except Exception as exc:  # noqa: BLE001 - transport errors are retried
                message = f"{type(exc).__name__}: {exc}"
                last_error = exc
                if attempt == self.settings.max_retries - 1:
                    break
                logging.warning("attempt %d failed (%s); rebuilding connection", attempt + 1, message[:80])
                self._rebuild()
                time.sleep(min(30, 2 ** attempt))
        raise RuntimeError(f"failed after {self.settings.max_retries} attempts: {last_error}") from last_error

    def _image_block(self, path: Path) -> dict:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{encoded}",
                "detail": "low",
            },
        }

    def analyse_frames(self, frames: Iterable[tuple[float, Path]], prompt: str) -> str:
        """Send one chronological batch of frames and return the raw reply."""
        content: list[dict] = [{"type": "text", "text": prompt}]
        for absolute_sec, path in frames:
            content.append({
                "type": "text",
                "text": f"Frame at {utils.hms(absolute_sec)} (absolute)",
            })
            content.append(self._image_block(path))

        def call():
            response = self.client.chat.completions.create(
                model=self.settings.vision_model,
                messages=[{"role": "user", "content": content}],
                # Thinking is ON by default at effort "high", and its tokens are
                # billed as output. On a merge this burned the whole max_tokens
                # budget before any text was produced, so content came back
                # empty; on analysis it was ~70% of the completion cost.
                extra_body={"thinking": {"type": "disabled"}},
            )
            self.usage.add(getattr(response, "usage", None))
            return response.choices[0].message.content or ""

        # Never log the payload: it contains base64 image data.
        return self._call(call)

    def complete_text(self, prompt: str, max_tokens: int = 2000) -> str:
        """Text-only completion, used for the final merge so it costs no vision."""
        def call():
            response = self.client.chat.completions.create(
                model=self.settings.text_model or self.settings.vision_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
            self.usage.add(getattr(response, "usage", None))
            return response.choices[0].message.content or ""

        return self._call(call)