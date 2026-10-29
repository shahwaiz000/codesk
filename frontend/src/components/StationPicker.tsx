import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { byRegion, useStation } from "../stations";
import type { Station } from "../types";
import { Icon } from "./icons";

/** Which station the desk looks at: one warehouse, or all of them together. */
export function StationPicker() {
  const { station, stations, choose } = useStation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);

  const active = stations.filter((s) => s.active || s.id === station?.id);
  const totalDrivers = active.reduce((t, s) => t + s.drivers, 0);
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return byRegion(active.filter((s) => !q || [s.name, s.code, s.city, s.region].some((x) => x.toLowerCase().includes(q))));
  }, [active, query]);
  // the rows in the order they show, "All stations" first, for the arrow keys
  const flat: (Station | null)[] = [...(query ? [] : [null]), ...groups.flatMap(([, l]) => l)];

  useEffect(() => {
    if (!open) return;
    setCursor(Math.max(0, flat.findIndex((s) => (s?.id ?? null) === (station?.id ?? null))));
    setTimeout(() => search.current?.focus(), 0);
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setCursor(0); }, [query]);
  useEffect(() => {
    box.current?.querySelector(`[data-row="${cursor}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [cursor]);

  function pick(s: Station | null) {
    choose(s ? s.id : null);
    setOpen(false);
    setQuery("");
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") { setOpen(false); setQuery(""); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(flat.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)); }
    else if (e.key === "Enter" && flat.length) { e.preventDefault(); pick(flat[cursor]); }
  }

  const row = (s: Station | null, i: number) => {
    const chosen = (s?.id ?? null) === (station?.id ?? null);
    const lit = i === cursor;
    return (
      <li key={s?.id ?? "all"} role="option" aria-selected={chosen} data-row={i}
        onMouseEnter={() => setCursor(i)} onClick={() => pick(s)}
        className={`flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${lit ? "bg-white/10" : ""}`}>
        {s ? (
          <span className={`num grid h-7 w-10 shrink-0 place-items-center rounded-md text-[10px] font-bold tracking-wide ${chosen ? "bg-brass-glow text-ledger-950" : "bg-white/[0.07] text-brass-glow"}`}>{s.code}</span>
        ) : (
          <span className={`grid h-7 w-10 shrink-0 place-items-center rounded-md ${chosen ? "bg-brass-glow text-ledger-950" : "bg-white/[0.07] text-brass-glow"}`}><Icon name="dashboard" className="h-3.5 w-3.5" /></span>
        )}
        <span className="min-w-0 flex-1">
          <span className={`block truncate ${chosen ? "font-semibold text-white" : "text-ledger-300"} ${lit ? "text-white" : ""}`}>{s ? s.name : "All stations"}</span>
          {!s && <span className="block text-[11px] text-ledger-300/70">{active.length} stations together</span>}
        </span>
        <span className="num shrink-0 text-[11px] text-ledger-300/70" title="Drivers">{s ? s.drivers || "" : totalDrivers}</span>
        {chosen && <Icon name="check" className="h-4 w-4 shrink-0 text-brass-glow" />}
      </li>
    );
  };

  let i = query ? 0 : 1;
  return (
    <div ref={box} className="relative mx-3 mb-6">
      <button type="button" aria-label="Station" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${open ? "border-brass-glow/50 bg-white/[0.09]" : "border-white/10 bg-white/[0.04] hover:border-brass-glow/40 hover:bg-white/[0.07]"}`}>
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brass-glow to-brass text-ledger-950 shadow-[0_0_0_3px_rgba(226,181,90,.12)]">
          <Icon name={station ? "pin" : "dashboard"} className="h-[18px] w-[18px]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[10px] uppercase tracking-[0.14em] text-ledger-300/80">Station</span>
          <span className="block truncate text-sm font-semibold text-white">{station ? station.name : "All stations"}</span>
          <span className="block truncate text-[11px] text-ledger-300/80">{station ? `${station.code} · ${station.region || "Region not set"}` : `${active.length} stations`}</span>
        </span>
        <svg viewBox="0 0 20 20" className={`h-4 w-4 shrink-0 text-ledger-300 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true">
          <path d="m5 8 5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-2 w-72 max-w-[calc(100vw-2rem)] animate-rise overflow-hidden rounded-xl border border-white/10 bg-ledger-950 shadow-[0_24px_48px_-12px_rgba(0,0,0,.6)]">
          <div className="border-b border-white/[0.07] p-2">
            <label className="relative block">
              <span className="sr-only">Find a station</span>
              <Icon name="search" className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ledger-300/70" />
              <input ref={search} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onKey} placeholder="Find a city or code"
                className="w-full rounded-lg border border-white/10 bg-white/[0.05] py-2 pl-8 pr-3 text-sm text-white placeholder:text-ledger-300/60 focus:border-brass-glow/50 focus:outline-none" />
            </label>
          </div>
          <ul role="listbox" aria-label="Stations" className="max-h-[min(26rem,60vh)] overflow-y-auto p-1.5 [scrollbar-color:rgba(255,255,255,.15)_transparent] [scrollbar-width:thin]">
            {!query && row(null, 0)}
            {groups.map(([region, list]) => (
              <li key={region} role="presentation">
                <p className="flex items-center gap-2 px-2.5 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-brass-glow/80">
                  {region}<span className="h-px flex-1 bg-white/[0.07]" />
                </p>
                <ul role="presentation">{list.map((s) => row(s, i++))}</ul>
              </li>
            ))}
            {groups.length === 0 && <li className="px-3 py-6 text-center text-sm text-ledger-300">No station matches “{query}”</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
