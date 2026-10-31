import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useBusinessDay } from "../businessDay";
import DayPicker from "../components/DayPicker";
import { ErrorBox, Loading, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, fmtMoney, useApi, withStation } from "../lib";
import { Icon } from "../components/icons";
import type { Dashboard as Dash } from "../types";
import StationBoard from "../components/StationBoard";
import CallList from "../components/CallList";
import { useStation } from "../stations";

/* Chart colors, checked for color-blind separation and contrast on white. */
const CASH = "#1d7a55";
const POS = "#5a7fd1";


function Change({ now, before, prevDate }: { now: number; before: number | undefined; prevDate: string | null }) {
  if (before == null || !prevDate) return null;
  if (before === 0) return <span className="text-xs text-ink-faint">vs {fmtDay(prevDate)}</span>;
  const pct = ((now - before) / Math.abs(before)) * 100;
  const up = pct >= 0;
  return (
    <span className="text-xs text-ink-faint">
      <span className={`num font-medium ${up ? "text-leaf-dark" : "text-ink-soft"}`}>{up ? "+" : ""}{pct.toFixed(1)}%</span> vs {fmtDay(prevDate)}
    </span>
  );
}

export function Trend({ data, day, onPick }: { data: Dash["trend"]; day: string; onPick: (d: string) => void }) {
  const compact = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}K` : String(n));
  return (
    <Panel title="Collected per day, last 30 working days"
      action={<span className="flex items-center gap-4 text-xs text-ink-soft">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: CASH }} />Cash</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: POS }} />POS</span>
      </span>}>
      <div className="h-64" role="img" aria-label="Stacked bars of cash and POS collected per day; the selected day is highlighted">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -8, bottom: 0 }} barCategoryGap="28%"
            onClick={(e) => { const d = (e?.activePayload?.[0]?.payload as { date?: string } | undefined)?.date; if (d) onPick(d); }}>
            <CartesianGrid vertical={false} stroke="#e8ece6" />
            <XAxis dataKey="date" tickLine={false} axisLine={{ stroke: "#e1e6e0" }} interval={4}
              tick={{ fontSize: 11, fill: "#7c8781" }} tickFormatter={(d: string) => fmtDay(d).split(" ").slice(1).join(" ")} />
            <YAxis tickLine={false} axisLine={false} width={44} tick={{ fontSize: 11, fill: "#7c8781" }} tickFormatter={compact} />
            <Tooltip cursor={{ fill: "rgba(22,33,28,.05)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as Dash["trend"][number];
                return (
                  <div className="rounded-lg bg-white px-3 py-2 text-xs shadow-pop">
                    <p className="mb-1 font-semibold">{fmtDay(p.date, true)}</p>
                    <p className="flex justify-between gap-6"><span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: CASH }} />Cash</span><span className="num">{fmtMoney(p.cash)}</span></p>
                    <p className="flex justify-between gap-6"><span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: POS }} />POS</span><span className="num">{fmtMoney(p.pos)}</span></p>
                    <p className="mt-1 flex justify-between gap-6 border-t border-paper-line pt-1 font-semibold"><span>Total</span><span className="num">{fmtMoney(p.cash + p.pos)}</span></p>
                  </div>
                );
              }} />
            <Bar dataKey="cash" stackId="a" fill={CASH} maxBarSize={24} stroke="#fff" strokeWidth={1} cursor="pointer">
              {data.map((d) => <Cell key={d.date} fillOpacity={d.date === day ? 1 : 0.42} />)}
            </Bar>
            <Bar dataKey="pos" stackId="a" fill={POS} maxBarSize={24} radius={[4, 4, 0, 0]} stroke="#fff" strokeWidth={1} cursor="pointer">
              {data.map((d) => <Cell key={d.date} fillOpacity={d.date === day ? 1 : 0.42} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-ink-faint">Click a bar to open that day.</p>
    </Panel>
  );
}

const ISSUE_TEXT = { cash_short: "Cash short", cash_over: "Cash over", terminal_short: "POS terminal short", terminal_over: "POS terminal over" };

export default function Dashboard() {
  const { day } = useBusinessDay();
  const { station } = useStation();
  const { data, error, loading, reload } = useApi<Dash>(`/dashboard?date=${day}`);
  const f = data?.figures;
  const late = data?.alerts?.some((a) => a.kind === "deposit_overdue" || a.kind === "deposit_short");

  return (
    <>
      <PageHeader title="Overview"
        subtitle={station ? `${station.name}: the day's money, and whether the cashier needs a call.` : "Every station's day: how much money came in, and which cashier needs a call."}>
        <a href={withStation(`/api/supervisor/day-report?date=${day}`)} className="btn-primary"><Icon name="download" className="h-4 w-4" />Daily report (PDF)</a>
      </PageHeader>
      <DayPicker />
      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && f && (
        <dl className="mb-6 grid grid-cols-2 overflow-hidden rounded-panel bg-white shadow-panel lg:grid-cols-4 [&>*]:border-paper-line max-lg:[&>*:nth-child(-n+2)]:border-b max-lg:[&>*:nth-child(odd)]:border-r lg:[&>*:not(:last-child)]:border-r">
          <div className="p-5">
            <dt className="text-sm text-ink-soft">Cash collected</dt>
            <dd className="mt-1 text-[22px] font-semibold"><Money value={f.cash_received} /> <span className="text-sm font-normal text-ink-faint">SAR</span></dd>
            <dd className="mt-1 text-xs text-ink-faint">{f.drivers ? `${f.drivers} drivers handed over` : "Nothing imported for this day"}</dd>
          </div>
          <div className="p-5">
            <dt className="text-sm text-ink-soft">Card (POS)</dt>
            <dd className="mt-1 text-[22px] font-semibold"><Money value={f.pos_terminal || f.pos_system} /></dd>
            <dd className={`mt-1 text-xs ${Math.abs(f.pos_difference) >= 0.01 ? "text-short" : "text-ink-faint"}`}>
              {Math.abs(f.pos_difference) >= 0.01 ? `Machines differ from the system by ${fmtMoney(f.pos_difference)}` : f.pos_awaiting ? "Waiting for the system's card payments" : !(f.pos_terminal || f.pos_system) ? "No card payments on this day" : "Machines match the system"}</dd>
          </div>
          <Link to="/deposits" className="p-5 hover:bg-paper/50">
            <dt className="text-sm text-ink-soft">In the bank</dt>
            <dd className="mt-1 text-[22px] font-semibold">{f.deposited ? <Money value={f.deposited} tone="leaf" /> : <span className="text-ink-faint">—</span>}</dd>
            <dd className="mt-1 text-xs text-ink-faint">{f.to_deposit ? `${f.deposit_status_text}, due ${f.due_on ? fmtDay(f.due_on) : "next working day"}` : "Nothing to deposit"}</dd>
          </Link>
          <Link to="/deposits" className={`p-5 hover:bg-paper/50 ${late ? "bg-short-soft/50" : ""}`}>
            <dt className="text-sm text-ink-soft">Not yet in the bank</dt>
            <dd className="mt-1 text-[22px] font-semibold"><Money value={data.cash_on_hand} tone={late ? "short" : data.cash_on_hand ? "brass" : "leaf"} /></dd>
            <dd className={`mt-1 text-xs ${late ? "text-short" : "text-ink-faint"}`}>{late ? "Includes late or short deposits" : "All days, still with the cashiers"}</dd>
          </Link>
        </dl>
      )}

      <CallList day={day} only={station?.id} />

      {!station && <StationBoard day={day} />}
    </>
  );
}
