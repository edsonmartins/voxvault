import { useCallback, useEffect, useRef, useState } from "react";
import { TitleBar } from "./components/TitleBar";
import { StatusBar } from "./components/StatusBar";
import { TranscriptView } from "./components/TranscriptView";
import { SettingsPanel } from "./components/SettingsPanel";
import { useTranscript } from "./hooks/useTranscript";
import { useSession } from "./hooks/useSession";
import { useNotification } from "./hooks/useNotification";

function App() {
  const { chunks, connected, statusText, clearChunks } = useTranscript();
  const { session, isActive, loading, error, startSession, stopSession } =
    useSession();

  const { notify } = useNotification();
  const [showSettings, setShowSettings] = useState(false);
  const [stealthMode, setStealthMode] = useState(true);
  const [duration, setDuration] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Session timer
  useEffect(() => {
    if (isActive) {
      setDuration(0);
      timerRef.current = setInterval(() => {
        setDuration((prev) => prev + 1);
      }, 1000);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isActive]);

  const handleStart = useCallback(() => {
    clearChunks();
    startSession();
    notify("VoxVault", "Session started — transcribing...");
  }, [clearChunks, startSession, notify]);

  const handleStop = useCallback(async () => {
    const result = await stopSession();
    if (result) {
      const mins = Math.floor(result.duration_seconds / 60);
      const secs = result.duration_seconds % 60;
      notify(
        "Session ended",
        `Duration: ${mins}m ${secs}s — ${result.transcript_chunks} chunks recorded`
      );
    }
  }, [stopSession, notify]);

  const handleCopy = useCallback(() => {
    const text = chunks
      .filter((c) => c.is_final)
      .map((c) => c.translated_text || c.original_text)
      .join("\n");
    navigator.clipboard.writeText(text);
  }, [chunks]);

  // Detect primary language from chunks
  const detectedLang =
    chunks.length > 0 ? chunks[chunks.length - 1].source_language : "auto";

  return (
    <div className="app">
      <TitleBar
        onSettingsClick={() => setShowSettings(true)}
        stealthMode={stealthMode}
      />

      <StatusBar
        connected={connected}
        isRecording={isActive}
        language={detectedLang}
        duration={duration}
        statusText={statusText}
      />

      <TranscriptView chunks={chunks} />

      {/* Action Bar */}
      <div className="action-bar">
        {error && <div className="action-error">{error}</div>}

        <div className="action-buttons">
          {!isActive ? (
            <button
              className="btn btn-start"
              onClick={handleStart}
              disabled={loading}
            >
              {loading ? (
                <span className="spinner" />
              ) : (
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                >
                  <circle cx="8" cy="8" r="6" />
                </svg>
              )}
              {loading ? "Starting..." : "Start"}
            </button>
          ) : (
            <button
              className="btn btn-stop"
              onClick={handleStop}
              disabled={loading}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="currentColor"
              >
                <rect x="3" y="3" width="10" height="10" rx="1" />
              </svg>
              {loading ? "Stopping..." : "Stop"}
            </button>
          )}

          <button
            className="btn btn-secondary"
            onClick={handleCopy}
            disabled={chunks.length === 0}
            title="Copy transcript to clipboard"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="currentColor"
            >
              <path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1h1a1 1 0 0 1 1 1V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3.5a1 1 0 0 1 1-1h1v-1z" />
              <path d="M9.5 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5h3zm-3-1A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0h-3z" />
            </svg>
            Copy
          </button>
        </div>

        {session && (
          <div className="session-info">
            {session.title || "Active Session"}
          </div>
        )}
      </div>

      <SettingsPanel
        visible={showSettings}
        onClose={() => setShowSettings(false)}
        stealthMode={stealthMode}
        onStealthModeChange={setStealthMode}
      />
    </div>
  );
}

export default App;
