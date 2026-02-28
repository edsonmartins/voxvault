"""
test_apple_translation.py

Valida a qualidade da tradução Apple FM para segmentos reais
de transcrição de reunião antes de integrar no VoxVault.

Uso:
    cd python-orchestrator
    pip install -e ../../python-apple-fm-sdk/
    python test_apple_translation.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "../../python-apple-fm-sdk/src"))

from providers.apple_provider import AppleTranslationProvider


# Segmentos reais de reunião para teste
SEGMENTOS_EN_PARA_PT = [
    ("curto",    "The meeting is starting now."),
    ("médio",    "We need to review the Q4 sales numbers before the presentation. John, can you share the spreadsheet?"),
    ("técnico",  "The API integration with the ERP is failing due to a timeout on the Consinco endpoint. We need to increase the retry limit."),
    ("longo",    "So basically what we decided in the last sprint was to postpone the feature for invoice generation and focus instead on the WhatsApp integration, because the client from Rio de Janeiro is pushing hard for that deliverable before the end of the month, and we really can't afford to miss that deadline given the contract terms."),
    ("jargão",   "The NF-e batch processing is stuck. We have 847 pending DANFEs in the queue and the SEFAZ endpoint is returning 500."),
    ("números",  "Revenue this quarter was R$ 4.850.000,00, up 12.3% from Q3. We're targeting R$ 5.200.000,00 for Q1."),
    ("names",    "Maria from the São Paulo office will join the call. Pedro is handling the Winthor integration."),
    ("já em PT", "Já finalizamos a integração com o sistema da distribuidora."),  # não deve mudar
]

SEGMENTOS_PT_PARA_EN = [
    ("curto",   "A reunião está começando."),
    ("médio",   "Precisamos fechar o relatório de vendas antes da apresentação para o cliente."),
    ("técnico", "A integração via API REST com o Consinco está retornando timeout. Precisamos aumentar o pool de conexões."),
]


async def main():
    print("\n🍎 Teste de Tradução — Apple Foundation Models")
    print("=" * 60)

    provider = AppleTranslationProvider()
    ok = await provider.initialize()

    if not ok:
        print("❌ Apple Intelligence não disponível.")
        print("   Verifique: Ajustes → Apple Intelligence → Ativado")
        return

    print("✅ Apple Intelligence disponível\n")

    # ── Teste 1: EN → PT ──────────────────────────────────────
    print("📋 Tradução EN → PT-BR")
    print("-" * 60)

    total_ms = []
    for tipo, texto in SEGMENTOS_EN_PARA_PT:
        inicio = time.perf_counter()
        traduzido = await provider.translate(texto, target_lang="pt")
        ms = (time.perf_counter() - inicio) * 1000
        total_ms.append(ms)

        print(f"\n[{tipo}] {ms:.0f}ms")
        print(f"  EN: {texto[:80]}{'...' if len(texto) > 80 else ''}")
        print(f"  PT: {traduzido[:80]}{'...' if len(traduzido) > 80 else ''}")

    print(f"\n  ⏱ Latência média: {sum(total_ms)/len(total_ms):.0f}ms")
    print(f"  ⏱ Latência máxima: {max(total_ms):.0f}ms")

    # ── Teste 2: PT → EN ──────────────────────────────────────
    print("\n\n📋 Tradução PT → EN")
    print("-" * 60)

    provider.reset_session("en")  # nova sessão para este idioma
    for tipo, texto in SEGMENTOS_PT_PARA_EN:
        inicio = time.perf_counter()
        traduzido = await provider.translate(texto, target_lang="en", source_lang="pt")
        ms = (time.perf_counter() - inicio) * 1000

        print(f"\n[{tipo}] {ms:.0f}ms")
        print(f"  PT: {texto}")
        print(f"  EN: {traduzido}")

    # ── Teste 3: Batch (simula re-tradução de sessão) ─────────
    print("\n\n📋 Teste Batch — Sessão Completa (5 segmentos)")
    print("-" * 60)

    segmentos_batch = [t for _, t in SEGMENTOS_EN_PARA_PT[:5]]
    provider.reset_session("pt")

    inicio = time.perf_counter()
    resultados = await provider.translate_batch(segmentos_batch, target_lang="pt")
    total = (time.perf_counter() - inicio) * 1000

    for orig, trad in zip(segmentos_batch, resultados):
        print(f"  ✓ {orig[:50]:<50} → {trad[:50]}")

    print(f"\n  ⏱ Total batch: {total:.0f}ms | Média: {total/len(segmentos_batch):.0f}ms/segmento")

    # ── Veredicto ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    lat_media = sum(total_ms) / len(total_ms)

    if lat_media < 1000:
        print("✅ LATÊNCIA: Excelente (<1s) — adequado para tradução em tempo real")
    elif lat_media < 2000:
        print("🟡 LATÊNCIA: Boa (1-2s) — aceitável para tradução ligeiramente atrasada")
    else:
        print("🔴 LATÊNCIA: Alta (>2s) — considere tradução assíncrona pós-segmento")

    print("\n   Verifique manualmente a qualidade das traduções acima.")
    print("   Foco especial: jargão técnico, nomes próprios, valores monetários.")


if __name__ == "__main__":
    asyncio.run(main())
