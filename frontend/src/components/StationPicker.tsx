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
    return (
      <li key={s?.id ?? "all"} role="option" aria-selected={chosen} data-row={i}
        onMouseEnter={() => setCursor(i)} onClick={() => pick(s)}
        className={`flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-sm ${i === cursor ? "bg-white/10 text-white" : "text-ledger-300"} ${chosen ? "font-semibold text-white" : ""}`}>
        <span className="min-w-0 flex-1 truncate">{s ? s.name : "All stations"}</span>
        {s && <span className="text-xs text-ledger-300/60">{s.code}</span>}
        {chosen && <Icon name="check" className="h-4 w-4 shrink-0" />}
      </li>
    );
  };

  let i = query ? 0 : 1;
  return (
    <div ref={box} className="relative mx-3 mb-6">
      <button type="button" aria-label="Station" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-left hover:bg-white/[0.05]">
        <Icon name="pin" className="h-4 w-4 shrink-0 text-ledger-300" />
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] text-ledger-300/80">Station</span>
          <span className="block truncate text-sm font-medium text-white">{station ? station.name : "All stations"}</span>
        </span>
        <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-ledger-300" aria-hidden="true">
          <path d="m5 8 5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-lg border border-white/10 bg-ledger-950 shadow-pop">
          <div className="border-b border-white/[0.07] p-2">
            <label className="relative block">
              <span className="sr-only">Find a station</span>
              <Icon name="search" className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ledger-300/70" />
              <input ref={search} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onKey} placeholder="Find a city or code"
                className="w-full rounded-md border border-white/10 bg-transparent py-1.5 pl-8 pr-2 text-sm text-white placeholder:text-ledger-300/60 focus:border-white/30 focus:outline-none" />
            </label>
          </div>
          <ul role="listbox" aria-label="Stations" className="max-h-[min(22rem,60vh)] overflow-y-auto p-1.5 [scrollbar-color:rgba(255,255,255,.15)_transparent] [scrollbar-width:thin]">
            {!query && row(null, 0)}
            {groups.map(([region, list]) => (
              <li key={region} role="presentation">
                <p className="px-2.5 pb-0.5 pt-2.5 text-[11px] text-ledger-300/60">{region}</p>
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
