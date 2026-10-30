import { Link } from "react-router-dom";
import { fmtDay, useApi } from "../lib";
import { Money, Panel } from "./ui";

type Month = {
  start: string; end: string; working_days: number; cash_received: number; pos: number; pos_difference: number;
  pos_differences: number; pos_open: number; paid_out: number; to_deposit: number; deposited: number;
  not_deposited: number; late_days: number; late_amount: number; late_dates: string[]; cash_short: number; cash_short_count: number;
};

/** The month so far, from the 1st to the chosen day, for the station being looked at. */
export default function MonthBox({ day, name }: { day: string; name: string }) {
  const m = useApi<Month>(`/dashboard/month?date=${day}`).data;
  if (!m || typeof m.working_days !== "number") return null;
  const month = new Date(`${m.start}T00:00:00Z`).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
  return (
    <Panel flush className="mb-6" title={`${name}: ${month} so far`}
      action={<span className="text-xs text-ink-faint">{fmtDay(m.start)} to {fmtDay(m.end)}</span>}>
      <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 [&>div]:border-paper-line [&>div]:border-b [&>div]:p-4 sm:[&>div]:border-r">
        <div><dt className="text-xs text-ink-faint">Days with collections</dt><dd className="num mt-1 text-xl font-semibold">{m.working_days}</dd></div>
        <div><dt className="text-xs text-ink-faint">Cash collected</dt><dd className="mt-1 text-xl font-semibold"><Money value={m.cash_received} /></dd></div>
        <div><dt className="text-xs text-ink-faint">Card (POS)</dt><dd className="mt-1 text-xl font-semibold"><Money value={m.pos} /></dd></div>
        <div><dt className="text-xs text-ink-faint">Paid out</dt><dd className="mt-1 text-xl font-semibold"><Money value={m.paid_out} tone="muted" /></dd></div>
        <div><dt className="text-xs text-ink-faint">Deposited in the bank</dt><dd className="mt-1 text-xl font-semibold"><Money value={m.deposited} tone="leaf" /></dd></div>
        <div><dt className="text-xs text-ink-faint">Not yet in the bank</dt><dd className="mt-1 text-xl font-semibold"><Money value={m.not_deposited} tone={m.late_amount ? "short" : m.not_deposited ? "brass" : "leaf"} /></dd></div>
      </dl>
      <ul className="grid gap-x-6 gap-y-2 px-5 py-4 text-sm sm:grid-cols-3">
        <li><Link to="/collections" className="hover:underline">
          <span className="text-ink-soft">Drivers short on cash: </span>
          {m.cash_short_count ? <><b className="text-short">{m.cash_short_count} {m.cash_short_count === 1 ? "time" : "times"}</b>, <Money value={m.cash_short} tone="short" /> SAR</> : <b className="text-leaf-dark">none</b>}
        </Link></li>
        <li><Link to="/pos" className="hover:underline">
          <span className="text-ink-soft">Card machine differences: </span>
          {m.pos_differences ? <><b className={m.pos_open ? "text-short" : ""}>{m.pos_differences}</b>{m.pos_open ? <span className="text-short">, {m.pos_open} not explained</span> : ", all explained"}</> : <b className="text-leaf-dark">none</b>}
        </Link></li>
        <li><Link to="/deposits" className="hover:underline">
          <span className="text-ink-soft">Bank deposits late or short: </span>
          {m.late_days ? <b className="text-short"><Money value={m.late_amount} tone="short" /> SAR ({m.late_dates.slice(0, 3).map((d) => fmtDay(d)).join(", ")}{m.late_dates.length > 3 ? "…" : ""})</b> : <b className="text-leaf-dark">none</b>}
        </Link></li>
      </ul>
    </Panel>
  );
}
