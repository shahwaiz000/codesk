import { useMemo, useState } from "react";
import { useBusinessDay } from "../businessDay";
import DayPicker from "../components/DayPicker";
import HandoverDialog from "../components/HandoverDialog";
import { Icon } from "../components/icons";
import ImportDialog, { money, PreviewRow } from "../components/ImportDialog";
import { Badge, Empty, ErrorBox, FormError, Loading, Modal, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, fmtMoney, send, useApi } from "../lib";
import type { CollectionDay, DepositLedger, Driver, Handover } from "../types";

function Figure({ label, children, foot }: { label: string; children: React.ReactNode; foot?: React.ReactNode }) {
  return (
    <div className="p-5">
      <dt className="text-sm text-ink-soft">{label}</dt>
      <dd className="mt-1 text-[22px] font-semibold leading-tight">{children}</dd>
      {foot && <dd className="mt-1 text-xs text-ink-faint">{foot}</dd>}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  deposited: "bg-leaf text-white", overdue: "bg-short text-white", short: "bg-short text-white", over: "bg-brass-glow text-ledger-950",
  due_today: "bg-brass-glow text-ledger-950", not_due: "bg-white/15 text-white", nothing: "bg-white/15 text-white",
};

/** The day's cash, large enough to read across the room, with where it stands on its way to the bank. */
function CashHero({ day, t }: { day: string; t: CollectionDay["totals"] }) {
  const dep = useApi<DepositLedger>(`/deposits?end=${day}&count=1`).data?.rows?.find((r) => r.date === day);
  return (
    <section aria-label="Cash collected" className="relative mb-6 overflow-hidden rounded-panel bg-ledger-900 text-white shadow-pop">
      {/* banknote guilloche */}
      <svg aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-[28rem] w-[28rem] text-brass-glow/15" viewBox="0 0 200 200" fill="none" stroke="currentColor" strokeWidth="0.6">
        {Array.from({ length: 14 }, (_, i) => <ellipse key={i} cx="100" cy="100" rx={30 + i * 5} ry={18 + i * 4} transform={`rotate(${i * 13} 100 100)`} />)}
      </svg>
      <div className="relative grid gap-6 p-6 sm:p-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium uppercase tracking-wider text-brass-glow">
            <Icon name="cash" className="h-5 w-5" />Cash collected · {fmtDay(day)}
          </p>
          <p className="num mt-3 text-[2.6rem] font-semibold leading-none tracking-tight sm:text-6xl lg:text-7xl">
            <span className="whitespace-nowrap">{fmtMoney(t.cash_received)}</span>{" "}
            <span className="inline-block whitespace-nowrap align-baseline text-lg font-normal text-ledger-300 sm:ml-2 sm:text-2xl">SAR</span>
          </p>
          {dep && (
            <p className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ledger-300">
              <span>Paid out <span className="num font-medium text-white">{fmtMoney(dep.paid_out)}</span></span>
              <span aria-hidden="true">→</span>
              <span>To the bank <span className="num font-semibold text-white">{fmtMoney(dep.to_deposit)}</span></span>
              <span>due {fmtDay(dep.due_on)}</span>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_TONE[dep.status] ?? "bg-white/15 text-white"}`}>{dep.status_text}</span>
            </p>
          )}
        </div>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-4 border-t border-white/10 pt-5 text-sm lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          <div><dt className="text-ledger-300">POS (card)</dt><dd className="num mt-1 text-xl font-semibold">{fmtMoney(t.pos_amount)}</dd></div>
          <div><dt className="text-ledger-300">Total collected</dt><dd className="num mt-1 text-xl font-semibold">{fmtMoney(t.total)}</dd></div>
          <div><dt className="text-ledger-300">Drivers</dt><dd className="num mt-1 text-xl font-semibold">{t.drivers}</dd></div>
          <div><dt className="text-ledger-300">Orders closed</dt><dd className="num mt-1 text-xl font-semibold">{t.orders}</dd></div>
        </dl>
      </div>
    </section>
  );
}

const PAID_PREVIEW = [
  { label: "Driver", cell: (r: PreviewRow) => <><span className="num font-medium">{(r.driver_code as string) ?? "-"}</span> <span className="text-ink-soft">{r.driver_name as string}</span></> },
  { label: "Orders", right: true, cell: (r: PreviewRow) => <span className="num">{r.orders as number}</span> },
  { label: "Cash", right: true, cell: money("expected_cash") },
  { label: "POS (system)", right: true, cell: money("system_pos") },
];

const HANDOVER_PREVIEW = [
  { label: "Driver", cell: (r: PreviewRow) => <><span className="num font-medium">{(r.driver_code as string) ?? "-"}</span> <span className="text-ink-soft">{r.driver_name as string}</span></> },
  { label: "Expected", right: true, cell: money("expected_cash") },
  { label: "Cash", right: true, cell: money("cash_received") },
  { label: "Difference", right: true, cell: (r: PreviewRow) => (r.difference as number)
      ? <Money value={r.difference as number} tone={(r.difference as number) < 0 ? "short" : "brass"} /> : <span className="text-ink-faint">-</span> },
  { label: "POS", right: true, cell: money("pos_amount") },
];

function StatusBadge({ h }: { h: Handover }) {
  if (h.status === "short") return <Badge tone="short">Short</Badge>;
  if (h.status === "over") return <Badge tone="brass">Over</Badge>;
  return <Badge tone="leaf">Agrees</Badge>;
}

export default function Collections() {
  const { day, setDay, refreshMeta } = useBusinessDay();
  const [version, setVersion] = useState(0);
  const { data, error, loading, reload } = useApi<CollectionDay>(`/collections?date=${day}&v=${version}`);
  const drivers = useApi<Driver[]>("/drivers");
  const paid = useApi<{ cash_mode: string }>("/settings").data?.cash_mode === "paid";
  const [dialog, setDialog] = useState<{ handover: Handover | null; preset?: number } | null>(null);
  const [importing, setImporting] = useState(false);
  const [deleting, setDeleting] = useState<Handover | null>(null);
  const [onlyDiffs, setOnlyDiffs] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const changed = () => { setVersion((v) => v + 1); refreshMeta(); drivers.reload(); };
  const t = data?.totals;
  const active = (drivers.data ?? []).filter((d) => d.active);
  const free = useMemo(() => {
    const done = new Set((data?.rows ?? []).map((r) => r.driver_id));
    return active.filter((d) => !done.has(d.id));
  }, [data, active]);
  const rows = (data?.rows ?? []).filter((r) => !onlyDiffs || r.status !== "ok");
  const expectedCount = (data?.rows.length ?? 0) + (data?.missing.length ?? 0);

  async function confirmDelete() {
    if (!deleting) return;
    setActionError(null);
    try { await send(`/collections/${deleting.id}`, "DELETE"); setDeleting(null); changed(); }
    catch (e) { setActionError((e as Error).message); }
  }

  return (
    <>
      <PageHeader title="Collections" subtitle={paid
        ? "The cash and card money each driver handed over, from your system's collection report. Orders are closed only when paid in full, so this is the day's cash that goes to the bank."
        : "What each driver handed over: cash counted at the desk against the cash the system expects, plus POS card totals."}>
        <button onClick={() => setImporting(true)} className={paid ? "btn-primary" : "btn-quiet"}><Icon name="upload" className="h-4 w-4" />Import file</button>
        <button onClick={() => setDialog({ handover: null })} disabled={free.length === 0} className={paid ? "btn-quiet" : "btn-primary"}><Icon name="plus" className="h-4 w-4" />{paid ? "Add by hand" : "Record handover"}</button>
      </PageHeader>

      <DayPicker refreshKey={version} />

      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && t && (
        <>
          {paid ? <CashHero day={day} t={t} /> : (
          <dl className="mb-6 grid grid-cols-2 divide-paper-line overflow-hidden rounded-panel bg-white shadow-panel lg:grid-cols-4 lg:divide-x [&>*]:border-paper-line max-lg:[&>*:nth-child(-n+2)]:border-b max-lg:[&>*:nth-child(odd)]:border-r">
            <Figure label="Cash counted" foot={<>Expected <span className="num">{fmtMoney(t.expected_cash)}</span></>}>
              <Money value={t.cash_received} /> <span className="text-sm font-normal text-ink-faint">SAR</span>
            </Figure>
            <Figure label={t.short > 0 ? "Cash short" : t.over > 0 ? "Cash over" : "Cash difference"}
              foot={t.short_count || t.over_count
                ? [t.short_count && `${t.short_count} ${t.short_count === 1 ? "driver" : "drivers"} short`,
                   t.over_count && (t.short > 0 ? `${t.over_count} over by ${fmtMoney(t.over)}` : `${t.over_count} ${t.over_count === 1 ? "driver" : "drivers"} over`)]
                  .filter(Boolean).join(", ")
                : t.drivers ? "Every driver's cash agrees" : "No handovers yet"}>
              {t.short > 0 ? <Money value={-t.short} tone="short" /> : t.over > 0 ? <Money value={t.over} tone="brass" /> : <Money value={0} tone="leaf" />}
            </Figure>
            <Figure label="POS (card)" foot={<><span className="num">{t.orders}</span> COD orders</>}>
              <Money value={t.pos_amount} /> <span className="text-sm font-normal text-ink-faint">SAR</span>
            </Figure>
            <Figure label="Handed over" foot={<>Total collected <span className="num">{fmtMoney(t.total)}</span> SAR</>}>
              <span className="num">{t.drivers}</span><span className="text-base font-normal text-ink-faint"> of {expectedCount} drivers</span>
              <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-paper-deep" aria-hidden="true">
                <span className="block h-full rounded-full bg-leaf transition-all" style={{ width: `${expectedCount ? (t.drivers / expectedCount) * 100 : 0}%` }} />
              </span>
            </Figure>
          </dl>
          )}

          <Panel flush title={`Handovers on ${fmtDay(day)}`}
            action={!paid && data.rows.length > 0 && (t.short_count + t.over_count > 0) && (
              <label className="flex items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" className="h-4 w-4 accent-ledger-700" checked={onlyDiffs} onChange={(e) => setOnlyDiffs(e.target.checked)} />
                Only differences</label>
            )}>
            {actionError && <div className="px-5 pt-4"><FormError message={actionError} /></div>}
            {data.rows.length === 0 ? (
              <Empty title="No handovers recorded for this day" hint="Record each driver as they hand over, or import the day's file from your delivery system.">
                <div className="flex justify-center gap-2">
                  <button onClick={() => setImporting(true)} className="btn-quiet">Import file</button>
                  <button onClick={() => setDialog({ handover: null })} className="btn-primary">Record handover</button>
                </div>
              </Empty>
            ) : (
              <div className="relative overflow-x-auto">
                <table className="w-full min-w-[880px] text-sm">
                  <thead>
                    <tr className="border-b border-paper-line text-left text-xs text-ink-faint">
                      <th className="px-5 py-2.5 font-medium">Driver</th>
                      <th className="px-3 py-2.5 text-right font-medium">Orders</th>
                      {paid ? <th className="px-3 py-2.5 text-right font-medium">Cash</th> : <>
                        <th className="px-3 py-2.5 text-right font-medium">Expected cash</th>
                        <th className="px-3 py-2.5 text-right font-medium">Cash counted</th>
                        <th className="px-3 py-2.5 text-right font-medium">Difference</th></>}
                      <th className="px-3 py-2.5 text-right font-medium">POS terminal</th>
                      <th className="px-3 py-2.5 text-right font-medium">Total</th>
                      {!paid && <th className="px-3 py-2.5 font-medium">Status</th>}
                      <th className="px-5 py-2.5"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((h) => (
                      <tr key={h.id} className={`border-b border-paper-line hover:bg-paper/60 ${!paid && h.status === "short" ? "bg-short-soft/40" : ""}`}>
                        <td className="px-5 py-3">
                          <span className="num mr-2 font-semibold text-ink-soft">{h.driver_code}</span>
                          <span className="font-medium">{h.driver_name}</span>
                          {h.note && <span className="block max-w-xs truncate text-xs text-ink-faint" title={h.note}>{h.note}</span>}
                        </td>
                        <td className="num px-3 py-3 text-right text-ink-soft">{h.orders}</td>
                        {paid ? <td className="px-3 py-3 text-right font-medium"><Money value={h.cash_received} /></td> : <>
                          <td className="px-3 py-3 text-right"><Money value={h.expected_cash} tone="muted" /></td>
                          <td className="px-3 py-3 text-right font-medium"><Money value={h.cash_received} /></td>
                          <td className="px-3 py-3 text-right font-semibold">
                            {h.difference ? <Money value={h.difference} tone={h.difference < 0 ? "short" : "brass"} /> : <span className="text-ink-faint">-</span>}
                          </td></>}
                        <td className="px-3 py-3 text-right"><Money value={h.pos_amount} /></td>
                        <td className="px-3 py-3 text-right"><Money value={h.total} /></td>
                        {!paid && <td className="px-3 py-3"><StatusBadge h={h} /></td>}
                        <td className="px-5 py-3">
                          <div className="flex justify-end gap-1">
                            <button onClick={() => setDialog({ handover: h })} className="rounded-md px-2 py-1 text-xs font-medium text-ink-soft hover:bg-paper-deep hover:text-ink">Correct</button>
                            <button onClick={() => setDeleting(h)} aria-label={`Delete ${h.driver_code} handover`} className="rounded-md p-1 text-ink-faint hover:bg-short-soft hover:text-short"><Icon name="trash" className="h-4 w-4" /></button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  {!onlyDiffs && (
                    <tfoot>
                      <tr className="bg-paper/70 font-semibold">
                        <td className="px-5 py-3">Day total</td>
                        <td className="num px-3 py-3 text-right">{t.orders}</td>
                        {paid ? <td className="px-3 py-3 text-right"><Money value={t.cash_received} /></td> : <>
                          <td className="px-3 py-3 text-right"><Money value={t.expected_cash} /></td>
                          <td className="px-3 py-3 text-right"><Money value={t.cash_received} /></td>
                          <td className="px-3 py-3 text-right">{t.difference ? <Money value={t.difference} tone={t.difference < 0 ? "short" : "brass"} /> : "-"}</td></>}
                        <td className="px-3 py-3 text-right"><Money value={t.pos_amount} /></td>
                        <td className="px-3 py-3 text-right"><Money value={t.total} /></td>
                        <td colSpan={paid ? 1 : 2} />
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            )}

            {!paid && data.missing.length > 0 && data.rows.length > 0 && (
              <div className="border-t border-paper-line px-5 py-4">
                <p className="mb-3 text-sm font-medium">Not handed over yet <span className="font-normal text-ink-faint">({data.missing.length})</span></p>
                <ul className="flex flex-wrap gap-2">
                  {data.missing.map((m) => (
                    <li key={m.id}>
                      <button onClick={() => setDialog({ handover: null, preset: m.id })}
                        className="flex items-center gap-2 rounded-lg border border-dashed border-paper-line px-3 py-1.5 text-sm hover:border-leaf hover:bg-leaf-soft/50">
                        <span className="num font-semibold text-ink-soft">{m.code}</span>{m.name}
                        <Icon name="plus" className="h-3.5 w-3.5 text-leaf" />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>
        </>
      )}

      {dialog && (
        <HandoverDialog day={day} handover={dialog.handover} presetDriver={dialog.preset} paid={paid}
          drivers={dialog.handover ? active.concat((drivers.data ?? []).filter((d) => d.id === dialog.handover!.driver_id && !d.active)) : free}
          onClose={() => setDialog(null)} onSaved={() => { setDialog(null); changed(); }} />
      )}
      {importing && (
        <ImportDialog day={day} title="Import handovers" endpoint="/collections/import" templateUrl="/api/collections/template"
          noun={["handover", "handovers"]} columns={paid ? PAID_PREVIEW : HANDOVER_PREVIEW}
          intro={paid ? "Upload your system's collection report as it is (one line per order). Each driver's cash lines are added up into the cash he handed over; card lines are left to the POS check." : "Upload your system's collection report as it is (one line per order): each driver's expected cash is added up from his cash lines, and the counted cash starts equal to it, so you only change the drivers who were short. Or upload a list with one row per driver: driver ID, expected cash and cash received."}
          onClose={() => setImporting(false)}
          onSaved={(dates) => { setImporting(false); if (dates.length === 1) setDay(dates[0]); changed(); }} />
      )}
      {deleting && (
        <Modal title="Delete this handover?" onClose={() => setDeleting(null)}>
          <p className="text-sm text-ink-soft">
            {deleting.driver_code} {deleting.driver_name} on {fmtDay(deleting.business_date, true)}: cash {fmtMoney(deleting.cash_received)}, POS {fmtMoney(deleting.pos_amount)}.
            The deletion is written to the activity log.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setDeleting(null)} className="btn-quiet">Keep it</button>
            <button onClick={confirmDelete} className="btn-danger">Delete handover</button>
          </div>
        </Modal>
      )}
    </>
  );
}
