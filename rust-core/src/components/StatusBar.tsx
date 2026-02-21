interface StatusBarProps {
  connected: boolean;
  isRecording: boolean;
  language: string;
  duration: number;
  statusText: string;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function StatusBar({
  connected,
  isRecording,
  language,
  duration,
  statusText,
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
