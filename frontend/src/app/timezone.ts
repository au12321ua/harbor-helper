import { useSyncExternalStore } from "react";

const key = "harbor-helper.timezone";
export const browserZone =
  Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
export function validZone(value: string) {
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return /[A-Za-z]/.test(value);
  } catch {
    return false;
  }
}
function read() {
  try {
    const value = localStorage.getItem(key);
    return value && validZone(value) ? value : "browser";
  } catch {
    return "browser";
  }
}
let preference = read();
const listeners = new Set<() => void>();
function apply(value: string) {
  preference = value;
  listeners.forEach((fn) => fn());
}
window.addEventListener("storage", (e) => {
  if (e.key === key || e.key === null) apply(read());
});
export function setTimezone(value: string) {
  if (value !== "browser" && !validZone(value))
    throw new Error("请输入合法的 IANA 时区，例如 Asia/Shanghai");
  try {
    localStorage.setItem(key, value);
  } catch {
    /* In-memory preference remains usable. */
  }
  apply(value);
}
export function useTimezone() {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    () => preference,
  );
}
export function timezone() {
  return preference === "browser" ? browserZone : preference;
}
export function formatTime(
  value: unknown,
  options: Intl.DateTimeFormatOptions = {},
) {
  if (value === null || value === undefined || value === "") return "—";
  const instant = new Date(
    typeof value === "number" ? value * 1000 : String(value),
  );
  if (!Number.isFinite(instant.getTime())) return "—";
  return instant.toLocaleString("zh-CN", {
    timeZone: timezone(),
    hour12: false,
    ...options,
  });
}
export function localTime(epoch: number, zone = timezone()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(epoch * 1000));
  const p = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}
// Enumerate offsets on both sides of a local day, then round-trip each candidate.
// This rejects gaps and returns both instants in a daylight-saving overlap.
export function localCandidates(value: string, zone = timezone()): number[] {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(value)) return [];
  const wall = Date.parse(`${value}:00Z`) / 1000;
  if (!Number.isFinite(wall)) return [];
  const offsets = new Set<number>();
  for (let hours = -48; hours <= 48; hours += 6) {
    const instant = wall + hours * 3600;
    offsets.add(Date.parse(`${localTime(instant, zone)}:00Z`) / 1000 - instant);
  }
  return [...offsets]
    .map((offset) => wall - offset)
    .filter((epoch) => localTime(epoch, zone) === value)
    .sort((a, b) => a - b);
}
export function offsetLabel(epoch: number, zone = timezone()) {
  return new Intl.DateTimeFormat("en", {
    timeZone: zone,
    timeZoneName: "longOffset",
  }).format(new Date(epoch * 1000));
}
