"""Meeting minutes generation via LLM (ADR-008)."""

import logging
import os
from datetime import datetime
from pathlib import Path

from services.translation import TranslationService

logger = logging.getLogger(__name__)

MINUTES_PROMPT_TEMPLATE = """\
You are a specialized meeting minutes assistant.

Title: {title}
Participants: {participants}
Date/Time: {date}
Duration: {duration}

Full transcript:
{transcript}

Generate professional meeting minutes in Markdown with:
1. Executive summary (3-5 lines)
2. Topics discussed
3. Decisions made
4. Action items with owners and deadlines (as a Markdown table)
5. Pending items

Format: Markdown.
Language: {language}.
"""

CHUNK_SUMMARY_PROMPT = """\
Summarize the following meeting transcript segment concisely.
Keep all key points, decisions, and action items.

Transcript segment:
{chunk}

Summary (in {language}):
"""

SYNTHESIS_PROMPT = """\
You are a specialized meeting minutes assistant.

Title: {title}
Participants: {participants}
Date/Time: {date}
Duration: {duration}

The following are summaries of consecutive segments of a long meeting:

{summaries}

Synthesize these summaries into professional meeting minutes in Markdown with:
1. Executive summary (3-5 lines)
2. Topics discussed
3. Decisions made
4. Action items with owners and deadlines (as a Markdown table)
5. Pending items

Format: Markdown.
Language: {language}.
"""

# Threshold in chars above which we use chunked summarization
CHUNK_THRESHOLD = 6000
CHUNK_SIZE = 4000


class MinutesGenerator:
    """Generates structured meeting minutes from a transcript using an LLM."""

    def __init__(self, llm_service: TranslationService):
        self.llm = llm_service

    async def generate(
        self,
        transcript: str,
        title: str,
        participants: list[str],
        started_at: datetime,
        duration_seconds: int,
        language: str = "pt",
    ) -> str:
        """Generate meeting minutes from the full transcript."""
        if not transcript.strip():
            return self._empty_minutes(title, participants, started_at, language)

        # Format duration
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        duration_str = f"{minutes}min {seconds}s" if seconds else f"{minutes}min"

        prompt = MINUTES_PROMPT_TEMPLATE.format(
            title=title,
            participants=", ".join(participants) if participants else "Not specified",
            date=started_at.strftime("%Y-%m-%d %H:%M"),
            duration=duration_str,
            transcript=transcript,
            language=language,
        )

        try:
            # Use chunked summarization for long transcripts (> 1h meetings)
            if len(transcript) > CHUNK_THRESHOLD:
                content = await self._chunked_generate(
                    transcript, title, participants, started_at, duration_str, language
                )
            else:
                content = await self.llm.generate_text(prompt, max_tokens=2000)
            return self._wrap_with_frontmatter(content, title, participants, started_at, duration_str)
        except NotImplementedError:
            logger.warning("LLM service does not support text generation, returning raw transcript")
            return self._fallback_minutes(transcript, title, participants, started_at, duration_str)
        except Exception as e:
            logger.error(f"Minutes generation failed: {e}")
            return self._fallback_minutes(transcript, title, participants, started_at, duration_str)

    async def _chunked_generate(
        self,
        transcript: str,
        title: str,
        participants: list[str],
        started_at: datetime,
        duration_str: str,
        language: str,
    ) -> str:
        """Generate minutes for long transcripts using chunked summarization."""
        chunks = self._split_transcript(transcript)
        logger.info(f"Long transcript ({len(transcript)} chars) split into {len(chunks)} chunks")

        # Summarize each chunk
        summaries = []
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Summarizing chunk {i}/{len(chunks)}...")
            try:
                prompt = CHUNK_SUMMARY_PROMPT.format(chunk=chunk, language=language)
                summary = await self.llm.generate_text(prompt, max_tokens=800)
                summaries.append(f"### Segment {i}\n{summary}")
            except Exception as e:
                logger.warning(f"Chunk {i} summarization failed: {e}, using raw text")
                summaries.append(f"### Segment {i}\n{chunk[:500]}...")

        # Synthesize final minutes from summaries
        combined = "\n\n".join(summaries)
        synthesis_prompt = SYNTHESIS_PROMPT.format(
            title=title,
            participants=", ".join(participants) if participants else "Not specified",
            date=started_at.strftime("%Y-%m-%d %H:%M"),
            duration=duration_str,
            summaries=combined,
            language=language,
        )
        return await self.llm.generate_text(synthesis_prompt, max_tokens=2000)

    @staticmethod
    def _split_transcript(transcript: str) -> list[str]:
        """Split transcript into chunks at paragraph boundaries."""
        paragraphs = transcript.split("\n\n")
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) > CHUNK_SIZE and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            current_chunk.append(para)
            current_len += len(para)

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks if chunks else [transcript]

    async def save_minutes(
        self, content: str, session_id: str, output_dir: Path
    ) -> Path:
        """Save minutes as a Markdown file."""
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
        filename = f"reuniao_{timestamp}_{session_id[:8]}.md"
        file_path = output_dir / filename

        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Minutes saved to {file_path}")
        return file_path

    def _wrap_with_frontmatter(
        self,
        content: str,
        title: str,
        participants: list[str],
        started_at: datetime,
        duration: str,
    ) -> str:
        """Add YAML frontmatter for Obsidian compatibility (future RFC-001)."""
        participants_yaml = ", ".join(participants) if participants else ""
        frontmatter = (
            f"---\n"
            f"title: {title}\n"
            f"date: {started_at.strftime('%Y-%m-%d')}\n"
            f"duration: {duration}\n"
            f"participants: [{participants_yaml}]\n"
            f"generated_by: VoxVault\n"
            f"---\n\n"
        )
        return frontmatter + content

    def _empty_minutes(
        self, title: str, participants: list[str], started_at: datetime, language: str
    ) -> str:
        return (
            f"# {title}\n\n"
            f"**Date:** {started_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"**Participants:** {', '.join(participants) if participants else 'N/A'}\n\n"
            f"*No transcript content recorded.*\n"
        )

    def _fallback_minutes(
        self,
        transcript: str,
        title: str,
        participants: list[str],
        started_at: datetime,
        duration: str,
    ) -> str:
        """Generate basic minutes without LLM (raw transcript)."""
        header = (
            f"# {title}\n\n"
            f"**Date:** {started_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"**Duration:** {duration}\n"
            f"**Participants:** {', '.join(participants) if participants else 'N/A'}\n\n"
            f"---\n\n"
            f"## Transcript\n\n"
        )
        return self._wrap_with_frontmatter(
            header + transcript, title, participants, started_at, duration
        )
