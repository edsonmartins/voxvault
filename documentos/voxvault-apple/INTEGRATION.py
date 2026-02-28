"""
COMO INTEGRAR NO python-orchestrator/main.py DO VOXVAULT
=========================================================

1. Copie providers/apple_provider.py para python-orchestrator/providers/

2. No .env, adicione:
   VOXVAULT_TRANSLATION_MODE=apple

3. Aplique as mudanças abaixo no main.py existente.
   As linhas com  ← ADICIONAR  são novas.
   As linhas com  ← SUBSTITUIR  trocam o código existente.
"""

# ── Trecho 1: imports no topo do main.py ──────────────────────

import os
import logging

TRANSLATION_MODE = os.getenv("VOXVAULT_TRANSLATION_MODE", "disabled")
TARGET_LANGUAGE  = os.getenv("VOXVAULT_TARGET_LANGUAGE", "pt")

# ← ADICIONAR: inicialização condicional do provider Apple
_apple_provider = None

async def get_translator():
    """Retorna o provider de tradução configurado no .env"""
    global _apple_provider

    if TRANSLATION_MODE == "apple":
        if _apple_provider is None:
            from providers.apple_provider import AppleTranslationProvider
            _apple_provider = AppleTranslationProvider()
            ok = await _apple_provider.initialize()
            if not ok:
                logging.warning(
                    "Apple FM indisponível — tradução desabilitada. "
                    "Verifique Apple Intelligence em Ajustes."
                )
        return _apple_provider

    # providers existentes permanecem inalterados
    if TRANSLATION_MODE == "claude":
        from providers.claude_provider import ClaudeTranslator
        return ClaudeTranslator()

    if TRANSLATION_MODE == "openai":
        from providers.openai_provider import OpenAITranslator
        return OpenAITranslator()

    if TRANSLATION_MODE == "openrouter":
        from providers.openrouter_provider import OpenRouterTranslator
        return OpenRouterTranslator()

    return None   # disabled


# ── Trecho 2: evento de startup do FastAPI ─────────────────────

# ← ADICIONAR no @app.on_event("startup") existente:
async def startup():
    # ... código de startup existente (DB, sessões, etc.) ...

    # Pré-inicializa o Apple provider para evitar cold start na 1ª tradução
    if TRANSLATION_MODE == "apple":
        await get_translator()
        logging.info("Apple Translation Provider pronto")


# ── Trecho 3: onde a tradução é chamada ───────────────────────
# (provavelmente em algum handler do WebSocket ou processador de segmentos)

# ← SUBSTITUIR a lógica de tradução existente por:
async def translate_segment(text: str) -> str:
    """Traduz um segmento de transcrição usando o provider configurado."""
    if TRANSLATION_MODE == "disabled":
        return text

    translator = await get_translator()

    if translator is None:
        return text

    # Apple provider e os outros compartilham a mesma interface
    if TRANSLATION_MODE == "apple":
        return await translator.translate(text, target_lang=TARGET_LANGUAGE)
    else:
        # interface dos providers existentes (ajuste conforme seu código atual)
        return await translator.translate(text, TARGET_LANGUAGE)


# ── Trecho 4: reset entre sessões ─────────────────────────────

# ← ADICIONAR no endpoint POST /api/session/stop:
async def stop_session(session_id: str):
    # ... código existente de encerramento de sessão ...

    # Reseta contexto do Apple provider entre reuniões
    if TRANSLATION_MODE == "apple" and _apple_provider:
        _apple_provider.reset_session()  # limpa contexto acumulado
        logging.debug("Apple provider: contexto resetado")


# ── Trecho 5: health check ────────────────────────────────────

# ← ADICIONAR no GET /api/health:
async def health():
    health_data = {
        "status": "ok",
        "translation_mode": TRANSLATION_MODE,
        # ... campos existentes ...
    }

    # ← ADICIONAR:
    if TRANSLATION_MODE == "apple" and _apple_provider:
        health_data["apple_fm_available"] = _apple_provider.is_available

    return health_data
