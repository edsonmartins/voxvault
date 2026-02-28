"""
providers/apple_provider.py

Provider de tradução usando Apple Foundation Models (on-device).
Substitui chamadas externas para Claude/OpenAI quando
VOXVAULT_TRANSLATION_MODE=apple

Requisitos:
  - macOS 26+ com Apple Intelligence ativado
  - SDK instalado: pip install -e ../../python-apple-fm-sdk/
  - Python 3.10+

Vantagens para tradução:
  - On-device: zero latência de rede, zero custo
  - LGPD: áudio e texto nunca saem do dispositivo
  - Ideal para frases curtas de transcrição em tempo real

Limitação:
  - Context window ~4K tokens — suficiente para segmentos de transcrição
  - Qualidade em pt-BR boa mas inferior ao Claude Sonnet para textos complexos
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Mapeamento de código ISO → nome completo para o prompt
LANG_NAMES = {
    "pt": "Brazilian Portuguese",
    "pt-BR": "Brazilian Portuguese",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ja": "Japanese",
    "zh": "Simplified Chinese",
}

INSTRUCTIONS_TRANSLATION = """
You are a professional real-time meeting transcript translator.
Rules:
- Translate accurately and naturally, preserving the speaker's tone
- Keep technical terms, proper nouns and acronyms as-is
- Return ONLY the translated text — no explanations, no quotes, no preamble
- If the text is already in the target language, return it unchanged
- Preserve line breaks from the original
"""


class AppleTranslationProvider:
    """
    Provider de tradução usando Apple Foundation Models on-device.
    
    Mantém uma sessão persistente por idioma alvo para
    aproveitar o contexto entre segmentos consecutivos.
    
    Uso:
        provider = AppleTranslationProvider()
        await provider.initialize()
        
        translated = await provider.translate(
            text="The sales meeting went well.",
            target_lang="pt"
        )
        # → "A reunião de vendas correu bem."
    """

    def __init__(self):
        self._fm = None          # módulo apple_fm_sdk (importado lazy)
        self._available = False
        self._sessions: dict[str, object] = {}   # uma sessão por target_lang
        self._lock = asyncio.Lock()

    async def initialize(self) -> bool:
        """
        Verifica disponibilidade e inicializa o SDK.
        Retorna True se Apple Intelligence estiver disponível.
        """
        try:
            import apple_fm_sdk as fm
            self._fm = fm

            model = fm.SystemLanguageModel()
            ok, reason = model.is_available()

            if not ok:
                logger.warning(f"[AppleProvider] Modelo não disponível: {reason}")
                logger.warning("[AppleProvider] Verifique: Ajustes → Apple Intelligence → Ativado")
                return False

            self._available = True
            logger.info("[AppleProvider] Apple Foundation Models inicializado com sucesso")
            return True

        except ImportError:
            logger.error(
                "[AppleProvider] apple_fm_sdk não instalado. "
                "Execute: pip install -e ../../python-apple-fm-sdk/"
            )
            return False
        except Exception as e:
            logger.error(f"[AppleProvider] Erro na inicialização: {e}")
            return False

    @property
    def is_available(self) -> bool:
        return self._available

    def _get_session(self, target_lang: str) -> object:
        """Retorna sessão existente ou cria uma nova para o idioma."""
        if target_lang not in self._sessions:
            self._sessions[target_lang] = self._fm.LanguageModelSession(
                instructions=INSTRUCTIONS_TRANSLATION
            )
            logger.debug(f"[AppleProvider] Nova sessão criada para lang={target_lang}")
        return self._sessions[target_lang]

    async def translate(
        self,
        text: str,
        target_lang: str = "pt",
        source_lang: Optional[str] = None,
    ) -> str:
        """
        Traduz um segmento de transcrição.

        Args:
            text:        Texto a traduzir (segmento de reunião)
            target_lang: Código ISO do idioma alvo (ex: "pt", "en", "es")
            source_lang: Código ISO do idioma origem (opcional — modelo detecta automaticamente)

        Returns:
            Texto traduzido ou texto original em caso de erro
        """
        if not self._available:
            logger.warning("[AppleProvider] translate() chamado sem inicialização")
            return text

        if not text or not text.strip():
            return text

        lang_name = LANG_NAMES.get(target_lang, target_lang)

        # Monta prompt — direto e sem ambiguidade
        if source_lang:
            source_name = LANG_NAMES.get(source_lang, source_lang)
            prompt = f"Translate from {source_name} to {lang_name}:\n{text}"
        else:
            prompt = f"Translate to {lang_name}:\n{text}"

        try:
            async with self._lock:
                session = self._get_session(target_lang)
                response = await session.respond(prompt=prompt)

            result = str(response).strip()
            logger.debug(f"[AppleProvider] Traduzido ({len(text)}→{len(result)} chars)")
            return result

        except Exception as e:
            # Context window excedido — recria a sessão e tenta uma vez mais
            if "context" in str(e).lower() or "exceeded" in str(e).lower():
                logger.warning("[AppleProvider] Context window excedido — recriando sessão")
                self._sessions.pop(target_lang, None)
                try:
                    async with self._lock:
                        session = self._get_session(target_lang)
                        response = await session.respond(prompt=prompt)
                    return str(response).strip()
                except Exception as e2:
                    logger.error(f"[AppleProvider] Erro na segunda tentativa: {e2}")

            logger.error(f"[AppleProvider] Erro na tradução: {e}")
            return text  # fallback: retorna original sem travar o pipeline

    async def translate_batch(
        self,
        segments: list[str],
        target_lang: str = "pt",
    ) -> list[str]:
        """
        Traduz múltiplos segmentos sequencialmente.
        Útil para retraduzir uma sessão completa.

        Args:
            segments:    Lista de segmentos de texto
            target_lang: Idioma alvo

        Returns:
            Lista de segmentos traduzidos na mesma ordem
        """
        results = []
        for segment in segments:
            translated = await self.translate(segment, target_lang)
            results.append(translated)
        return results

    def reset_session(self, target_lang: Optional[str] = None):
        """
        Descarta sessão(ões) para liberar contexto acumulado.
        Útil entre reuniões diferentes.

        Args:
            target_lang: Se informado, descarta só a sessão desse idioma.
                         Se None, descarta todas.
        """
        if target_lang:
            self._sessions.pop(target_lang, None)
            logger.debug(f"[AppleProvider] Sessão resetada para lang={target_lang}")
        else:
            self._sessions.clear()
            logger.debug("[AppleProvider] Todas as sessões resetadas")


# ──────────────────────────────────────────────────────────────
# Singleton — uma instância para todo o Orchestrator
# ──────────────────────────────────────────────────────────────
_provider_instance: Optional[AppleTranslationProvider] = None


async def get_apple_provider() -> AppleTranslationProvider:
    """
    Retorna o singleton do provider, inicializando na primeira chamada.
    
    Uso no FastAPI:
        from providers.apple_provider import get_apple_provider
        
        provider = await get_apple_provider()
        translated = await provider.translate(text, target_lang="pt")
    """
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = AppleTranslationProvider()
        await _provider_instance.initialize()
    return _provider_instance
