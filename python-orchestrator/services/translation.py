"""Translation service abstraction — supports disabled, cloud (Claude/OpenAI), and local MLX modes."""

import asyncio
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class TranslationService(ABC):
    """Abstract base class for translation services."""

    @abstractmethod
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text from source to target language.

        Returns the translated text, or the original text if translation
        is not needed (e.g., source == target).
        """
        ...

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        """Generate text from a prompt (used for meeting minutes).

        Subclasses that support LLM generation should override this.
        """
        raise NotImplementedError("This translation service does not support text generation")


class DisabledTranslation(TranslationService):
    """No-op translation — returns original text."""

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        return text

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        raise NotImplementedError(
            "Translation is disabled. Enable Claude or OpenAI to generate minutes."
        )


class ClaudeTranslation(TranslationService):
    """Translation via Anthropic Claude Haiku API."""

    def __init__(self, api_key: str):
        import anthropic

        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = "claude-haiku-4-5-20251001"

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text

        try:
            response = await asyncio.wait_for(
                self.client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=(
                        f"You are a precise translator. Translate from {source_lang} to {target_lang}. "
                        "Output ONLY the translated text, no explanations or metadata."
                    ),
                    messages=[{"role": "user", "content": text}],
                ),
                timeout=30.0,
            )
            return response.content[0].text
        except asyncio.TimeoutError:
            logger.error("Claude translation timed out (30s)")
            return text
        except Exception as e:
            logger.error(f"Claude translation error: {e}")
            return text

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        response = await asyncio.wait_for(
            self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=60.0,
        )
        return response.content[0].text


class OpenAITranslation(TranslationService):
    """Translation via OpenAI GPT-4o-mini API."""

    def __init__(self, api_key: str):
        import openai

        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = "gpt-4o-mini"

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text

        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"Translate from {source_lang} to {target_lang}. "
                                "Output ONLY the translated text."
                            ),
                        },
                        {"role": "user", "content": text},
                    ],
                    temperature=0,
                ),
                timeout=30.0,
            )
            return response.choices[0].message.content or text
        except asyncio.TimeoutError:
            logger.error("OpenAI translation timed out (30s)")
            return text
        except Exception as e:
            logger.error(f"OpenAI translation error: {e}")
            return text

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        response = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            ),
            timeout=60.0,
        )
        return response.choices[0].message.content or ""


class OpenRouterTranslation(TranslationService):
    """Translation via OpenRouter API (OpenAI-compatible, access to many models)."""

    def __init__(self, api_key: str, model: str = "google/gemma-3-27b-it:free"):
        import openai

        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.model = model

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text

        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"Translate from {source_lang} to {target_lang}. "
                                "Output ONLY the translated text."
                            ),
                        },
                        {"role": "user", "content": text},
                    ],
                    temperature=0,
                ),
                timeout=30.0,
            )
            return response.choices[0].message.content or text
        except asyncio.TimeoutError:
            logger.error("OpenRouter translation timed out (30s)")
            return text
        except Exception as e:
            logger.error(f"OpenRouter translation error: {e}")
            return text

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        response = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            ),
            timeout=60.0,
        )
        return response.choices[0].message.content or ""


class LocalMLXTranslation(TranslationService):
    """Translation via local MLX model (Apple Silicon only).

    Uses mlx-lm to run a quantized Gemma 3 model locally.
    The model is loaded lazily on first use and kept in memory.
    """

    def __init__(self, model_name: str = "mlx-community/gemma-3-4b-it-4bit"):
        self.model_name = model_name
        self._model = None
        self._tokenizer = None

    async def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        logger.info(f"Loading local MLX model: {self.model_name} (this may take a moment)...")
        try:
            from mlx_lm import load
            self._model, self._tokenizer = await asyncio.to_thread(
                load, self.model_name
            )
            logger.info("Local MLX model loaded successfully")
        except ImportError:
            raise RuntimeError(
                "mlx-lm is not installed. Install it with: pip install mlx-lm"
            )

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text

        await self._ensure_loaded()

        prompt = (
            f"Translate the following text from {source_lang} to {target_lang}. "
            "Output ONLY the translation, nothing else.\n\n"
            f"Text: {text}\n\nTranslation:"
        )

        try:
            from mlx_lm import generate
            result = await asyncio.to_thread(
                generate,
                self._model,
                self._tokenizer,
                prompt=prompt,
                max_tokens=512,
            )
            return result.strip()
        except Exception as e:
            logger.error(f"Local MLX translation error: {e}")
            return text

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        await self._ensure_loaded()

        from mlx_lm import generate
        result = await asyncio.to_thread(
            generate,
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
        )
        return result.strip()


# Language code → display name mapping for Apple FM prompts
_APPLE_LANG_NAMES = {
    "pt": "Brazilian Portuguese", "pt-BR": "Brazilian Portuguese",
    "en": "English", "es": "Spanish", "fr": "French",
    "de": "German", "it": "Italian", "ja": "Japanese",
    "zh": "Simplified Chinese",
}

_APPLE_TRANSLATION_INSTRUCTIONS = (
    "You are a professional real-time meeting transcript translator.\n"
    "Rules:\n"
    "- Translate accurately and naturally, preserving the speaker's tone\n"
    "- Keep technical terms, proper nouns and acronyms as-is\n"
    "- Return ONLY the translated text — no explanations, no quotes, no preamble\n"
    "- If the text is already in the target language, return it unchanged\n"
    "- Preserve line breaks from the original"
)


class AppleTranslation(TranslationService):
    """Translation via Apple Foundation Models (on-device, macOS 26+).

    Zero cost, LGPD compliant — text never leaves the device.
    Requires Apple Intelligence enabled in System Settings.
    """

    def __init__(self):
        self._fm = None
        self._available = False
        self._sessions: dict[str, object] = {}
        self._lock = asyncio.Lock()

    async def _ensure_available(self) -> bool:
        """Lazy-init the SDK on first use. Returns True if available."""
        if self._fm is not None:
            return self._available
        try:
            import apple_fm_sdk as fm
            self._fm = fm
            model = fm.SystemLanguageModel()
            ok, reason = model.is_available()
            if not ok:
                logger.warning(f"Apple FM not available: {reason}")
                self._available = False
            else:
                self._available = True
                logger.info("Apple Foundation Models initialized (on-device)")
        except ImportError:
            logger.warning(
                "apple_fm_sdk not installed. "
                "Install with: pip install -e ./python-apple-fm-sdk/"
            )
            self._available = False
        except Exception as e:
            logger.error(f"Apple FM init error: {e}")
            self._available = False
        return self._available

    @property
    def is_available(self) -> bool:
        return self._available

    def _get_session(self, target_lang: str) -> object:
        """Return existing session or create a new one for the language."""
        if target_lang not in self._sessions:
            self._sessions[target_lang] = self._fm.LanguageModelSession(
                instructions=_APPLE_TRANSLATION_INSTRUCTIONS
            )
        return self._sessions[target_lang]

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text
        if not text or not text.strip():
            return text

        if not await self._ensure_available():
            return text

        source_name = _APPLE_LANG_NAMES.get(source_lang, source_lang)
        target_name = _APPLE_LANG_NAMES.get(target_lang, target_lang)
        prompt = f"Translate from {source_name} to {target_name}:\n{text}"

        try:
            async with self._lock:
                session = self._get_session(target_lang)
                response = await asyncio.wait_for(
                    session.respond(prompt=prompt), timeout=30.0
                )
            return str(response).strip()
        except asyncio.TimeoutError:
            logger.error("Apple FM translation timed out (30s)")
            return text
        except Exception as e:
            # Context window exceeded — recreate session and retry once
            if "context" in str(e).lower() or "exceeded" in str(e).lower():
                logger.warning("Apple FM context exceeded — recreating session")
                self._sessions.pop(target_lang, None)
                try:
                    async with self._lock:
                        session = self._get_session(target_lang)
                        response = await asyncio.wait_for(
                            session.respond(prompt=prompt), timeout=30.0
                        )
                    return str(response).strip()
                except Exception as e2:
                    logger.error(f"Apple FM retry failed: {e2}")
            else:
                logger.error(f"Apple FM translation error: {e}")
            return text

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        if not await self._ensure_available():
            raise NotImplementedError("Apple FM not available")
        session = self._fm.LanguageModelSession()
        response = await session.respond(prompt=prompt)
        return str(response).strip()

    def reset_session(self, target_lang: str | None = None):
        """Discard session(s) to free accumulated context. Call between meetings."""
        if target_lang:
            self._sessions.pop(target_lang, None)
        else:
            self._sessions.clear()
        logger.debug("Apple FM sessions reset")


def create_translation_service(
    mode: str,
    anthropic_api_key: str = "",
    openai_api_key: str = "",
    openrouter_api_key: str = "",
    openrouter_model: str = "",
    gemma_model_path: str = "",
) -> TranslationService:
    """Factory function to create the appropriate translation service."""
    if mode == "claude":
        if not anthropic_api_key:
            logger.warning("Claude translation selected but no API key set, falling back to disabled")
            return DisabledTranslation()
        return ClaudeTranslation(api_key=anthropic_api_key)

    elif mode == "openai":
        if not openai_api_key:
            logger.warning("OpenAI translation selected but no API key set, falling back to disabled")
            return DisabledTranslation()
        return OpenAITranslation(api_key=openai_api_key)

    elif mode == "openrouter":
        if not openrouter_api_key:
            logger.warning("OpenRouter translation selected but no API key set, falling back to disabled")
            return DisabledTranslation()
        model = openrouter_model or "google/gemma-3-27b-it:free"
        return OpenRouterTranslation(api_key=openrouter_api_key, model=model)

    elif mode == "local":
        try:
            import mlx_lm  # noqa: F401
            model_name = gemma_model_path or "mlx-community/gemma-3-4b-it-4bit"
            return LocalMLXTranslation(model_name=model_name)
        except ImportError:
            logger.warning("mlx-lm not installed, falling back to disabled. Install with: pip install mlx-lm")
            return DisabledTranslation()

    elif mode == "apple":
        return AppleTranslation()

    else:
        return DisabledTranslation()
