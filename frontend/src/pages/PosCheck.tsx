import { FormEvent, Fragment, useState } from "react";
import { useBusinessDay } from "../businessDay";
import DayPicker from "../components/DayPicker";
import { Icon } from "../components/icons";
import ImportDialog, { money, PreviewRow } from "../components/ImportDialog";
import { Badge, Empty, ErrorBox, FormError, Loading, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, fmtMoney, fmtWhen, send, useApi } from "../lib";
import type { Driver, Machine, PairedBy, PosDay, PosRow } from "../types";

const driverCell = (r: PreviewRow) => r.driver_code
  ? <><span className="num font-medium">{r.driver_code as string}</span> <span className="text-ink-soft">{r.driver_name as string}</span></>
  : <span className="text-ink-faint">-</span>;

const ORDER_PREVIEW = [
  { label: "Order", cell: (r: PreviewRow) => <span className="num">{(r.order_no as string) ?? "-"}</span> },
  { label: "Driver", cell: driverCell },
  { label: "Amount", right: true, cell: money("amount") },
];
export const PAIRED_TEXT: Record<PairedBy, string> = { terminal: "registered machine", amount: "same amount", hand: "chosen by hand" };

const TERMINAL_PREVIEW = [
  { label: "Terminal", cell: (r: PreviewRow) => <span className="num">{(r.terminal as string) ?? "-"}</span> },
  { label: "Driver", cell: (r: PreviewRow) => r.driver_code
    ? <>{driverCell(r)} <span className="text-xs text-ink-faint">({PAIRED_TEXT[r.paired_by as PairedBy]})</span></>
    : <span className="text-ink-faint">-</span> },
  { label: "Was", right: true, cell: money("previous") },
  { label: "Terminal total", right: true, cell: money("amount") },
];

function StatusCell({ r }: { r: PosRow }) {
  if (r.status === "agrees") return <Badge tone="leaf">Agrees</Badge>;
  if (r.status === "no_terminal") return <Badge tone="muted">No terminal total</Badge>;
  if (r.status === "awaiting_orders") return <Badge tone="muted">Waiting for system orders</Badge>;
  const rv = r.review;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Badge tone={r.status === "terminal_short" ? "short" : "brass"}>{r.status_text}</Badge>
      {rv && !rv.stale && rv.status === "explained" && <Badge tone="leaf">Explained</Badge>}
      {rv && !rv.stale && rv.status === "follow_up" && <Badge tone="brass">Follow up</Badge>}
      {rv?.stale && <Badge tone="muted">Changed since review</Badge>}
    </span>
  );
}

function Orders({ day, r }: { day: string; r: PosRow }) {
  const { data, error, loading } = useApi<{ order_no: string; amount: number }[]>(`/pos/orders?date=${day}&driver_id=${r.driver_id}`);
  const target = r.difference ? Math.abs(r.difference) : null;
  if (loading && !data) return <p className="py-6 text-sm text-ink-faint">Loading orders...</p>;
  if (error) return <FormError message={error} />;
  if (!data?.length) return <p className="py-2 text-sm text-ink-soft">No POS orders in the system for this driver on this day. If he took card payments, import the system's POS orders.</p>;
  const exact = target ? data.filter((o) => Math.abs(o.amount - target) < 0.005) : [];
  return (
    <div>
      {exact.length > 0 && (
        <p className="mb-3 rounded-md bg-brass-soft px-3 py-2 text-sm text-brass-dark">
          {exact.length === 1 ? `Order ${exact[0].order_no} is exactly ${fmtMoney(target)}` : `${exact.length} orders are exactly ${fmtMoney(target)}`}, the size of the difference. Check how {exact.length === 1 ? "it was" : "they were"} paid.
        </p>
      )}
      <div className="max-h-72 overflow-y-auto rounded-lg border border-paper-line bg-white">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-paper text-left text-xs text-ink-faint">
            <tr><th className="px-3 py-2 font-medium">POS order</th><th className="px-3 py-2 text-right font-medium">Amount (SAR)</th></tr>
          </thead>
          <tbody>
            {data.map((o) => {
              const hit = exact.includes(o);
              return (
                <tr key={o.order_no} className={`border-t border-paper-line ${hit ? "bg-brass-soft/70" : ""}`}>
                  <td className="num px-3 py-1.5">{o.order_no}{hit && <span className="ml-2 text-xs font-medium text-brass-dark">matches the difference</span>}</td>
                  <td className="px-3 py-1.5 text-right"><Money value={o.amount} /></td>
                </tr>
              );
            })}
          </tbody>
          <tfoot><tr className="border-t border-paper-line bg-paper/70 font-semibold">
            <td className="px-3 py-2">{data.length} orders</td><td className="px-3 py-2 text-right"><Money value={r.system_total} /></td>
          </tr></tfoot>
        </table>
      </div>
    </div>
  );
}

function MachinesPanel({ machines, rows, onChanged }: { machines: Machine[]; rows: PosRow[]; onChanged: () => void }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [other, setOther] = useState<Record<number, string>>({});
  const free = machines.filter((m) => !m.driver_id);
  const paired = machines.filter((m) => m.driver_id);
  // any active driver can be chosen: a driver whose card orders were all closed as cash has no POS orders at all
  const list = useApi<Driver[]>("/drivers").data;
  const drivers = Array.isArray(list) ? list : [];
  const posIds = new Set(rows.filter((r) => r.order_count > 0).map((r) => r.driver_id));
  const others = drivers.filter((d) => d.active && !posIds.has(d.id));

  async function remove(m: Machine) {
    setBusy(m.id); setError(null);
    try { await send(`/pos/machines/${m.id}`, "DELETE"); onChanged(); }
    catch (err) { setError((err as Error).message); }
    setBusy(null);
  }
  async function pair(m: Machine, driverId: number | null) {
    setBusy(m.id); setError(null);
    try { await send(`/pos/machines/${m.id}`, "PUT", { driver_id: driverId }); onChanged(); }
    catch (err) { setError((err as Error).message); }
    setBusy(null);
  }

  return (
    <Panel title={free.length ? `${free.length} POS machine${free.length === 1 ? "" : "s"} to match with a driver` : "POS machines"} className="mb-6">
      {free.length > 0 && (
        <>
          <p className="mb-4 text-sm text-ink-soft">
            {paired.length} of {machines.length} machines were matched automatically. For each machine below, pick the driver who had it.
            The closest system totals are shown first; a small difference is usually the driver's POS difference for the day.
          </p>
          <ul className="space-y-3">
            {free.map((m) => (
              <li key={m.id} className="rounded-lg border border-brass/30 bg-brass-soft/40 p-4">
                <div className="mb-3 flex flex-wrap items-baseline gap-x-3">
                  <span className="text-xs text-ink-faint">Machine</span>
                  <span className="num font-semibold">{m.terminal}</span>
                  <span className="ml-auto text-lg font-semibold"><Money value={m.amount} /> <span className="text-xs font-normal text-ink-faint">SAR</span></span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {m.suggestions.map((s) => (
                    <button key={s.driver_id} disabled={busy === m.id} onClick={() => pair(m, s.driver_id)}
                      className="flex min-w-0 flex-col items-start rounded-lg border border-paper-line bg-white px-3 py-2 text-left text-sm hover:border-ledger-700 disabled:opacity-50">
                      <span><span className="num font-semibold">{s.driver_code}</span> <span className="text-ink-soft">{s.driver_name}</span></span>
                      <span className="text-xs text-ink-faint">system <Money value={s.system_total} />, difference{" "}
                        <Money value={s.difference} tone={Math.abs(s.difference) < 0.005 ? "leaf" : s.difference < 0 ? "short" : "brass"} /></span>
                    </button>
                  ))}
                  <span className="flex items-center gap-2">
                    <select aria-label={`Other driver for machine ${m.terminal}`} className="field !mt-0 !w-auto" value={other[m.id] ?? ""}
                      onChange={(e) => setOther({ ...other, [m.id]: e.target.value })}>
                      <option value="">Another driver...</option>
                      <optgroup label="Drivers with POS orders">
                        {rows.filter((r) => r.order_count > 0).map((r) => <option key={r.driver_id} value={r.driver_id}>{r.driver_code} {r.driver_name}</option>)}
                      </optgroup>
                      {others.length > 0 && <optgroup label="Drivers without POS orders in the system">
                        {others.map((d) => <option key={d.id} value={d.id}>{d.code} {d.name}</option>)}
                      </optgroup>}
                    </select>
                    {other[m.id] && <button disabled={busy === m.id} onClick={() => pair(m, Number(other[m.id]))} className="btn-primary">Match</button>}
                  </span>
                  <button disabled={busy === m.id} onClick={() => remove(m)} className="btn-quiet ml-auto self-center text-xs"
                    title="Remove this machine total if it was entered by mistake">Remove</button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <FormError message={error} />
      {paired.length > 0 && (
        <details className={free.length ? "mt-5" : ""}>
          <summary className="cursor-pointer text-sm text-ink-soft">{paired.length} machine{paired.length === 1 ? "" : "s"} matched with a driver</summary>
          <ul className="mt-3 divide-y divide-paper-line text-sm">
            {paired.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <span className="num w-24 font-medium">{m.terminal}</span>
                <span className="min-w-0 flex-1"><span className="num font-semibold text-ink-soft">{m.driver_code}</span> {m.driver_name}
                  <span className="ml-2 text-xs text-ink-faint">{m.paired_by ? PAIRED_TEXT[m.paired_by] : ""}</span></span>
                <Money value={m.amount} />
                <button disabled={busy === m.id} onClick={() => pair(m, null)} className="btn-quiet !px-2 !py-1 text-xs">Undo</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}

function ReviewBox({ day, r, sheet, onChanged }: { day: string; r: PosRow; sheet: boolean; onChanged: () => void }) {
  const [note, setNote] = useState(r.review?.note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function decide(status: "explained" | "follow_up", e?: FormEvent) {
    e?.preventDefault();
    setBusy(true); setError(null);
    try { await send("/pos/review", "PUT", { business_date: day, driver_id: r.driver_id, status, note }); onChanged(); }
    catch (err) { setError((err as Error).message); }
    setBusy(false);
  }
  async function reopen() {
    setBusy(true); setError(null);
    try { await send(`/pos/review?business_date=${day}&driver_id=${r.driver_id}`, "DELETE"); setNote(""); onChanged(); }
    catch (err) { setError((err as Error).message); }
    setBusy(false);
  }

  if (r.status === "agrees") return <p className="text-sm text-leaf-dark">The terminal total agrees with the system to the halala. Nothing to review.</p>;
  if (r.status === "awaiting_orders") return <p className="text-sm text-ink-soft">The terminal total is recorded, but the system’s POS orders for this day are not imported yet, so there is nothing to compare it with. Import the system orders for this day.</p>;
  if (r.status === "no_terminal") return <p className="text-sm text-ink-soft">{sheet
    ? "No POS machine is matched with this driver yet. Match his machine in the box above the table."
    : "This driver has POS orders but no handover yet, so there is no terminal total. Record his handover on the Collections page, or import the terminal sheet."}</p>;
  const rv = r.review;
  return (
    <form onSubmit={(e) => decide("explained", e)} className="space-y-3">
      <p className="text-sm">
        The terminal shows <Money value={r.terminal_total} className="font-semibold" /> but the system's POS orders add up to <Money value={r.system_total} className="font-semibold" />,
        so the terminal is <span className={r.status === "terminal_short" ? "font-semibold text-short" : "font-semibold text-brass-dark"}>{fmtMoney(Math.abs(r.difference ?? 0))} {r.status === "terminal_short" ? "short" : "over"}</span>.
      </p>
      {rv && (
        <p className={`rounded-md px-3 py-2 text-sm ${rv.stale ? "bg-paper-deep text-ink-soft" : rv.status === "explained" ? "bg-leaf-soft text-leaf-dark" : "bg-brass-soft text-brass-dark"}`}>
          {rv.status === "explained" ? "Explained" : "Marked for follow-up"} by {rv.by}, {fmtWhen(rv.at)}{rv.note ? `: ${rv.note}` : ""}
          {rv.stale && <span className="block text-xs">The amounts have changed since then, so review it again.</span>}
        </p>
      )}
      <label className="block text-sm font-medium">Reason or note
        <input className="field" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)}
          placeholder={r.status === "terminal_short" ? "e.g. order closed as POS but customer paid cash" : "e.g. card swiped twice, refund issued"} /></label>
      <FormError message={error} />
      <div className="flex flex-wrap gap-2">
        <button disabled={busy || note.trim().length < 3} className="btn-primary"><Icon name="check" className="h-4 w-4" />Mark explained</button>
        <button type="button" disabled={busy} onClick={() => decide("follow_up")} className="btn-quiet">Needs follow-up</button>
        {rv && <button type="button" disabled={busy} onClick={reopen} className="btn-quiet ml-auto">Reopen</button>}
      </div>
    </form>
  );
}

export default function PosCheck({ embedded = false }: { embedded?: boolean }) {
  const { day, setDay } = useBusinessDay();
  const [version, setVersion] = useState(0);
  const { data, error, loading, reload } = useApi<PosDay>(`/pos?date=${day}&v=${version}`);
  const [open, setOpen] = useState<number | null>(null);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [importing, setImporting] = useState<"orders" | "terminals" | null>(null);
  const t = data?.totals;
  const rows = (data?.rows ?? []).filter((r) => !onlyOpen || r.open || r.status === "no_terminal");
  const changed = () => setVersion((v) => v + 1);

  return (
    <>
      <PageHeader embedded={embedded} title="POS check" subtitle="For each driver, the orders the system shows as closed by POS against the total on his POS terminal. Both should agree to the halala.">
        <button onClick={() => setImporting("orders")} className="btn-quiet"><Icon name="upload" className="h-4 w-4" />Import system orders</button>
        <button onClick={() => setImporting("terminals")} className="btn-quiet"><Icon name="upload" className="h-4 w-4" />Import terminal sheet</button>
      </PageHeader>

      {!embedded && <DayPicker refreshKey={version} />}

      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && t && (
        <>
          {!data.orders_imported && data.rows.length > 0 && (
            <div className="mb-6 flex flex-wrap items-center gap-3 rounded-panel border border-brass/30 bg-brass-soft px-5 py-3 text-sm text-brass-dark">
              <Icon name="alert" className="h-5 w-5" />
              <span className="flex-1">The system's POS orders for {fmtDay(day)} are not imported yet, so the terminal totals cannot be checked.</span>
              <button onClick={() => setImporting("orders")} className="btn-primary">Import system orders</button>
            </div>
          )}

          <dl className="mb-6 grid grid-cols-2 overflow-hidden rounded-panel bg-white shadow-panel lg:grid-cols-4 [&>div]:border-paper-line max-lg:[&>div:nth-child(-n+2)]:border-b max-lg:[&>div:nth-child(odd)]:border-r lg:[&>div:not(:last-child)]:border-r">
            <div className="p-5">
              <dt className="text-sm text-ink-soft">System POS orders</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={t.system_total} /> <span className="text-sm font-normal text-ink-faint">SAR</span></dd>
              <dd className="mt-1 text-xs text-ink-faint"><span className="num">{t.order_count}</span> orders</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">{t.sheet ? "POS machines" : "Terminal totals"}</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={t.sheet ? t.machines_total : t.terminal_total} /> <span className="text-sm font-normal text-ink-faint">SAR</span></dd>
              <dd className="mt-1 text-xs text-ink-faint">{t.sheet ? `${t.machines} machines${t.unpaired ? `, ${t.unpaired} not matched yet` : ", all matched"}` : t.awaiting ? `${t.awaiting} waiting for system orders` : t.no_terminal ? `${t.no_terminal} without a terminal total` : `${t.drivers} drivers`}</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Difference</dt>
              <dd className="mt-1 text-[22px] font-semibold">
                {t.difference ? <Money value={t.difference} tone={t.difference < 0 ? "short" : "brass"} /> : <Money value={0} tone="leaf" />}
              </dd>
              <dd className="mt-1 text-xs text-ink-faint">
                {t.sheet && t.order_count ? (t.difference ? `Machines ${t.difference < 0 ? "below" : "above"} the system orders` : "Machines agree with the system") : t.differences ? [t.short && `terminals short ${fmtMoney(t.short)}`, t.over && `over ${fmtMoney(t.over)}`].filter(Boolean).join(", ") : t.awaiting ? "Not checked yet" : t.drivers ? "Every terminal agrees" : "Nothing recorded"}
              </dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">To review</dt>
              <dd className={`mt-1 text-[22px] font-semibold ${t.open ? "text-short" : "text-leaf-dark"}`}>
                <span className="num">{t.open}</span><span className="text-base font-normal text-ink-faint"> open</span>
              </dd>
              <dd className="mt-1 text-xs text-ink-faint"><span className="num">{t.agrees}</span> agree, <span className="num">{t.explained}</span> explained</dd>
            </div>
          </dl>

          {!!data.machines?.length && data.orders_imported && <MachinesPanel machines={data.machines} rows={data.rows} onChanged={changed} />}

          <Panel flush title={`POS by driver on ${fmtDay(day)}`}
            action={(t.differences > 0 || t.no_terminal > 0) && (
              <label className="flex items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" className="h-4 w-4 accent-ledger-700" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />
                Only what needs attention</label>
            )}>
            {data.rows.length === 0 ? (
              <Empty title="No POS records for this day" hint="Record the drivers' handovers on the Collections page, then import the system's POS orders for the day.">
                <div className="flex justify-center gap-2">
                  <button onClick={() => setImporting("orders")} className="btn-primary">Import system orders</button>
                </div>
              </Empty>
            ) : rows.length === 0 ? (
              <Empty title="Nothing needs attention" hint="Every difference on this day is explained." />
            ) : (
              <div className="relative overflow-x-auto">
                <table className="w-full min-w-[860px] text-sm">
                  <thead>
                    <tr className="border-b border-paper-line text-left text-xs text-ink-faint">
                      <th className="px-5 py-2.5 font-medium">Driver</th>
                      <th className="px-3 py-2.5 font-medium">Terminal</th>
                      <th className="px-3 py-2.5 text-right font-medium">POS orders</th>
                      <th className="px-3 py-2.5 text-right font-medium">System total</th>
                      <th className="px-3 py-2.5 text-right font-medium">Terminal total</th>
                      <th className="px-3 py-2.5 text-right font-medium">Difference</th>
                      <th className="px-3 py-2.5 font-medium">Status</th>
                      <th className="w-10 px-3 py-2.5"><span className="sr-only">Details</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const expanded = open === r.driver_id;
                      return (
                        <Fragment key={r.driver_id}>
                          <tr onClick={() => setOpen(expanded ? null : r.driver_id)}
                            className={`cursor-pointer border-b border-paper-line hover:bg-paper/60 ${r.open ? "bg-short-soft/40" : ""} ${expanded ? "bg-paper/80" : ""}`}>
                            <td className="px-5 py-3"><span className="num mr-2 font-semibold text-ink-soft">{r.driver_code}</span><span className="font-medium">{r.driver_name}</span></td>
                            <td className="num px-3 py-3 text-ink-soft">{r.terminal ?? <span className="text-ink-faint">{t.sheet ? "Not matched" : "Not set"}</span>}
                              {r.paired_by && r.paired_by !== "terminal" && <span className="block text-xs text-ink-faint">{PAIRED_TEXT[r.paired_by]}</span>}</td>
                            <td className="num px-3 py-3 text-right text-ink-soft">{r.order_count}</td>
                            <td className="px-3 py-3 text-right"><Money value={r.system_total} /></td>
                            <td className="px-3 py-3 text-right font-medium">{r.terminal_total == null ? <span className="text-ink-faint">-</span> : <Money value={r.terminal_total} />}</td>
                            <td className="px-3 py-3 text-right font-semibold">
                              {r.difference ? <Money value={r.difference} tone={r.difference < 0 ? "short" : "brass"} /> : <span className="text-ink-faint">-</span>}
                            </td>
                            <td className="px-3 py-3"><StatusCell r={r} /></td>
                            <td className="px-3 py-3">
                              <button aria-expanded={expanded} aria-label={`${expanded ? "Hide" : "Show"} ${r.driver_code} details`}
                                className="rounded-md p-1 text-ink-faint hover:bg-paper-deep hover:text-ink">
                                <Icon name="chevronRight" className={`h-4 w-4 transition-transform ${expanded ? "rotate-90" : ""}`} />
                              </button>
                            </td>
                          </tr>
                          {expanded && (
                            <tr className="border-b border-paper-line bg-paper/50">
                              <td colSpan={8} className="px-5 py-5">
                                <div className="grid gap-6 lg:grid-cols-2">
                                  <Orders day={day} r={r} />
                                  <ReviewBox key={`${r.driver_id}-${r.review?.at ?? ""}`} day={day} r={r} sheet={!!t.sheet} onChanged={changed} />
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                  {!onlyOpen && (
                    <tfoot><tr className="bg-paper/70 font-semibold">
                      <td className="px-5 py-3" colSpan={2}>Day total{t.unpaired ? <span className="block text-xs font-normal text-ink-faint">machines include {fmtMoney(t.unpaired_total ?? 0)} not matched yet</span> : null}</td>
                      <td className="num px-3 py-3 text-right">{t.order_count}</td>
                      <td className="px-3 py-3 text-right"><Money value={t.system_total} /></td>
                      <td className="px-3 py-3 text-right"><Money value={t.sheet ? t.machines_total : t.terminal_total} /></td>
                      <td className="px-3 py-3 text-right">{t.difference ? <Money value={t.difference} tone={t.difference < 0 ? "short" : "brass"} /> : "-"}</td>
                      <td colSpan={2} />
                    </tr></tfoot>
                  )}
                </table>
              </div>
            )}
          </Panel>
        </>
      )}

      {importing === "orders" && (
        <ImportDialog day={day} title="Import the system's POS orders" endpoint="/pos/import/orders" templateUrl="/api/pos/template/orders"
          noun={["order", "orders"]} columns={ORDER_PREVIEW}
          intro="Export the orders closed by POS from your delivery system. Each row needs the order number, the driver ID and the amount. If the file has a payment method column, cash orders are skipped."
          onClose={() => setImporting(null)} onSaved={(dates) => { setImporting(null); if (dates.length === 1) setDay(dates[0]); changed(); }} />
      )}
      {importing === "terminals" && (
        <ImportDialog day={day} title="Import the terminal sheet" endpoint="/pos/import/terminals" templateUrl="/api/pos/template/terminals"
          noun={["terminal total", "terminal totals"]} columns={TERMINAL_PREVIEW}
          intro="One row per POS machine with the day's total, or your own sheet with a POS Code column and the date as the amount column's heading. Each machine is matched to a driver by its registered terminal ID or by the exact amount of his system POS orders; you match the rest by hand."
          onClose={() => setImporting(null)} onSaved={(dates) => { setImporting(null); if (dates.length === 1) setDay(dates[0]); changed(); }} />
      )}
    </>
  );
}
