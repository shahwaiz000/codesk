import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useBusinessDay } from "../businessDay";
import DayPicker from "../components/DayPicker";
import MoneyRoute from "../components/MoneyRoute";
import { Icon } from "../components/icons";
import { Badge, ErrorBox, Loading, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, fmtMoney, useApi } from "../lib";
import type { Dashboard as Dash } from "../types";
import StationBoard from "../components/StationBoard";
import MonthBox from "../components/MonthBox";
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

function Trend({ data, day, onPick }: { data: Dash["trend"]; day: string; onPick: (d: string) => void }) {
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
  const { day, setDay } = useBusinessDay();
  const { station } = useStation();
  const { data, error, loading, reload } = useApi<Dash>(`/dashboard?date=${day}`);
  const f = data?.figures;
  const p = data?.previous ?? undefined;

  return (
    <>
      <PageHeader title={station ? `${station.name} station` : "Overview"}
        subtitle={station ? `The business day at ${station.name} at a glance, and everything there that still needs you.` : "Every station's day at a glance: which cashier to call, which files are missing, and where the money is."} />
      <DayPicker />
      {!station && <CallList day={day} />}
      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && f && (
        <>
          <dl className="mb-6 grid grid-cols-2 overflow-hidden rounded-panel bg-white shadow-panel lg:grid-cols-4 [&>div]:border-paper-line max-lg:[&>div:nth-child(-n+2)]:border-b max-lg:[&>div:nth-child(odd)]:border-r lg:[&>div:not(:last-child)]:border-r">
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Total collected</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={f.total_collected} /> <span className="text-sm font-normal text-ink-faint">SAR</span></dd>
              <dd className="mt-1"><Change now={f.total_collected} before={p?.total_collected} prevDate={data.previous_date} /></dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Cash and POS split</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={f.cash_received} /></dd>
              <dd className="mt-1 text-xs text-ink-faint">cash, plus <span className="num">{fmtMoney(f.pos_terminal)}</span> POS</dd>
            </div>
            <Link to="/deposits" className="group p-5 hover:bg-paper/50">
              <dt className="text-sm text-ink-soft">In the bank</dt>
              <dd className={`mt-1 text-[22px] font-semibold ${f.deposited ? "text-leaf-dark" : ""}`}>{f.deposited ? <Money value={f.deposited} tone="leaf" /> : <span className="text-ink-faint">—</span>}</dd>
              <dd className="mt-1 text-xs text-ink-faint">{f.to_deposit ? <>{f.deposit_status_text} · <span className="num">{fmtMoney(f.total_due ?? f.to_deposit)}</span> to deposit</> : "Nothing to deposit"}</dd>
            </Link>
            <Link to="/pos" className="group p-5 hover:bg-paper/50">
              <dt className="text-sm text-ink-soft">Card sheet against the system</dt>
              <dd className={`mt-1 text-[22px] font-semibold ${Math.abs(f.pos_difference) >= 0.01 ? "text-short" : f.pos_awaiting ? "text-brass-dark" : "text-leaf-dark"}`}>
                {Math.abs(f.pos_difference) >= 0.01 ? <Money value={f.pos_difference} tone="short" /> : f.pos_awaiting ? "Waiting" : f.drivers ? "Agrees" : "-"}</dd>
              <dd className="mt-1 text-xs text-ink-faint">{Math.abs(f.pos_difference) >= 0.01 ? `The sheet is ${f.pos_difference < 0 ? "below" : "above"} the system` : f.pos_awaiting ? "Import the system’s card payments" : "Card machine sheet matches the system"}</dd>
            </Link>
          </dl>

          <MoneyRoute f={f} activeDrivers={data.active_drivers} />

          <MonthBox day={day} name={station ? station.name : "All stations"} />

          {!station && <StationBoard day={day} />}

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
            <div className="min-w-0 space-y-6">
              <Trend data={data.trend} day={day} onPick={setDay} />

            </div>

            <Panel flush title="Needs attention" className="self-start"
              action={data.alert_count > 0 && <span className="num rounded-full bg-short-soft px-2 py-0.5 text-xs font-semibold text-short-dark">{data.alert_count}</span>}>
              <div className="border-b border-paper-line px-5 py-4">
                <p className="text-sm text-ink-soft">Cash on hand, all days</p>
                <p className="text-2xl font-semibold"><Money value={data.cash_on_hand} /> <span className="text-sm font-normal text-ink-faint">SAR</span></p>
              </div>
              {data.alerts.length === 0 ? (
                <p className="flex items-center gap-2 px-5 py-6 text-sm text-leaf-dark"><Icon name="check" className="h-4 w-4" />Nothing is waiting. Every deposit, POS difference and advance is in order.</p>
              ) : (
                <ul className="divide-y divide-paper-line">
                  {data.alerts.map((a, i) => (
                    <li key={i}>
                      <Link to={a.page} onClick={() => a.kind !== "advance_old" && setDay(a.date)} className="flex items-start gap-3 px-5 py-3 text-sm hover:bg-paper/60">
                        <Icon name={a.kind.startsWith("unusual") ? "spark" : a.kind.startsWith("deposit") ? "bank" : a.kind.startsWith("pos") ? "card" : a.kind.startsWith("file_") ? "upload" : "receipt"}
                          className={`mt-0.5 h-4 w-4 ${a.kind === "advance_old" || a.kind.startsWith("unusual") ? "text-brass" : "text-short"}`} />
                        <span className="min-w-0 flex-1">
                          <span className="block">{a.text}</span>
                          <span className="text-xs text-ink-faint">{fmtDay(a.date, true)}</span>
                        </span>
                        {!a.kind.startsWith("file_") && <Money value={a.amount} className="font-semibold" />}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              {data.alert_count > data.alerts.length && <p className="border-t border-paper-line px-5 py-3 text-xs text-ink-faint">Showing the newest {data.alerts.length} of {data.alert_count}.</p>}
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
