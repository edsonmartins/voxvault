import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import { useCallback, useEffect, useRef } from "react";

export function useNotification() {
  const permissionRef = useRef(false);

  useEffect(() => {
    (async () => {
      let granted = await isPermissionGranted();
      if (!granted) {
        const permission = await requestPermission();
        granted = permission === "granted";
      }
      permissionRef.current = granted;
    })();
  }, []);

  const notify = useCallback((title: string, body?: string) => {
    if (!permissionRef.current) return;
    sendNotification({ title, body });
  }, []);

  return { notify };
}
