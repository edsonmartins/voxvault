import { useCallback, useEffect, useRef, useState } from "react";
import type { TranslatedChunk } from "../types";

const API_URL = "http://localhost:8766";

export function useTranscript() {
  const [chunks, setChunks] = useState<TranslatedChunk[]>([]);
  const [connected, setConnected] = useState(false);
  const [statusText, setStatusText] = useState("");
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource(`${API_URL}/api/transcript/stream`);
    esRef.current = es;

    es.onopen = () => setConnected(true);

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
          const chunk: TranslatedChunk = data;

          setChunks((prev) => {
            // If last chunk was not final and this one replaces it (partial update)
            if (
              !chunk.is_final &&
              prev.length > 0 &&
              !prev[prev.length - 1].is_final
            ) {
              const updated = [...prev];
              updated[updated.length - 1] = chunk;
              return updated;
            }
            return [...prev, chunk];
          });
        }
      } catch {
        // Ignore malformed SSE data
      }
    };

    es.onerror = () => {
      setConnected(false);
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, []);

  const clearChunks = useCallback(() => setChunks([]), []);

  return { chunks, connected, statusText, clearChunks };
}
