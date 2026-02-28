"""
test_apple_translation.py

Validates Apple Foundation Models translation quality for real
meeting transcript segments before integrating into VoxVault.

Usage:
    cd python-orchestrator
    pip install -e ../python-apple-fm-sdk/
    python test_apple_translation.py
"""

import asyncio
import sys
import time

from services.translation import AppleTranslation


# Real meeting segments for testing
SEGMENTS_EN_TO_PT = [
    ("short", "The meeting is starting now."),
    ("medium", "We need to review the Q4 sales numbers before the presentation. John, can you share the spreadsheet?"),
    ("technical", "The API integration with the ERP is failing due to a timeout on the Consinco endpoint. We need to increase the retry limit."),
    ("long", "So basically what we decided in the last sprint was to postpone the feature for invoice generation and focus instead on the WhatsApp integration, because the client from Rio de Janeiro is pushing hard for that deliverable before the end of the month, and we really can't afford to miss that deadline given the contract terms."),
    ("jargon", "The NF-e batch processing is stuck. We have 847 pending DANFEs in the queue and the SEFAZ endpoint is returning 500."),
    ("numbers", "Revenue this quarter was R$ 4.850.000,00, up 12.3% from Q3. We're targeting R$ 5.200.000,00 for Q1."),
    ("names", "Maria from the Sao Paulo office will join the call. Pedro is handling the Winthor integration."),
    ("already PT", "Ja finalizamos a integracao com o sistema da distribuidora."),
]

SEGMENTS_PT_TO_EN = [
    ("short", "A reuniao esta comecando."),
    ("medium", "Precisamos fechar o relatorio de vendas antes da apresentacao para o cliente."),
    ("technical", "A integracao via API REST com o Consinco esta retornando timeout. Precisamos aumentar o pool de conexoes."),
]


async def main():
    print("\nApple Foundation Models - Translation Test")
    print("=" * 60)

    provider = AppleTranslation()
    available = await provider._ensure_available()

    if not available:
        print("FAIL: Apple Intelligence not available.")
        print("  Check: System Settings > Apple Intelligence > Enabled")
        sys.exit(1)

    print("OK: Apple Intelligence available\n")

    # Test 1: EN -> PT
    print("EN -> PT-BR Translation")
    print("-" * 60)

    latencies = []
    for label, text in SEGMENTS_EN_TO_PT:
        start = time.perf_counter()
        translated = await provider.translate(text, source_lang="en", target_lang="pt")
        ms = (time.perf_counter() - start) * 1000
        latencies.append(ms)

        print(f"\n[{label}] {ms:.0f}ms")
        print(f"  EN: {text[:80]}{'...' if len(text) > 80 else ''}")
        print(f"  PT: {translated[:80]}{'...' if len(translated) > 80 else ''}")

    avg = sum(latencies) / len(latencies)
    print(f"\n  Avg latency: {avg:.0f}ms")
    print(f"  Max latency: {max(latencies):.0f}ms")

    # Test 2: PT -> EN
    print("\n\nPT -> EN Translation")
    print("-" * 60)

    provider.reset_session("en")
    for label, text in SEGMENTS_PT_TO_EN:
        start = time.perf_counter()
        translated = await provider.translate(text, source_lang="pt", target_lang="en")
        ms = (time.perf_counter() - start) * 1000

        print(f"\n[{label}] {ms:.0f}ms")
        print(f"  PT: {text}")
        print(f"  EN: {translated}")

    # Test 3: Batch
    print("\n\nBatch Test - 5 segments")
    print("-" * 60)

    batch_texts = [t for _, t in SEGMENTS_EN_TO_PT[:5]]
    provider.reset_session("pt")

    start = time.perf_counter()
    results = []
    for text in batch_texts:
        results.append(await provider.translate(text, source_lang="en", target_lang="pt"))
    total_ms = (time.perf_counter() - start) * 1000

    for orig, trad in zip(batch_texts, results):
        print(f"  {orig[:50]:<50} -> {trad[:50]}")

    print(f"\n  Total: {total_ms:.0f}ms | Avg: {total_ms/len(batch_texts):.0f}ms/segment")

    # Verdict
    print("\n" + "=" * 60)
    if avg < 1000:
        print("LATENCY: Excellent (<1s) - suitable for real-time translation")
    elif avg < 2000:
        print("LATENCY: Good (1-2s) - acceptable with slight delay")
    else:
        print("LATENCY: High (>2s) - consider async post-segment translation")

    print("\n  Manually review translation quality above.")
    print("  Focus: technical jargon, proper nouns, monetary values.")


if __name__ == "__main__":
    asyncio.run(main())
