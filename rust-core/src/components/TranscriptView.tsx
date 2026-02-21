import { useEffect, useRef } from "react";
import type { TranslatedChunk } from "../types";

interface TranscriptViewProps {
  chunks: TranslatedChunk[];
}

export function TranscriptView({ chunks }: TranscriptViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new chunks arrive
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [chunks]);

  if (chunks.length === 0) {
    return (
      <div className="transcript-view" ref={containerRef}>
        <div className="transcript-empty">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3z" />
          </svg>
          <p>Start a session to begin transcription</p>
        </div>
      </div>
    );
  }

  return (
    <div className="transcript-view" ref={containerRef}>
      {chunks.map((chunk, i) => (
        <div
          key={i}
          className={`transcript-chunk ${chunk.is_final ? "final" : "partial"}`}
        >
          <div className="chunk-header">
            <span className="chunk-lang">{chunk.source_language.toUpperCase()}</span>
            {!chunk.is_final && <span className="chunk-live">LIVE</span>}
          </div>
          <p className="chunk-original">{chunk.original_text}</p>
          {chunk.is_final &&
            chunk.translated_text !== chunk.original_text && (
              <p className="chunk-translated">
                <span className="chunk-lang-target">
                  {chunk.target_language.toUpperCase()}
                </span>
                {chunk.translated_text}
              </p>
            )}
        </div>
      ))}
    </div>
  );
}
