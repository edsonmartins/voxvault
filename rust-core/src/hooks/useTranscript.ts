import { useCallback, useEffect, useRef, useState } from "react";

const API_URL = "";
const RECONNECT_DELAY_MS = 3000;

/**
 * Hook for streaming transcript data via SSE.
 *
 * Maintains O(1) state updates per incoming chunk:
 * - finalText: accumulated confirmed transcript (append-only string)
 * - partial: current in-progress text (replaced in place)
 * - translatedText: accumulated translations (if enabled)
 *
 * This avoids the previous O(n) array iteration on every update.
 */
export function useTranscript() {
  const [finalText, setFinalText] = useState("");
  const [partial, setPartial] = useState("");
  const [translatedText, setTranslatedText] = useState("");
  const [hasTranslation, setHasTranslation] = useState(false);
  const [connected, setConnected] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [sourceLang, setSourceLang] = useState("auto");
  const [hasContent, setHasContent] = useState(false);
  const [rtf, setRtf] = useState<number | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Refs for copy — accumulate full text without triggering re-render
  const fullTextRef = useRef("");
  const fullTranslatedRef = useRef("");

  useEffect(() => {
    let cancelled = false;

    function connect() {
      if (cancelled) return;

      const es = new EventSource(`${API_URL}/api/transcript/stream`);
      esRef.current = es;

      es.onopen = () => {
        console.log("[useTranscript] SSE connected");
        setConnected(true);
      };

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          // Status/error message from Rust core
          if (data.type === "status") {
            setStatusText(data.text || "");
            return;
          }
          if (data.type === "error") {
            setStatusText(`Error: ${data.text}`);
            return;
          }

          // Translated transcript chunk
          if (data.original_text !== undefined) {
            const text: string = data.original_text;
            const translated: string = data.translated_text || text;
            const isFinal: boolean = data.is_final;
            const lang: string = data.source_language || "auto";

            // Detect translation update: same original_text, different translated_text.
            // The Python orchestrator sends the original first (translated == original),
            // then sends an update later with the actual translation.
            if (isFinal && translated !== text) {
              setHasTranslation(true);
              setTranslatedText((prev) => {
                const updated = prev ? prev + " " + translated : translated;
                fullTranslatedRef.current = updated;
                return updated;
              });
              return;
            }

            if (data.rtf != null) {
              setRtf(data.rtf);
            }

            setSourceLang(lang);
            setHasContent(true);

            if (isFinal) {
              setFinalText((prev) => {
                const updated = prev ? prev + " " + text : text;
                fullTextRef.current = updated;
                return updated;
              });
              setPartial("");
            } else {
              setPartial(text);
            }
          }
        } catch {
          // Ignore malformed SSE data
        }
      };

      es.onerror = () => {
        console.log(
          "[useTranscript] SSE error/disconnected, will reconnect..."
        );
        setConnected(false);
        es.close();
        esRef.current = null;
        if (!cancelled) {
          reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, []);

  const clearTranscript = useCallback(() => {
    setFinalText("");
    setPartial("");
    setTranslatedText("");
    setHasTranslation(false);
    setHasContent(false);
    setSourceLang("auto");
    setRtf(null);
    fullTextRef.current = "";
    fullTranslatedRef.current = "";
  }, []);

  /** Get the full transcript text for clipboard copy. */
  const getFullText = useCallback(() => {
    return fullTranslatedRef.current || fullTextRef.current;
  }, []);

  return {
    finalText,
    partial,
    translatedText,
    hasTranslation,
    connected,
    statusText,
    sourceLang,
    hasContent,
    clearTranscript,
    getFullText,
    rtf,
  };
}
