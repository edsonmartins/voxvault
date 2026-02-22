"""Sentence-level merge buffer for transcript segments.

The Voxtral model splits audio into segments based on silence pauses (~1s).
This often cuts sentences mid-phrase, producing fragments like:
    "but there's still a lot more than"

This module buffers final chunks that don't end with terminal punctuation
and merges them with the next final chunk, producing complete sentences.
"""

import logging
import time

from models.schemas import TranslatedChunk

logger = logging.getLogger(__name__)

# Punctuation that marks the end of a sentence
_TERMINAL_PUNCT = frozenset(".!?。！？")
# Characters that may follow terminal punctuation (quotes, parens)
_TRAILING_CHARS = frozenset("\"')]}»"")


def _ends_with_sentence(text: str) -> bool:
    """Check whether *text* ends with sentence-terminating punctuation."""
    stripped = text.rstrip()
    if not stripped:
        return True  # empty text is "complete"

    last = stripped[-1]
    if last in _TERMINAL_PUNCT:
        return True

    # Allow trailing quote/paren after punctuation: `Hello world."` or `(ok!)`
    if last in _TRAILING_CHARS and len(stripped) >= 2 and stripped[-2] in _TERMINAL_PUNCT:
        return True

    return False


def _merge_chunks(a: TranslatedChunk, b: TranslatedChunk) -> TranslatedChunk:
    """Merge two consecutive final chunks into one."""
    return TranslatedChunk(
        original_text=a.original_text.rstrip() + " " + b.original_text.lstrip(),
        translated_text=a.translated_text.rstrip() + " " + b.translated_text.lstrip(),
        source_language=b.source_language,
        target_language=b.target_language,
        timestamp=a.timestamp,  # keep earliest timestamp
        is_final=True,
    )


class SentenceMerger:
    """Buffer that merges final transcript segments into complete sentences.

    Usage::

        merger = SentenceMerger(timeout_ms=2000)

        # For each incoming final chunk:
        ready = merger.push(chunk)
        if ready:
            broadcast(ready)

        # Periodically (e.g. every 500ms):
        flushed = merger.check_timeout()
        if flushed:
            broadcast(flushed)

        # When session ends:
        flushed = merger.flush()
        if flushed:
            broadcast(flushed)
    """

    def __init__(self, timeout_ms: int = 2000, enabled: bool = True):
        self._timeout_ms = timeout_ms
        self._enabled = enabled
        self._pending: TranslatedChunk | None = None
        self._pending_since: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def push(self, chunk: TranslatedChunk) -> TranslatedChunk | None:
        """Process a final chunk. Returns a merged chunk when ready, or None if buffering."""
        if not self._enabled:
            return chunk

        if self._pending is None:
            # Nothing buffered yet
            if _ends_with_sentence(chunk.original_text):
                return chunk  # complete sentence → send immediately
            # Incomplete sentence → buffer
            self._pending = chunk
            self._pending_since = time.monotonic()
            logger.debug(
                f"[MERGER] Buffered: '{chunk.original_text[:60]}...' (no terminal punct)"
            )
            return None

        # We have a pending chunk — merge with the new one
        merged = _merge_chunks(self._pending, chunk)
        logger.info(
            f"[MERGER] Merged {len(self._pending.original_text)}+"
            f"{len(chunk.original_text)} chars"
        )

        if _ends_with_sentence(merged.original_text):
            # Merged text is a complete sentence → send
            self._pending = None
            self._pending_since = None
            return merged

        # Still incomplete after merge → keep buffering
        self._pending = merged
        self._pending_since = time.monotonic()
        return None

    def check_timeout(self) -> TranslatedChunk | None:
        """Flush the buffer if it has been waiting longer than *timeout_ms*."""
        if self._pending is None or self._pending_since is None:
            return None

        elapsed_ms = (time.monotonic() - self._pending_since) * 1000
        if elapsed_ms >= self._timeout_ms:
            logger.info(
                f"[MERGER] Timeout flush after {elapsed_ms:.0f}ms: "
                f"'{self._pending.original_text[:60]}...'"
            )
            return self.flush()
        return None

    def flush(self) -> TranslatedChunk | None:
        """Force-flush the buffer regardless of sentence completeness."""
        chunk = self._pending
        self._pending = None
        self._pending_since = None
        return chunk

    @property
    def has_pending(self) -> bool:
        return self._pending is not None
