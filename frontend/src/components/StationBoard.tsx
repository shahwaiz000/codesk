import { useMemo, useState } from "react";
import { fmtDay, fmtMoney, useApi } from "../lib";
import { useStation } from "../stations";
import type { StationDay, StationOverview } from "../types";
import { Money, Panel } from "./ui";

/* The Kingdom's regions as a tile map: each tile sits roughly where the region is, north at the top. */
const TILES: { region: string; short: string; area: string }[] = [
  { region: "Al Jouf", short: "Al Jouf", area: "1 / 2 / 2 / 3" },
  { region: "Northern Borders", short: "Northern Borders", area: "1 / 3 / 2 / 4" },
  { region: "Tabuk", short: "Tabuk", area: "2 / 1 / 3 / 2" },
  { region: "Hail", short: "Hail", area: "2 / 2 / 3 / 3" },
  { region: "Qassim", short: "Qassim", area: "2 / 3 / 3 / 4" },
  { region: "Eastern Province", short: "Eastern", area: "2 / 4 / 5 / 5" },
  { region: "Madinah", short: "Madinah", area: "3 / 1 / 4 / 3" },
  { region: "Riyadh", short: "Riyadh", area: "3 / 3 / 5 / 4" },
  { region: "Makkah", short: "Makkah", area: "4 / 1 / 5 / 2" },
  { region: "Al Baha", short: "Al Baha", area: "4 / 2 / 5 / 3" },
  { region: "Jazan", short: "Jazan", area: "5 / 1 / 6 / 2" },
  { region: "Asir", short: "Asir", area: "5 / 2 / 6 / 3" },
  { region: "Najran", short: "Najran", area: "5 / 3 / 6 / 5" },
];

type Mood = "late" | "holding" | "clear" | "quiet";
const MOOD: Record<Mood, { tile: string; dot: string; text: string }> = {
  late: { tile: "bg-short text-white ring-short-dark/30", dot: "bg-white", text: "Deposit late" },
  holding: { tile: "bg-brass-glow/90 text-ledger-950 ring-brass/40", dot: "bg-ledger-950", text: "Cash waiting for the bank" },
  clear: { tile: "bg-leaf text-white ring-leaf-dark/30", dot: "bg-white", text: "Collected and deposited" },
  quiet: { tile: "bg-white/[0.06] text-ledger-300 ring-white/10", dot: "bg-white/20", text: "No cash on this day" },
};
const mood = (s: { late_amount: number; cash_on_hand: number; cash_received: number }): Mood =>
  s.late_amount > 0 ? "late" : s.cash_on_hand > 0 ? "holding" : s.cash_received > 0 ? "clear" : "quiet";

const compact = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}K` : fmtMoney(n);

function sum(list: StationDay[], k: "cash_received" | "cash_on_hand" | "late_amount") {
  return Math.round(list.reduce((t, s) => t + s[k], 0) * 100) / 100;
}

export default function StationBoard({ day }: { day: string }) {
  const { data } = useApi<StationOverview>(`/stations/overview?date=${day}`);
  const { stations } = useStation();
  const [region, setRegion] = useState<string | null>(null);
  const rows = Array.isArray(data?.stations) ? data!.stations : [];

  const regions = useMemo(() => {
    const out = new Map<string, { list: StationDay[]; all: number }>();
    for (const s of stations) if (s.active) {
      const key = s.region || "Other";
      out.set(key, { list: out.get(key)?.list ?? [], all: (out.get(key)?.all ?? 0) + 1 });
    }
    for (const s of rows) {
      const key = s.region || "Other";
      const g = out.get(key) ?? { list: [], all: 0 };
      out.set(key, { ...g, list: [...g.list, s] });
    }
    return out;
  }, [stations, rows]);

  if (!data || !stations.length) return null;
  const t = data.totals;
  const others = [...regions.keys()].filter((r) => !TILES.some((x) => x.region === r));

  return (
    <Panel flush className="mb-6" title={`Map of the stations on ${fmtDay(day)}`}
      action={<span className="text-xs text-ink-faint">{rows.filter((r) => r.cash_received > 0).length} of {data.active_stations} stations with cash</span>}>
      <div className="grid gap-6 p-5 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div>
          <div className="relative overflow-hidden rounded-xl bg-ledger-900 p-3">
            <svg viewBox="0 0 100 100" className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.07]" aria-hidden="true">
              {Array.from({ length: 11 }, (_, i) => <path key={i} d={`M0 ${i * 10}H100M${i * 10} 0V100`} stroke="#fff" strokeWidth=".3" />)}
            </svg>
            <p className="relative mb-2 flex items-center justify-between text-[11px] uppercase tracking-wider text-ledger-300">
              <span>Saudi Arabia, by region</span><span aria-hidden="true">N ↑</span>
            </p>
            <div className="relative grid aspect-[4/5] grid-cols-4 grid-rows-5 gap-1.5">
              {TILES.map((tile) => {
                const g = regions.get(tile.region);
                const list = g?.list ?? [];
                const m = mood({ late_amount: sum(list, "late_amount"), cash_on_hand: sum(list, "cash_on_hand"), cash_received: sum(list, "cash_received") });
                const picked = region === tile.region;
                return (
                  <button key={tile.region} type="button" style={{ gridArea: tile.area }}
                    onClick={() => setRegion(picked ? null : tile.region)} aria-pressed={picked}
                    title={`${tile.region}: ${MOOD[m].text}`}
                    className={`group relative flex min-w-0 flex-col justify-between overflow-hidden rounded-lg p-2 text-left ring-1 transition duration-200 hover:-translate-y-0.5 hover:shadow-pop ${MOOD[m].tile} ${picked ? "outline outline-2 outline-offset-2 outline-brass-glow" : ""}`}>
                    <span className="flex items-start justify-between gap-1">
                      <span className="truncate text-[11px] font-semibold leading-tight">{tile.short}</span>
                      {m !== "quiet" && <span className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${MOOD[m].dot} ${m === "late" ? "animate-pulse" : ""}`} />}
                    </span>
                    <span>
                      {list.length > 0 && <span className="num block truncate text-[13px] font-bold leading-tight">{compact(sum(list, "cash_received"))}</span>}
                      <span className="block text-[10px] opacity-80">{list.length}/{g?.all ?? 0}<span className="hidden sm:inline"> stations</span></span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <ul className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-soft">
            {(["late", "holding", "clear", "quiet"] as Mood[]).map((m) => (
              <li key={m} className="flex items-center gap-1.5"><span className={`h-2.5 w-2.5 rounded-sm ring-1 ${m === "quiet" ? "bg-ledger-900 ring-ledger-700" : MOOD[m].tile}`} />{MOOD[m].text}</li>
            ))}
          </ul>
          {others.length > 0 && <p className="mt-2 text-xs text-ink-faint">Also: {others.map((o) => (
            <button key={o} onClick={() => setRegion(region === o ? null : o)} className="mr-2 underline underline-offset-2">{o}</button>))}</p>}
        </div>

        <div className="min-w-0">
          <dl className="mb-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
            <div className="rounded-lg bg-paper p-3"><dt className="text-xs text-ink-faint">Cash collected</dt><dd className="text-lg font-semibold"><Money value={t.cash_received} /></dd></div>
            <div className="rounded-lg bg-paper p-3"><dt className="text-xs text-ink-faint">Cash on hand, all days</dt><dd className="text-lg font-semibold"><Money value={t.cash_on_hand} tone={t.cash_on_hand ? "brass" : undefined} /></dd></div>
            <div className={`rounded-lg p-3 ${t.late_amount ? "bg-short-soft" : "bg-leaf-soft"}`}><dt className="text-xs text-ink-faint">Late deposits</dt>
              <dd className="text-lg font-semibold">{t.late_amount ? <Money value={t.late_amount} tone="short" /> : <span className="text-leaf-dark">None</span>}</dd></div>
          </dl>
          <p className="text-sm text-ink-soft">Each region takes the colour of its most urgent station. The list above says who to call and why.</p>
        </div>
      </div>
    </Panel>
  );
}
