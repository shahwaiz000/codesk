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
      <PageHeader title={station ? `${station.name} station` : "Dashboard"}
        subtitle={station ? `The business day at ${station.name} at a glance, and everything there that still needs you.` : "The business day across every station at a glance, and everything across all days that still needs you."} />
      <DayPicker />
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
            <Link to="/collections" className="group p-5 hover:bg-paper/50">
              <dt className="text-sm text-ink-soft">Cash differences</dt>
              <dd className={`mt-1 text-[22px] font-semibold ${f.short_count ? "text-short" : "text-leaf-dark"}`}>
                {f.short_count ? <Money value={-f.cash_short} tone="short" /> : f.drivers ? "None" : "-"}</dd>
              <dd className="mt-1 text-xs text-ink-faint">{f.short_count ? `${f.short_count} short` : "No driver short"}{f.over_count ? `, ${f.over_count} over` : ""}</dd>
            </Link>
            <Link to="/pos" className="group p-5 hover:bg-paper/50">
              <dt className="text-sm text-ink-soft">POS differences</dt>
              <dd className={`mt-1 text-[22px] font-semibold ${f.pos_open ? "text-short" : f.pos_awaiting && !f.pos_differences ? "text-brass-dark" : "text-leaf-dark"}`}>
                {f.pos_differences ? <Money value={f.pos_difference} tone={f.pos_open ? "short" : "muted"} /> : f.pos_awaiting ? "Waiting" : f.drivers ? "None" : "-"}</dd>
              <dd className="mt-1 text-xs text-ink-faint">{f.pos_differences ? `${f.pos_open} of ${f.pos_differences} not yet explained` : f.pos_awaiting ? "Import the system’s POS orders" : "Every terminal agrees"}</dd>
            </Link>
          </dl>

          <MoneyRoute f={f} activeDrivers={data.active_drivers} />

          <MonthBox day={day} name={station ? station.name : "All stations"} />

          {!station && <StationBoard day={day} />}

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
            <div className="min-w-0 space-y-6">
              <Trend data={data.trend} day={day} onPick={setDay} />
              <Panel flush title={`Drivers with a difference on ${fmtDay(day)}`}>
                {data.attention.length === 0 ? (
                  <p className="px-5 py-6 text-sm text-ink-soft">{f.drivers ? "Every driver's cash and POS agree on this day." : "No handovers recorded on this day yet."}</p>
                ) : (
                  <ul className="divide-y divide-paper-line">
                    {data.attention.map((a) => (
                      <li key={a.driver_code} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                        <span className="min-w-[12rem] flex-1"><span className="num mr-2 font-semibold text-ink-soft">{a.driver_code}</span><span className="font-medium">{a.driver_name}</span></span>
                        {a.issues.map((i) => (
                          <Link key={i.kind} to={i.page} className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-paper">
                            <Badge tone={i.kind.endsWith("over") ? "brass" : i.explained ? "muted" : "short"}>{ISSUE_TEXT[i.kind]}{i.explained ? ", explained" : ""}</Badge>
                            <Money value={i.amount} tone={i.amount < 0 ? "short" : "brass"} className="font-semibold" />
                          </Link>
                        ))}
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
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
