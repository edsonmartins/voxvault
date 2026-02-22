import { useEffect, useRef } from "react";

interface TranscriptViewProps {
  finalText: string;
  partial: string;
  translatedText: string;
  hasTranslation: boolean;
  targetLang: string;
}

export function TranscriptView({
  finalText,
  partial,
  translatedText,
  hasTranslation,
  targetLang,
}: TranscriptViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when text changes
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [finalText, partial]);

  const isEmpty = !finalText && !partial;

  if (isEmpty) {
    return (
      <div className="transcript-view" ref={containerRef}>
        <div className="transcript-empty">
          <svg
            width="48"
            height="48"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3z" />
          </svg>
          <p>Start a session to begin transcription</p>
        </div>
      </div>
    );
  }

  return (
    <div className="transcript-view" ref={containerRef}>
      <div className="transcript-flow">
        {finalText && <span className="flow-final">{finalText}</span>}
        {partial && (
          <>
            {finalText && " "}
            <span className="flow-partial">{partial}</span>
            <span className="flow-cursor" />
          </>
        )}
      </div>

      {hasTranslation && translatedText && (
        <div className="transcript-translation">
          <span className="translation-label">
            {targetLang?.toUpperCase() || "PT"}
          </span>
          {translatedText}
        </div>
      )}
    </div>
  );
}
