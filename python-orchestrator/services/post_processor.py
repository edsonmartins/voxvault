"""Post-processing pipeline for raw ASR transcription output.

Applies rule-based corrections to improve text quality before
sentence merging and translation:
  1. Clean ASR artifacts (repeated words, filler words)
  2. Ensure terminal punctuation
  3. Capitalize sentences and the pronoun "I"
  4. Inverse Text Normalization (spoken numbers to digits)
"""

import re
import logging

logger = logging.getLogger(__name__)


class PostProcessor:
    """Lightweight rule-based post-processor for Voxtral raw output."""

    # Filler words to remove (English + Portuguese + Spanish)
    _FILLERS = re.compile(
        r"\b(uh|um|erm|hmm|hm|ah|eh|oh)\b[,]?\s*",
        re.IGNORECASE,
    )

    # Repeated consecutive words: "the the" -> "the"
    _REPEATED = re.compile(r"\b(\w+)(\s+\1){1,}\b", re.IGNORECASE)

    # Sentence boundary for capitalization
    _SENT_START = re.compile(r"([.!?])\s+([a-z])")

    # "I" pronoun patterns
    _I_STANDALONE = re.compile(r"\bi\b")
    _I_CONTRACTIONS = re.compile(r"\bi('m|'ve|'ll|'d)\b")

    # Number words to digits mapping
    _UNITS = {
        "zero": "0", "one": "1", "two": "2", "three": "3",
        "four": "4", "five": "5", "six": "6", "seven": "7",
        "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
        "twelve": "12", "thirteen": "13", "fourteen": "14",
        "fifteen": "15", "sixteen": "16", "seventeen": "17",
        "eighteen": "18", "nineteen": "19",
    }
    _TENS = {
        "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
        "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
    }

    def process(self, text: str) -> str:
        """Apply all post-processing steps in order."""
        if not text or not text.strip():
            return text

        text = self._clean_artifacts(text)
        text = self._inverse_text_normalize(text)
        text = self._ensure_punctuation(text)
        text = self._capitalize(text)

        return text.strip()

    def _clean_artifacts(self, text: str) -> str:
        """Remove filler words and repeated consecutive words."""
        text = self._FILLERS.sub("", text)
        text = self._REPEATED.sub(r"\1", text)
        text = re.sub(r"  +", " ", text)
        return text

    def _ensure_punctuation(self, text: str) -> str:
        """Add period if text does not end with terminal punctuation."""
        stripped = text.rstrip()
        if not stripped:
            return text
        last = stripped[-1]
        if last in ".!?\u3002\uff01\uff1f":
            return text
        # Allow trailing quote/paren after punctuation
        if len(stripped) >= 2 and stripped[-2] in ".!?" and last in "'\")]}\"\"":
            return text
        return stripped + "."

    def _capitalize(self, text: str) -> str:
        """Capitalize first letter, after sentence endings, and 'I' pronoun."""
        if not text:
            return text

        # Capitalize first character
        if text[0].isalpha() and text[0].islower():
            text = text[0].upper() + text[1:]

        # Capitalize after .!?
        text = self._SENT_START.sub(
            lambda m: m.group(1) + " " + m.group(2).upper(), text
        )

        # Capitalize "I" contractions first (longer match)
        text = self._I_CONTRACTIONS.sub(
            lambda m: "I" + m.group(1), text
        )
        # Capitalize standalone "i"
        text = self._I_STANDALONE.sub("I", text)

        return text

    def _inverse_text_normalize(self, text: str) -> str:
        """Convert spoken number words to digits."""
        # Handle compound tens: "twenty one" -> "21"
        for tens_word, tens_val in self._TENS.items():
            for unit_word, unit_val in self._UNITS.items():
                if int(unit_val) == 0 or int(unit_val) >= 10:
                    continue
                pattern = re.compile(
                    rf"\b{tens_word}[\s-]{unit_word}\b", re.IGNORECASE
                )
                replacement = str(int(tens_val) + int(unit_val))
                text = pattern.sub(replacement, text)

        # Handle standalone tens: "twenty" -> "20"
        for word, val in self._TENS.items():
            text = re.compile(rf"\b{word}\b", re.IGNORECASE).sub(val, text)

        # Handle units (but skip "one" when likely used as pronoun)
        for word, val in self._UNITS.items():
            text = re.compile(rf"\b{word}\b", re.IGNORECASE).sub(val, text)

        # "hundred" and "thousand" patterns: "5 hundred" -> "500"
        text = re.sub(
            r"\b(\d+)\s+hundred\b",
            lambda m: str(int(m.group(1)) * 100),
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(\d+)\s+thousand\b",
            lambda m: str(int(m.group(1)) * 1000),
            text,
            flags=re.IGNORECASE,
        )

        return text


# ---------------------------------------------------------------------------
# Language Detection
# ---------------------------------------------------------------------------

# Stopwords for Latin-script language discrimination
_LANG_STOPWORDS: dict[str, set[str]] = {
    "en": {
        "the", "and", "is", "to", "of", "in", "it", "that", "was",
        "for", "with", "this", "are", "not",
    },
    "pt": {
        "de", "que", "nao", "uma", "com", "para", "por", "mais",
        "foi", "como", "esta", "seu", "dos", "das",
    },
    "es": {
        "que", "el", "en", "los", "del", "las", "por", "con",
        "una", "para", "esta", "como", "pero", "mas",
    },
    "fr": {
        "les", "des", "est", "une", "dans", "pour", "pas",
        "sur", "avec", "sont", "mais", "ont", "vous", "nous",
        "cette", "tout", "elle", "ses", "aux",
    },
    "de": {
        "der", "die", "das", "ist", "und", "ein", "den", "von",
        "nicht", "mit", "ich", "sich", "auf", "auch",
    },
    "it": {
        "che", "non", "una", "per", "sono", "del", "con", "della",
        "questo", "anche", "suo", "hanno", "gli", "molto",
    },
}


def detect_language(text: str) -> str:
    """Detect the source language of transcribed text.

    Uses Unicode script detection for CJK/Hangul, then
    stopword frequency analysis for Latin-script languages.

    Returns a 2-letter language code: en, pt, es, fr, de, it, ja, zh, ko.
    Falls back to "en" when uncertain.
    """
    if not text or not text.strip():
        return "en"

    stripped = text.replace(" ", "").strip()
    if not stripped:
        return "en"

    cjk = 0
    hangul = 0
    hiragana_katakana = 0
    latin = 0
    total = 0

    for ch in stripped:
        if not ch.isalpha():
            continue
        total += 1
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            cjk += 1
        elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
            hangul += 1
        elif 0x3040 <= cp <= 0x30FF:
            hiragana_katakana += 1
        elif ch.isascii() or 0x00C0 <= cp <= 0x024F:
            latin += 1

    if total == 0:
        return "en"

    # Script-based decisions
    if hangul / total > 0.3:
        return "ko"
    if hiragana_katakana / total > 0.2:
        return "ja"
    if cjk / total > 0.3:
        return "ja" if hiragana_katakana > 0 else "zh"

    # Latin script: use stopword frequency
    if latin / total < 0.5:
        return "en"

    words = set(text.lower().split())
    scores: dict[str, int] = {}
    for lang, stopwords in _LANG_STOPWORDS.items():
        scores[lang] = len(words & stopwords)

    if not scores or max(scores.values()) == 0:
        return "en"

    return max(scores, key=scores.get)  # type: ignore[arg-type]
