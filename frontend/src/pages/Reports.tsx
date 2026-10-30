import { useState } from "react";
import { todayIso, useBusinessDay } from "../businessDay";
import DayPicker from "../components/DayPicker";
import { Icon } from "../components/icons";
import { ErrorBox, Loading, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, send, useApi, withStation } from "../lib";
import { Trend } from "./Dashboard";
import type { Dashboard as Dash } from "../types";
import type { ReportPreview } from "../types";

function Downloads({ base }: { base: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      <a href={withStation(`${base}&format=xlsx`)} className="btn-primary"><Icon name="download" className="h-4 w-4" />Excel workbook</a>
      <a href={withStation(`${base}&format=pdf`)} className="btn-quiet"><Icon name="download" className="h-4 w-4" />Printable PDF</a>
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

interface Morning {
  today: string; day: string | null; lines: { label: string; value: string; note: string }[]; attention: string[]; due: string[];
  text: string; time: string; folder: string; last: string | null;
}

/** The morning summary: yesterday on one page, to copy into WhatsApp or email, or prepared by itself each morning. */
function MorningSummary() {
  const [version, setVersion] = useState(0);
  const { data, error, loading, reload } = useApi<Morning>(`/morning?v=${version}`);
  const [time, setTime] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const chosen = time ?? data?.time ?? "";

  async function copy() {
    if (!data) return;
    try { await navigator.clipboard.writeText(data.text); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { setProblem("Copy is blocked by the browser: select the text and copy it with Ctrl + C"); }
  }
  async function saveTime(value: string) {
    setProblem(null); setMsg(null);
    try { await send("/morning/settings", "PUT", { time: value }); setTime(null); setVersion((v) => v + 1);
      setMsg(value ? `Every working morning at ${value}, CODesk saves the summary as PDF and text.` : "Turned off."); }
    catch (e) { setProblem((e as Error).message); }
  }
  async function prepare() {
    setProblem(null); setMsg(null);
    try { const r = await send<{ folder: string }>("/morning/prepare", "POST"); setMsg(`Saved in ${r.folder}`); }
    catch (e) { setProblem((e as Error).message); }
  }

  if (loading && !data) return <Panel title="Morning summary"><Loading /></Panel>;
  if (error) return <Panel title="Morning summary"><ErrorBox message={error} retry={reload} /></Panel>;
  if (!data || !Array.isArray(data.lines)) return null;
  return (
    <Panel title="Morning summary" className="xl:col-span-2"
      action={<span className="text-sm text-ink-soft">{data.day ? `For ${fmtDay(data.day)}` : "Nothing recorded yet"}</span>}>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <dl className="divide-y divide-paper-line rounded-lg border border-paper-line">
            {data.lines.map((l) => (
              <div key={l.label} className="flex flex-wrap items-baseline gap-x-3 px-4 py-2.5 text-sm">
                <dt className="w-32 shrink-0 text-ink-soft">{l.label}</dt>
                <dd className="num font-semibold">{l.value}</dd>
                {l.note && <dd className="text-xs text-ink-faint">{l.note}</dd>}
              </div>
            ))}
          </dl>
          {data.due.length > 0 && (
            <div className="mt-4 rounded-lg bg-brass-soft/60 px-4 py-3 text-sm text-brass-dark">
              <p className="font-semibold">To the bank today</p>
              <ul className="mt-1 list-disc pl-5">{data.due.map((d) => <li key={d}>{d}</li>)}</ul>
            </div>
          )}
          <div className="mt-4 text-sm">
            <p className="font-semibold">Needs attention</p>
            {data.attention.length ? <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-soft">{data.attention.map((a) => <li key={a}>{a}</li>)}</ul>
              : <p className="mt-1 text-leaf-dark">Nothing. All clear.</p>}
          </div>
        </div>
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap gap-2">
            <button onClick={copy} className="btn-primary"><Icon name={copied ? "check" : "receipt"} className="h-4 w-4" />{copied ? "Copied" : "Copy text"}</button>
            <a href={withStation("/api/morning/pdf")} className="btn-quiet"><Icon name="download" className="h-4 w-4" />PDF</a>
          </div>
          <p className="text-xs text-ink-faint">Paste the text in WhatsApp or an email to your manager, or attach the PDF.</p>
          <div className="rounded-lg border border-paper-line p-4">
            <p className="text-sm font-medium">Prepare it by itself every morning</p>
            <p className="mt-1 text-xs text-ink-soft">On working days (not Friday) at this time, CODesk saves the PDF and text in
              <span className="block break-all font-mono text-[11px] text-ink">{data.folder}</span></p>
            <form onSubmit={(e) => { e.preventDefault(); saveTime(chosen); }} className="mt-3 flex flex-wrap items-center gap-2">
              <input type="time" aria-label="Time" className="field !mt-0 !w-36" value={chosen} onChange={(e) => setTime(e.target.value)} />
              <button disabled={chosen === (data.time ?? "")} className="btn-primary !py-1.5">Save</button>
              {data.time && <button type="button" onClick={() => saveTime("")} className="btn-quiet !py-1.5">Turn off</button>}
              <button type="button" onClick={prepare} className="btn-quiet !py-1.5">Save files now</button>
            </form>
            {data.last && <p className="mt-2 text-xs text-ink-faint">Last prepared on {fmtDay(data.last, true)}</p>}
            {msg && <p role="status" className="mt-2 rounded-md bg-leaf-soft px-3 py-1.5 text-xs text-leaf-dark">{msg}</p>}
            {problem && <p className="mt-2 text-xs text-short">{problem}</p>}
          </div>
        </div>
      </div>
    </Panel>
  );
}

/** The month-end report for the station being looked at, or for all stations. */
function MonthEnd() {
  const thisMonth = todayIso().slice(0, 7);
  const [month, setMonth] = useState(thisMonth);
  return (
    <Panel title="Month-end report">
      <p className="-mt-2 mb-4 text-sm text-ink-soft">For your manager: the month's money, each cashier's score (on time, short, late, card sheet), the days you checked, and every follow-up raised. For the station chosen at the top, or all stations.</p>
      <div className="flex flex-wrap items-center gap-3">
        <input type="month" className="field mt-0 w-auto" value={month} max={thisMonth} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        <a href={withStation(`/api/supervisor/month-report?month=${month}`)} className="btn-primary"><Icon name="download" className="h-4 w-4" />Month-end PDF</a>
      </div>
    </Panel>
  );
}

/** Cash and card collected per day, the last 30 working days up to the chosen day. */
function DailyTrend() {
  const { day, setDay } = useBusinessDay();
  const data = useApi<Dash>(`/dashboard?date=${day}`).data;
  return data?.trend ? <div className="xl:col-span-2"><Trend data={data.trend} day={day} onPick={setDay} /></div> : null;
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
        <DailyTrend />
        <MorningSummary />
        <MonthEnd />
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
