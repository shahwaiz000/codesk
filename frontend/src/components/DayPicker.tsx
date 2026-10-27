import { useMemo } from "react";
import { shiftWorkingDay, useBusinessDay } from "../businessDay";
import { fmtDay, useApi } from "../lib";
import { Icon } from "./icons";

export interface DaySummary { date: string; drivers: number; cash_received: number; pos_amount: number; difference: number; short: number }

/** The business date control: step back and forward by working day, pick any date, or jump
 *  along the last seven working days. A red mark means a driver was short that day. */
export default function DayPicker({ refreshKey = 0 }: { refreshKey?: number }) {
  const { day, setDay, today } = useBusinessDay();
  const recent = useApi<DaySummary[]>(`/collections/days?end=${today}&count=12&r=${refreshKey}`);
  const strip = useMemo(() => {
    const out: string[] = [];
    let d = today;
    if (new Date(`${d}T00:00:00Z`).getUTCDay() === 5) d = shiftWorkingDay(d, -1);
    while (out.length < 7) { out.push(d); d = shiftWorkingDay(d, -1); }
    return out.reverse();
  }, [today]);
  const byDate = new Map((recent.data ?? []).map((r) => [r.date, r]));
  const next = shiftWorkingDay(day, 1);

  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-3">
      <div className="flex items-stretch overflow-hidden rounded-lg border border-paper-line bg-white shadow-panel">
        <button onClick={() => setDay(shiftWorkingDay(day, -1))} aria-label="Previous working day"
          className="px-2.5 text-ink-soft hover:bg-paper-deep hover:text-ink"><Icon name="chevronLeft" className="h-4 w-4" /></button>
        <label className="relative flex cursor-pointer items-center gap-2.5 border-x border-paper-line px-4 py-2">
          <Icon name="calendar" className="h-4 w-4 text-brass" />
          <span className="text-sm font-semibold text-ink">{fmtDay(day, true)}</span>
          {day === today && <span className="rounded bg-brass-soft px-1.5 py-px text-[11px] font-medium text-brass-dark">Today</span>}
          <input type="date" aria-label="Business date" value={day} max={today}
            onChange={(e) => e.target.value && setDay(e.target.value)}
            className="absolute inset-0 cursor-pointer opacity-0" />
        </label>
        <button onClick={() => setDay(next)} disabled={next > today} aria-label="Next working day"
          className="px-2.5 text-ink-soft hover:bg-paper-deep hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent"><Icon name="chevronRight" className="h-4 w-4" /></button>
      </div>

      <ol className="flex min-w-0 max-w-full gap-1 overflow-x-auto" aria-label="Last seven working days">
        {strip.map((d) => {
          const s = byDate.get(d);
          const selected = d === day;
          return (
            <li key={d}>
              <button onClick={() => setDay(d)} aria-current={selected ? "date" : undefined}
                title={s ? `${s.drivers} handovers${s.short ? `, ${s.short.toFixed(2)} SAR short` : ""}` : "No handovers recorded"}
                className={`relative flex w-12 flex-col items-center rounded-lg py-1.5 text-xs transition-colors ${selected ? "bg-ledger-900 text-white" : "text-ink-soft hover:bg-white"}`}>
                <span className={selected ? "text-ledger-300" : "text-ink-faint"}>{fmtDay(d).split(" ")[0]}</span>
                <span className="num text-sm font-semibold">{Number(d.slice(8))}</span>
                <span aria-hidden="true" className={`mt-0.5 h-1 w-1 rounded-full ${!s ? "bg-transparent" : s.short ? "bg-short" : selected ? "bg-brass-glow" : "bg-leaf"}`} />
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
