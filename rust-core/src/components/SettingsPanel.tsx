import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { AppSettings } from "../types";

const API_URL = "http://localhost:8766";

interface SettingsPanelProps {
  visible: boolean;
  onClose: () => void;
  stealthMode: boolean;
  onStealthModeChange: (enabled: boolean) => void;
}

export function SettingsPanel({
  visible,
  onClose,
  stealthMode,
  onStealthModeChange,
}: SettingsPanelProps) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [translationMode, setTranslationMode] = useState("disabled");
  const [targetLanguage, setTargetLanguage] = useState("pt");
  const [saving, setSaving] = useState(false);

  // Load settings on open
  useEffect(() => {
    if (!visible) return;
    fetch(`${API_URL}/api/settings`)
      .then((res) => res.json())
      .then((data: AppSettings) => {
        setSettings(data);
        setTranslationMode(data.translation_mode);
        setTargetLanguage(data.target_language);
      })
      .catch(() => {});
  }, [visible]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await fetch(`${API_URL}/api/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          translation_mode: translationMode,
          target_language: targetLanguage,
        }),
      });
    } catch {
      // Silently fail
    } finally {
      setSaving(false);
    }
  }, [translationMode, targetLanguage]);

  const handleStealthToggle = async () => {
    const newValue = !stealthMode;
    try {
      await invoke("set_stealth_mode", { enabled: newValue });
      onStealthModeChange(newValue);
    } catch {
      // Fallback: update UI anyway
      onStealthModeChange(newValue);
    }
  };

  if (!visible) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h3>Settings</h3>
          <button className="settings-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 12 12" fill="currentColor">
              <path d="M2.22 2.22a.75.75 0 0 1 1.06 0L6 4.94l2.72-2.72a.75.75 0 1 1 1.06 1.06L7.06 6l2.72 2.72a.75.75 0 1 1-1.06 1.06L6 7.06 3.28 9.78a.75.75 0 0 1-1.06-1.06L4.94 6 2.22 3.28a.75.75 0 0 1 0-1.06z" />
            </svg>
          </button>
        </div>

        <div className="settings-body">
          {/* Stealth Mode */}
          <div className="setting-group">
            <label className="setting-label">Stealth Mode</label>
            <p className="setting-desc">
              Hide VoxVault during screen sharing
            </p>
            <label className="toggle">
              <input
                type="checkbox"
                checked={stealthMode}
                onChange={handleStealthToggle}
              />
              <span className="toggle-slider" />
            </label>
          </div>

          {/* Translation Mode */}
          <div className="setting-group">
            <label className="setting-label">Translation</label>
            <select
              className="setting-select"
              value={translationMode}
              onChange={(e) => setTranslationMode(e.target.value)}
            >
              <option value="disabled">Disabled</option>
              <option value="openrouter">OpenRouter</option>
              <option value="claude">Claude (Haiku)</option>
              <option value="openai">OpenAI (GPT-4o-mini)</option>
              <option value="local">Local (MLX Gemma 3)</option>
            </select>
          </div>

          {/* Target Language */}
          <div className="setting-group">
            <label className="setting-label">Target Language</label>
            <select
              className="setting-select"
              value={targetLanguage}
              onChange={(e) => setTargetLanguage(e.target.value)}
            >
              <option value="pt">Portuguese</option>
              <option value="en">English</option>
              <option value="es">Spanish</option>
              <option value="fr">French</option>
              <option value="de">German</option>
              <option value="ja">Japanese</option>
              <option value="zh">Chinese</option>
            </select>
          </div>

          {/* API Status */}
          {settings && (
            <div className="setting-group">
              <label className="setting-label">API Keys</label>
              <div className="api-status">
                <span className={settings.openrouter_api_key_set ? "key-set" : "key-missing"}>
                  OpenRouter: {settings.openrouter_api_key_set ? "Configured" : "Not set"}
                </span>
                <span className={settings.anthropic_api_key_set ? "key-set" : "key-missing"}>
                  Anthropic: {settings.anthropic_api_key_set ? "Configured" : "Not set"}
                </span>
                <span className={settings.openai_api_key_set ? "key-set" : "key-missing"}>
                  OpenAI: {settings.openai_api_key_set ? "Configured" : "Not set"}
                </span>
              </div>
              {settings.openrouter_api_key_set && (
                <p className="setting-desc" style={{ marginTop: 4 }}>
                  Model: {settings.openrouter_model}
                </p>
              )}
            </div>
          )}

          <button
            className="btn btn-primary settings-save"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save Settings"}
          </button>
        </div>
      </div>
    </div>
  );
}
