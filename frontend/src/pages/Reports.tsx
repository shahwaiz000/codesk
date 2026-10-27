import { useState } from "react";
import { todayIso, useBusinessDay } from "../businessDay";
import DayPicker from "../components/DayPicker";
import { Icon } from "../components/icons";
import { ErrorBox, Loading, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, useApi } from "../lib";
import type { ReportPreview } from "../types";

function Downloads({ base }: { base: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      <a href={`${base}&format=xlsx`} className="btn-primary"><Icon name="download" className="h-4 w-4" />Excel workbook</a>
      <a href={`${base}&format=pdf`} className="btn-quiet"><Icon name="download" className="h-4 w-4" />Printable PDF</a>
    </div>
  );
}

function Preview({ start, end }: { start: string; end: string }) {
  const { data, error, loading, reload } = useApi<ReportPreview>(`/reports/preview?start=${start}&end=${end}`);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error} retry={reload} />;
  if (!data) return null;
  if (!data.days) return <p className="rounded-lg bg-paper px-4 py-3 text-sm text-ink-soft">No handovers or deposits are recorded in this period, so the report would be empty.</p>;
  const t = data.totals;
  const issues = [
    data.cash_differences && `${data.cash_differences} cash ${data.cash_differences === 1 ? "difference" : "differences"}`,
    data.pos_differences && `${data.pos_differences} POS ${data.pos_differences === 1 ? "difference" : "differences"}`,
    data.pending_days && `${data.pending_days} ${data.pending_days === 1 ? "day" : "days"} with cash pending`,
    data.open_advances && `${data.open_advances} open ${data.open_advances === 1 ? "advance" : "advances"}`,
  ].filter(Boolean);
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg bg-paper p-4 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-ink-faint">Cash received</dt><dd><Money value={t.cash_received} className="font-semibold" /></dd></div>
        <div><dt className="text-xs text-ink-faint">POS (terminals)</dt><dd><Money value={t.pos_terminal} className="font-semibold" /></dd></div>
        <div><dt className="text-xs text-ink-faint">To deposit</dt><dd><Money value={t.to_deposit} className="font-semibold" /></dd></div>
        <div><dt className="text-xs text-ink-faint">Still pending</dt><dd><Money value={t.pending} tone={t.pending > 0 ? "short" : "leaf"} className="font-semibold" /></dd></div>
      </dl>
      <p className="text-sm text-ink-soft">
        {data.days} {data.days === 1 ? "business day" : "business days"}, {data.handovers} handovers, {data.expenses} payouts and {data.slips} deposit slips.
        {issues.length ? <> The report lists <span className="font-medium text-ink">{issues.join(", ")}</span>.</> : " Nothing open."}
      </p>
    </div>
  );
}

function workingDaysBack(end: string, n: number) {
  const d = new Date(`${end}T00:00:00Z`);
  let left = n - 1;
  while (left > 0) { d.setUTCDate(d.getUTCDate() - 1); if (d.getUTCDay() !== 5) left--; }
  return d.toISOString().slice(0, 10);
}

export default function Reports() {
  const { day } = useBusinessDay();
  const today = todayIso();
  const [start, setStart] = useState(() => `${today.slice(0, 8)}01`);
  const [end, setEnd] = useState(today);
  const monthStart = `${today.slice(0, 8)}01`;
  const lastMonthEnd = new Date(Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)) - 1, 0)).toISOString().slice(0, 10);
  const presets: [string, string, string][] = [
    ["Last 7 working days", workingDaysBack(today, 7), today],
    ["This month", monthStart, today],
    ["Last month", `${lastMonthEnd.slice(0, 8)}01`, lastMonthEnd],
  ];
  const valid = start && end && start <= end;

  return (
    <>
      <PageHeader title="Reports" subtitle="Download the finance report for one business day or for a period. Excel has a sheet per area with working totals; the PDF is ready to print and sign." />
      <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
        <Panel title="Daily finance report">
          <p className="-mt-2 mb-4 text-sm text-ink-soft">One page: key figures, every driver's cash handover, POS differences with their reviews, expenses, deposit slips, open items and sign-off lines.</p>
          <DayPicker />
          <div className="-mt-2 space-y-4">
            <Preview start={day} end={day} />
            <Downloads base={`/api/reports/day?date=${day}`} />
          </div>
        </Panel>

        <Panel title="Period report">
          <p className="-mt-2 mb-4 text-sm text-ink-soft">A line per business day with cash, POS and deposit status, then every expense and slip in the period, and what is still open at the end.</p>
          <div className="mb-4 flex flex-wrap gap-2">
            {presets.map(([label, s, e]) => (
              <button key={label} onClick={() => { setStart(s); setEnd(e); }}
                className={`rounded-full border px-3 py-1 text-sm ${start === s && end === e ? "border-ledger-900 bg-ledger-900 text-white" : "border-paper-line bg-white text-ink-soft hover:bg-paper-deep"}`}>{label}</button>
            ))}
          </div>
          <div className="mb-4 grid grid-cols-2 gap-3">
            <label className="block text-sm font-medium">From<input type="date" className="field" value={start} max={today} onChange={(e) => setStart(e.target.value)} /></label>
            <label className="block text-sm font-medium">To<input type="date" className="field" value={end} max={today} onChange={(e) => setEnd(e.target.value)} /></label>
          </div>
          {valid ? (
            <div className="space-y-4">
              <p className="text-sm font-medium">{fmtDay(start, true)} to {fmtDay(end, true)}</p>
              <Preview start={start} end={end} />
              <Downloads base={`/api/reports/range?start=${start}&end=${end}`} />
            </div>
          ) : <p className="text-sm text-short-dark">Choose a start date on or before the end date.</p>}
        </Panel>
      </div>
    </>
  );
}
