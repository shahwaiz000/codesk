import { useCallback, useEffect, useRef, useState } from "react";

/** Sent when the server says the login has ended, so the app can show the login page. */
export const AUTH_LOST = "codesk-auth-lost";

/* The station being looked at ("" = all stations). It is sent with every request, so the backend shows
   and saves only that station's money; it is kept in this browser so the desk opens where it was left. */
const STATION_KEY = "codesk-station";
let station = (() => { try { return localStorage.getItem(STATION_KEY) ?? ""; } catch { return ""; } })();
export const currentStation = () => station;
export function rememberStation(id: string) {
  station = id;
  try { if (id) localStorage.setItem(STATION_KEY, id); else localStorage.removeItem(STATION_KEY); } catch { /* private window */ }
}
const stationHeader = (): Record<string, string> => (station ? { "X-Station": station } : {});
/** A download link (PDF, Excel) for the station being looked at. */
export const withStation = (url: string) => (station ? `${url}${url.includes("?") ? "&" : "?"}station=${station}` : url);

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers: { "Content-Type": "application/json", ...stationHeader(), ...(init?.headers ?? {}) } });
  } catch {
    throw new Error("Cannot reach the backend. Check that it is running on port 8000.");
  }
  const body = await res.json().catch(() => null);
  if (res.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new Event(AUTH_LOST));
  if (!res.ok) throw new Error(body?.error?.message ?? `Request failed (${res.status})`);
  return body as T;
}

/** Sent after anything is saved, so figures elsewhere on the screen can reload. */
export const CHANGED = "codesk-changed";
const changed = () => window.dispatchEvent(new Event(CHANGED));

export const send = <T,>(path: string, method: string, body?: unknown) =>
  api<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) }).then((r) => { changed(); return r; });

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);
  const load = useCallback(() => {
    if (!path) return;
    const ticket = ++latest.current; // only the newest request may update the screen
    setLoading(true);
    api<T>(path).then((d) => { if (ticket === latest.current) { setData(d); setError(null); } })
      .catch((e: Error) => { if (ticket === latest.current) setError(e.message); })
      .finally(() => { if (ticket === latest.current) setLoading(false); });
  }, [path]);
  useEffect(load, [load]);
  return { data, error, loading, reload: load };
}

const money = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** 1234.5 -> "1,234.50". Negative numbers keep their minus sign. */
export const fmtMoney = (n: number | null | undefined) => (n == null ? "-" : money.format(n));

/** "2026-10-26" -> "Mon 26 Oct". Dates are business days, so no time zone shifting. */
export function fmtDay(isoDate: string | null | undefined, withYear = false): string {
  if (!isoDate) return "-";
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}), timeZone: "UTC" });
}

export function fmtWhen(isoTime: string | null | undefined): string {
  if (!isoTime) return "-";
  return new Date(isoTime).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Send a form with a file. Same error handling as api(). */
export async function upload<T>(path: string, form: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: "POST", body: form, headers: stationHeader() });
  } catch {
    throw new Error("Cannot reach the backend. Check that it is running on port 8000.");
  }
  const body = await res.json().catch(() => null);
  if (res.status === 401) window.dispatchEvent(new Event(AUTH_LOST));
  if (!res.ok) throw new Error(body?.error?.message ?? `Upload failed (${res.status})`);
  changed();
  return body as T;
}

/** "1,234.50" or "SAR 99" -> number, or null when it is not a number yet (while typing). */
export function parseAmount(text: string): number | null {
  const t = text.replace(/sar|,|\s/gi, "");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}
