interface StatusBarProps {
  connected: boolean;
  isRecording: boolean;
  language: string;
  duration: number;
  statusText: string;
  rtf: number | null;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function rtfLabel(rtf: number): { text: string; className: string } {
  if (rtf < 0.5) return { text: "Fast", className: "rtf-fast" };
  if (rtf <= 1.0) return { text: "Normal", className: "rtf-normal" };
  return { text: "Slow", className: "rtf-slow" };
}

export function StatusBar({
  connected,
  isRecording,
  language,
  duration,
  statusText,
  rtf,
}: StatusBarProps) {
  return (
    <div className="status-bar">
      <div className="status-left">
        <span className={`status-dot ${connected ? "connected" : "disconnected"}`} />
        <span className="status-label">
          {connected ? "Connected" : "Disconnected"}
        </span>
      </div>

      {isRecording && (
        <div className="status-center">
          <span className="recording-indicator" />
          <span className="status-lang">{language.toUpperCase()}</span>
          <span className="status-duration">{formatDuration(duration)}</span>
          {rtf !== null && (
            <span className={`status-rtf ${rtfLabel(rtf).className}`}>
              {rtfLabel(rtf).text}
            </span>
          )}
        </div>
      )}

      {statusText && (
        <div className="status-right">
          <span className="status-text">{statusText}</span>
        </div>
      )}
    </div>
  );
}
