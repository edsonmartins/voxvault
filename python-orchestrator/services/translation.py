"""Translation service abstraction — supports disabled, cloud (Claude/OpenAI), and local modes."""

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
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=(
                    f"You are a precise translator. Translate from {source_lang} to {target_lang}. "
                    "Output ONLY the translated text, no explanations or metadata."
                ),
                messages=[{"role": "user", "content": text}],
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Claude translation error: {e}")
            return text

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
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
            response = await self.client.chat.completions.create(
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
            )
            return response.choices[0].message.content or text
        except Exception as e:
            logger.error(f"OpenAI translation error: {e}")
            return text

    async def generate_text(self, prompt: str, max_tokens: int = 2000) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


def create_translation_service(
    mode: str,
    anthropic_api_key: str = "",
    openai_api_key: str = "",
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

    elif mode == "local":
        logger.warning("Local translation (Gemma 3) not yet implemented, falling back to disabled")
        return DisabledTranslation()

    else:
        return DisabledTranslation()
