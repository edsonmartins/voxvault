import { useCallback, useEffect, useRef, useState } from "react";
import { TitleBar } from "./components/TitleBar";
import { StatusBar } from "./components/StatusBar";
import { TranscriptView } from "./components/TranscriptView";
import { SettingsPanel } from "./components/SettingsPanel";
import { useTranscript } from "./hooks/useTranscript";
import { useSession } from "./hooks/useSession";
import { useNotification } from "./hooks/useNotification";

function App() {
  const {
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
  } = useTranscript();
  const { session, isActive, loading, error, startSession, stopSession } =
    useSession();

  const { notify } = useNotification();
  const [showSettings, setShowSettings] = useState(false);
  const [stealthMode, setStealthMode] = useState(true);
  const [targetLang, setTargetLang] = useState("pt");
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
    clearTranscript();
    startSession();
    notify("VoxVault", "Session started — transcribing...");
  }, [clearTranscript, startSession, notify]);

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

  // Sync target language with Python API
  const handleLangChange = useCallback(
    async (lang: string) => {
      setTargetLang(lang);
      try {
        await fetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_language: lang }),
        });
      } catch {
        // Silently fail if API is down
      }
    },
    []
  );

  // Load initial target language from API
  useEffect(() => {
    fetch("/api/settings")
      .then((res) => res.json())
      .then((data) => {
        if (data.target_language) setTargetLang(data.target_language);
      })
      .catch(() => {});
  }, []);

  const handleCopy = useCallback(() => {
    const text = getFullText();
    if (text) {
      navigator.clipboard.writeText(text);
    }
  }, [getFullText]);

  const detectedLang = sourceLang;

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

      <TranscriptView
        finalText={finalText}
        partial={partial}
        translatedText={translatedText}
        hasTranslation={hasTranslation}
        targetLang={targetLang}
      />

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
            disabled={!hasContent}
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

        <div className="action-row">
          <div className="lang-selector">
            <label className="lang-label">Output:</label>
            <select
              className="lang-select"
              value={targetLang}
              onChange={(e) => handleLangChange(e.target.value)}
            >
              <option value="pt">PT</option>
              <option value="en">EN</option>
              <option value="es">ES</option>
              <option value="fr">FR</option>
              <option value="de">DE</option>
              <option value="ja">JA</option>
              <option value="zh">ZH</option>
              <option value="ko">KO</option>
              <option value="it">IT</option>
            </select>
          </div>

          {session && (
            <div className="session-info">
              {session.title || "Active Session"}
            </div>
          )}
        </div>
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
