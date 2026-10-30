import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useBusinessDay } from "../businessDay";
import DayDeposit from "../components/DayDeposit";
import DayPicker from "../components/DayPicker";
import { Icon, IconName } from "../components/icons";
import { ErrorBox, Money, PageHeader } from "../components/ui";
import { CHANGED, fmtDay, fmtMoney, useApi } from "../lib";
import { byRegion, useStation } from "../stations";
import type { Dashboard } from "../types";
import Collections from "./Collections";
import Expenses from "./Expenses";
import Drivers from "./Drivers";
import FollowUps from "../components/FollowUps";
import DayCheck from "../components/DayCheck";
import PosCheck from "./PosCheck";

export const TABS: { key: string; label: string; icon: IconName }[] = [
  { key: "collection", label: "Collection", icon: "cash" },
  { key: "pos", label: "Card (POS)", icon: "card" },
  { key: "expenses", label: "Expenses", icon: "receipt" },
  { key: "deposit", label: "Deposit", icon: "bank" },
  { key: "follow", label: "Follow-ups", icon: "alert" },
  { key: "drivers", label: "Drivers", icon: "drivers" },
];

/** Without a station chosen: pick the station to check. */
function ChooseStation() {
  const { stations, choose } = useStation();
  const staffed = stations.filter((s) => s.active);
  return (
    <>
      <PageHeader title="Daily review" subtitle="Choose the station to check. You can also choose it at the top of the menu." />
      {staffed.length === 0 ? <p className="text-sm text-ink-soft">No station yet. Add one on the Stations page.</p> : (
        <div className="space-y-5">
          {byRegion(staffed).map(([region, list]) => (
            <section key={region}>
              <h2 className="mb-2 text-sm font-semibold">{region}</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {list.map((s) => (
                  <button key={s.id} onClick={() => choose(s.id)}
                    className="flex items-center gap-3 rounded-panel bg-white p-4 text-left shadow-panel transition hover:shadow-pop">
                    <span className="num grid h-10 w-12 shrink-0 place-items-center rounded-lg bg-ledger-900 text-xs font-bold text-brass-glow">{s.code.slice(0, 7)}</span>
                    <span className="min-w-0"><span className="block truncate font-semibold">{s.name}</span>
                      <span className="text-xs text-ink-faint">{s.drivers ? `${s.drivers} drivers` : "no drivers yet"}</span></span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

function Box({ label, children, foot, tone = "" }: { label: string; children: React.ReactNode; foot?: React.ReactNode; tone?: string }) {
  return (
    <div className={`p-4 ${tone}`}>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="mt-1 text-xl font-semibold">{children}</dd>
      {foot && <dd className="mt-0.5 text-xs text-ink-faint">{foot}</dd>}
    </div>
  );
}

/** One station, one day, on one screen: the day's figures on top, then collection, POS, expenses and deposit. */
export default function StationDay({ tab: fixedTab }: { tab?: string }) {
  const { station } = useStation();
  const { day } = useBusinessDay();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.key === params.get("tab")) ? params.get("tab")! : fixedTab ?? "collection";
  const { data, error, reload } = useApi<Dashboard>(station ? `/dashboard?date=${day}` : null);
  useEffect(() => { if (station) reload(); }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // the boxes on top follow anything saved in the tabs
    const again = () => reload();
    window.addEventListener(CHANGED, again);
    return () => window.removeEventListener(CHANGED, again);
  }, [reload]);

  if (!station) return <ChooseStation />;
  const f = data?.figures;
  const notYet = f && f.deposited === 0;
  // red when this day is late or short, or money from earlier days is still not in the bank
  const late = !!f && ((f.pending > 0 && (f.deposit_status === "overdue" || f.deposit_status === "short")) || (f.left ?? 0) - f.pending > 0.99);

  return (
    <>
      <PageHeader title={`Daily review: ${station.name}`} subtitle={`${station.code}${station.region ? ` · ${station.region}` : ""}${station.cashier_name ? ` · cashier ${station.cashier_name}` : ""} · everything the cashier did on one day.`} />
      <DayPicker />
      {error ? <ErrorBox message={error} retry={reload} /> : (
        <dl className="mb-6 grid grid-cols-2 overflow-hidden rounded-panel bg-white shadow-panel sm:grid-cols-3 lg:grid-cols-6 [&>div]:border-paper-line [&>div]:border-b lg:[&>div]:border-b-0 [&>div:not(:last-child)]:border-r">
          <Box label="Cash collected" foot={f ? `${f.drivers} drivers` : ""}><Money value={f?.cash_received} /></Box>
          <Box label="POS (card)" foot={f && f.pos_difference ? <span className="text-short">sheet differs by {fmtMoney(f.pos_difference)}</span> : f?.pos_awaiting ? "waiting for the system file" : "sheet agrees"}>
            <Money value={f?.pos_terminal || f?.pos_system} /></Box>
          <Box label="Expenses paid out"><Money value={f?.paid_out} tone="muted" /></Box>
          <Box label="To deposit" foot={f ? (f.brought_forward ? <>day's cash <span className="num">{fmtMoney(f.to_deposit)}</span> + <span className="num text-brass-dark">{fmtMoney(f.brought_forward)}</span> from earlier days</> : f.due_on ? `due ${fmtDay(f.due_on)}` : "") : ""}>
            <Money value={f ? (f.total_due ?? f.to_deposit) : undefined} /></Box>
          <Box label="Deposited" tone={notYet && f?.to_deposit ? "bg-paper/60" : ""}
            foot={f ? (notYet ? (f.to_deposit ? "not in the bank yet" : "") : f.deposit_status_text) : ""}>
            {notYet ? <span className="text-ink-faint">—</span> : <Money value={f?.deposited} tone="leaf" />}</Box>
          <Box label="Left, goes to the next day" tone={late ? "bg-short-soft/50" : ""}
            foot={f ? ((f.left ?? 0) > 0 ? f.deposit_status_text : "nothing left") : ""}>
            <Money value={f ? Math.max(f.left ?? f.pending, 0) : undefined} tone={late ? "short" : f && (f.left ?? 0) > 0 ? "brass" : "leaf"} /></Box>
        </dl>
      )}

      <DayCheck day={day} stationId={station.id} />

      <div role="tablist" aria-label="Part of the day" className="mb-6 flex gap-1 overflow-x-auto rounded-xl bg-paper-deep p-1">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setParams({ tab: t.key }, { replace: true })}
            className={`flex flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg px-4 py-2.5 text-sm font-medium transition ${tab === t.key ? "bg-white text-ink shadow-panel" : "text-ink-soft hover:text-ink"}`}>
            <Icon name={t.icon} className="h-4 w-4" />{t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel">
        {tab === "collection" && <Collections embedded />}
        {tab === "pos" && <PosCheck embedded />}
        {tab === "expenses" && <Expenses embedded />}
        {tab === "deposit" && <DayDeposit day={day} />}
        {tab === "follow" && <FollowUps title={`Follow-ups with the cashier of ${station.name}`} />}
        {tab === "drivers" && <Drivers embedded />}
      </div>
    </>
  );
}
