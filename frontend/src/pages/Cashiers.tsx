import { useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../components/icons";
import { Empty, ErrorBox, Loading, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, useApi, withStation } from "../lib";
import { useStation } from "../stations";

type Row = {
  station_id: number; station: string; station_code: string; region: string; cashier_name: string; cashier_phone: string;
  days: number; cash: number; deposited: number; on_time: number; short_days: number; short_amount: number; late_days: number;
  card_days: number; card_amount: number; checked_days: number; follow_ups: number; open_follow_ups: number;
  score: number | null; grade: "good" | "watch" | "poor" | null;
};
const GRADE = {
  good: { text: "Good", cls: "bg-leaf text-white" }, watch: { text: "Watch", cls: "bg-brass-glow text-ledger-950" }, poor: { text: "Needs training", cls: "bg-short text-white" },
};
const thisMonth = () => new Date().toISOString().slice(0, 7);

/** Each station's cashier, graded on the month: deposits on time, short or late, card sheets that do not match. */
export default function Cashiers() {
  const [month, setMonth] = useState(thisMonth());
  const { choose } = useStation();
  const { data, error, loading, reload } = useApi<{ month: string; start: string; end: string; rows: Row[] }>(`/supervisor/scorecard?month=${month}`);
  const rows = Array.isArray(data?.rows) ? data!.rows : [];
  return (
    <>
      <PageHeader title="Cashier performance" subtitle="Each station's cashier, graded on the month. The score is the share of days whose cash reached the bank in full and on time.">
        <label className="flex items-center gap-2 text-sm text-ink-soft">Month
          <input type="month" className="field mt-0 w-auto" value={month} max={thisMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} /></label>
        <a href={withStation(`/api/supervisor/month-report?month=${month}`)} className="btn-quiet"><Icon name="download" className="h-4 w-4" />Month-end PDF</a>
      </PageHeader>
      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : rows.length === 0 ? (
        <Empty title="No cashier data for this month" hint="Import a station's files, or add the cashier's name on the Stations page." />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {rows.map((r) => (
              <div key={r.station_id} className="rounded-panel bg-white p-5 shadow-panel">
                <div className="flex items-start gap-3">
                  <div className={`grid h-14 w-14 shrink-0 place-items-center rounded-full text-lg font-bold ${r.grade ? GRADE[r.grade].cls : "bg-paper text-ink-faint"}`}>
                    {r.score === null ? "–" : `${r.score}%`}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{r.cashier_name || <span className="text-ink-faint">Cashier not named</span>}</p>
                    <p className="truncate text-sm text-ink-soft">{r.station} · {r.station_code}</p>
                    {r.grade && <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${GRADE[r.grade].cls}`}>{GRADE[r.grade].text}</span>}
                  </div>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                  <dt className="text-ink-soft">Days with cash</dt><dd className="num text-right">{r.days}</dd>
                  <dt className="text-ink-soft">Deposited on time</dt><dd className="num text-right text-leaf-dark">{r.on_time}</dd>
                  <dt className="text-ink-soft">Deposited short</dt><dd className={`num text-right ${r.short_days ? "text-short" : ""}`}>{r.short_days}{r.short_amount > 0 && <span className="text-xs"> ({<Money value={r.short_amount} tone="short" />} open)</span>}</dd>
                  <dt className="text-ink-soft">Deposited late</dt><dd className={`num text-right ${r.late_days ? "text-short" : ""}`}>{r.late_days}</dd>
                  <dt className="text-ink-soft">Card sheet not matching</dt><dd className={`num text-right ${r.card_days ? "text-brass-dark" : ""}`}>{r.card_days}</dd>
                  <dt className="text-ink-soft">Days you checked</dt><dd className="num text-right">{r.checked_days} of {r.days}</dd>
                  <dt className="text-ink-soft">Follow-ups</dt><dd className={`num text-right ${r.open_follow_ups ? "text-short" : ""}`}>{r.follow_ups}{r.open_follow_ups ? ` (${r.open_follow_ups} open)` : ""}</dd>
                </dl>
                <div className="mt-4 flex gap-2 border-t border-paper-line pt-3">
                  <Link to="/station" onClick={() => choose(r.station_id)} className="btn-quiet px-3 py-1.5 text-xs">Open station</Link>
                  <a href={withStation(`/api/supervisor/month-report?month=${month}&station=${r.station_id}`)} className="btn-quiet px-3 py-1.5 text-xs"><Icon name="download" className="h-3.5 w-3.5" />PDF</a>
                </div>
              </div>
            ))}
          </div>
          {data && <p className="text-xs text-ink-faint">{fmtDay(data.start, true)} to {fmtDay(data.end, true)}. A day counts once its deposit was due: today's cash is not graded yet.</p>}
        </>
      )}
    </>
  );
}
