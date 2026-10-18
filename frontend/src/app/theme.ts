import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";
const storageKey = "harbor-helper.theme";
function readTheme(): Theme {
  try {
    return localStorage.getItem(storageKey) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}
// Independent of the early script: a failed request must not strand a saved theme.
let theme = readTheme();
document.documentElement.dataset.theme = theme;
const listeners = new Set<() => void>();
function applyTheme(next: Theme) {
  theme = next;
  document.documentElement.dataset.theme = next;
  listeners.forEach((listener) => listener());
}
window.addEventListener("storage", (event) => {
  if (event.key === storageKey || event.key === null) {
    // Read the current value, avoiding stale queued events from rapid toggles.
    applyTheme(readTheme());
  }
});
export function setTheme(next: Theme) {
  try {
    localStorage.setItem(storageKey, next);
  } catch {
    // Still usable for this page when browser storage is unavailable or full.
  }
  applyTheme(next);
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function useTheme() {
  return useSyncExternalStore(subscribe, () => theme);
}
