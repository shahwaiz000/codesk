import { FormEvent, useState } from "react";
import { todayIso, useBusinessDay } from "../businessDay";
import DayPicker from "../components/DayPicker";
import { Icon } from "../components/icons";
import { Badge, Empty, ErrorBox, FormError, Loading, Modal, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, fmtMoney, parseAmount, send, useApi } from "../lib";
import type { Advances, Driver, ExpenseDay, ExpenseRow } from "../types";

const CATEGORIES = [
  { value: "fuel", text: "Fuel" }, { value: "toll", text: "Toll" }, { value: "parking", text: "Parking" },
  { value: "travel", text: "Travel" }, { value: "maintenance", text: "Maintenance" }, { value: "other", text: "Other" },
];

function ExpenseDialog({ day, expense, drivers, onClose, onSaved }: {
  day: string; expense: ExpenseRow | null; drivers: Driver[]; onClose: () => void; onSaved: () => void;
}) {
  const [kind, setKind] = useState<"expense" | "advance">(expense?.category === "advance" ? "advance" : "expense");
  const [driverId, setDriverId] = useState<number | "">(expense?.driver_id ?? "");
  const [category, setCategory] = useState(expense && expense.category !== "advance" ? expense.category : "fuel");
  const [amount, setAmount] = useState(expense ? String(expense.amount) : "");
  const [reference, setReference] = useState(expense?.reference ?? "");
  const [note, setNote] = useState(expense?.note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ready = driverId !== "" && (parseAmount(amount) ?? 0) > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    const body = { business_date: expense?.business_date ?? day, driver_id: driverId, category: kind === "advance" ? "advance" : category, amount, reference, note };
    try {
      if (expense) await send(`/expenses/${expense.id}`, "PUT", body);
      else await send("/expenses", "POST", body);
      onSaved();
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }

  const options = drivers.filter((d) => d.active || d.id === expense?.driver_id);
  return (
    <Modal title={expense ? "Correct a payment" : "Pay out from today's cash"} onClose={onClose} width="max-w-lg">
      <form onSubmit={submit} className="space-y-4">
        <p className="-mt-3 text-sm text-ink-soft">Business date {fmtDay(expense?.business_date ?? day, true)}. This amount is taken out of the day's cash to deposit.</p>
        <div role="radiogroup" aria-label="Type" className="grid grid-cols-2 gap-1 rounded-lg bg-paper-deep p-1">
          {(["expense", "advance"] as const).map((k) => (
            <button type="button" role="radio" aria-checked={kind === k} key={k} onClick={() => setKind(k)}
              className={`rounded-md py-2 text-sm font-medium transition-colors ${kind === k ? "bg-white text-ink shadow-panel" : "text-ink-soft hover:text-ink"}`}>
              {k === "expense" ? "Travel expense" : "Advance to driver"}</button>
          ))}
        </div>
        <div className="grid grid-cols-[1fr_9rem] gap-3">
          <label className="block text-sm font-medium">Driver
            <select className="field" value={driverId} onChange={(e) => setDriverId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Choose a driver</option>
              {options.map((d) => <option key={d.id} value={d.id}>{d.code}  {d.name}</option>)}
            </select></label>
          <label className="block text-sm font-medium">Amount (SAR)
            <input className="field num text-right" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" /></label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {kind === "expense" ? (
            <label className="block text-sm font-medium">Category
              <select className="field" value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.text}</option>)}
              </select></label>
          ) : <p className="self-end pb-2 text-xs text-ink-faint">The advance stays open until it is recovered from salary or returned in cash.</p>}
          <label className="block text-sm font-medium">Receipt or voucher no.
            <input className="field" value={reference} maxLength={60} onChange={(e) => setReference(e.target.value)} placeholder="Optional" /></label>
        </div>
        <label className="block text-sm font-medium">Note
          <input className="field" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder={kind === "advance" ? "e.g. trip to Makkah" : "Optional"} /></label>
        <FormError message={error} />
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="btn-quiet">Cancel</button>
          <button disabled={busy || !ready} className="btn-primary">{expense ? "Save correction" : kind === "advance" ? "Give advance" : "Save expense"}</button>
        </div>
      </form>
    </Modal>
  );
}

function SettleDialog({ advance, onClose, onSaved }: { advance: ExpenseRow; onClose: () => void; onSaved: () => void }) {
  const [date, setDate] = useState(todayIso());
  const [method, setMethod] = useState<"salary" | "cash">("salary");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try { await send(`/advances/${advance.id}/settle`, "POST", { settled_on: date, method, note }); onSaved(); }
    catch (err) { setError((err as Error).message); setBusy(false); }
  }
  return (
    <Modal title={`Recover ${advance.driver_code}'s advance`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <p className="-mt-3 text-sm text-ink-soft"><Money value={advance.amount} className="font-semibold text-ink" /> SAR given to {advance.driver_name} on {fmtDay(advance.business_date, true)}.</p>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">How did it come back?</legend>
          {([["salary", "Deducted from salary", "Nothing comes back to the desk."], ["cash", "Cash returned at the desk", "Added to the cash to deposit on the recovery date."]] as const).map(([v, label, hint]) => (
            <label key={v} className={`flex cursor-pointer gap-3 rounded-lg border p-3 text-sm ${method === v ? "border-leaf bg-leaf-soft/50" : "border-paper-line"}`}>
              <input type="radio" name="method" className="mt-0.5 accent-ledger-700" checked={method === v} onChange={() => setMethod(v)} />
              <span><span className="block font-medium">{label}</span><span className="text-ink-soft">{hint}</span></span>
            </label>
          ))}
        </fieldset>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium">Recovery date
            <input type="date" className="field" value={date} min={advance.business_date} max={todayIso()} onChange={(e) => setDate(e.target.value)} /></label>
          <label className="block text-sm font-medium">Note
            <input className="field" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="Optional" /></label>
        </div>
        <FormError message={error} />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-quiet">Cancel</button>
          <button disabled={busy || !date} className="btn-primary">Mark recovered</button>
        </div>
      </form>
    </Modal>
  );
}

function AdvancesPanel({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const [showAll, setShowAll] = useState(false);
  const { data, error, reload } = useApi<Advances>(`/advances?status=${showAll ? "all" : "open"}&r=${refreshKey}`);
  const [settling, setSettling] = useState<ExpenseRow | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function reopen(a: ExpenseRow) {
    setActionError(null);
    try { await send(`/advances/${a.id}/reopen`, "POST"); onChanged(); reload(); } catch (e) { setActionError((e as Error).message); }
  }
  return (
    <Panel flush title="Open advances" className="self-start"
      action={<label className="flex items-center gap-2 text-sm text-ink-soft">
        <input type="checkbox" className="h-4 w-4 accent-ledger-700" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />Show recovered</label>}>
      {error ? <div className="p-5"><ErrorBox message={error} retry={reload} /></div> : !data ? <Loading /> : (
        <>
          <div className="border-b border-paper-line px-5 py-4">
            <p className="text-2xl font-semibold"><Money value={data.open_total} tone={data.open_total ? "brass" : undefined} /> <span className="text-sm font-normal text-ink-faint">SAR</span></p>
            <p className="text-xs text-ink-faint">{data.open_count ? `${data.open_count} open, ${data.drivers} ${data.drivers === 1 ? "driver" : "drivers"}` : "Every advance is recovered"}</p>
          </div>
          {actionError && <div className="px-5 pt-3"><FormError message={actionError} /></div>}
          <ul className="max-h-[28rem] divide-y divide-paper-line overflow-y-auto">
            {data.rows.map((a) => (
              <li key={a.id} className="flex items-center gap-3 px-5 py-3 text-sm">
                <div className="min-w-0 flex-1">
                  <p><span className="num mr-1.5 font-semibold text-ink-soft">{a.driver_code}</span><span className="font-medium">{a.driver_name}</span></p>
                  <p className="text-xs text-ink-faint">
                    Given {fmtDay(a.business_date)}{a.settled_on
                      ? `, recovered ${fmtDay(a.settled_on)} by ${a.settlement_method === "cash" ? "cash" : "salary"}`
                      : `, ${a.days_open} ${a.days_open === 1 ? "day" : "days"} open`}
                  </p>
                </div>
                <Money value={a.amount} tone={a.settled_on ? "muted" : "brass"} className="font-semibold" />
                {a.settled_on
                  ? <button onClick={() => reopen(a)} className="rounded-md px-2 py-1 text-xs font-medium text-ink-soft hover:bg-paper-deep">Reopen</button>
                  : <button onClick={() => setSettling(a)} className="btn-quiet px-2.5 py-1 text-xs">Recover</button>}
              </li>
            ))}
          </ul>
        </>
      )}
      {settling && <SettleDialog advance={settling} onClose={() => setSettling(null)} onSaved={() => { setSettling(null); onChanged(); reload(); }} />}
    </Panel>
  );
}

export default function Expenses() {
  const { day } = useBusinessDay();
  const [version, setVersion] = useState(0);
  const { data, error, loading, reload } = useApi<ExpenseDay>(`/expenses?date=${day}&v=${version}`);
  const drivers = useApi<Driver[]>("/drivers");
  const [dialog, setDialog] = useState<{ expense: ExpenseRow | null } | null>(null);
  const [deleting, setDeleting] = useState<ExpenseRow | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const changed = () => setVersion((v) => v + 1);
  const t = data?.totals;

  async function confirmDelete() {
    if (!deleting) return;
    try { await send(`/expenses/${deleting.id}`, "DELETE"); setDeleting(null); changed(); }
    catch (e) { setActionError((e as Error).message); setDeleting(null); }
  }

  return (
    <>
      <PageHeader title="Expenses & advances" subtitle="Travel expenses and advances paid to drivers out of the day's cash. Everything here lowers that day's cash to deposit.">
        <button onClick={() => setDialog({ expense: null })} className="btn-primary"><Icon name="plus" className="h-4 w-4" />Pay out</button>
      </PageHeader>
      <DayPicker refreshKey={version} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && t && (
            <Panel flush title={`Paid out on ${fmtDay(day)}`}
              action={<span className="text-sm text-ink-soft">Total <Money value={t.total} className="font-semibold text-ink" /> SAR</span>}>
              {t.by_category.length > 0 && (
                <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-paper-line px-5 py-3 text-sm">
                  {t.by_category.map((c) => (
                    <span key={c.category} className="text-ink-soft">{c.category_text} <Money value={c.amount} className={`font-medium ${c.category === "advance" ? "text-brass-dark" : "text-ink"}`} /></span>
                  ))}
                </div>
              )}
              {actionError && <div className="px-5 pt-3"><FormError message={actionError} /></div>}
              {data.rows.length === 0 ? (
                <Empty title="Nothing paid out on this day" hint="Record fuel, tolls, parking or travel money, or an advance, when you hand cash to a driver.">
                  <button onClick={() => setDialog({ expense: null })} className="btn-primary">Pay out</button>
                </Empty>
              ) : (
                <div className="relative overflow-x-auto">
                  <table className="w-full min-w-[640px] text-sm">
                    <thead><tr className="border-b border-paper-line text-left text-xs text-ink-faint">
                      <th className="px-5 py-2.5 font-medium">Driver</th><th className="px-3 py-2.5 font-medium">Type</th>
                      <th className="px-3 py-2.5 font-medium">Receipt</th><th className="px-3 py-2.5 text-right font-medium">Amount (SAR)</th>
                      <th className="px-5 py-2.5"><span className="sr-only">Actions</span></th>
                    </tr></thead>
                    <tbody>
                      {data.rows.map((e) => (
                        <tr key={e.id} className="border-b border-paper-line last:border-0 hover:bg-paper/60">
                          <td className="px-5 py-3"><span className="num mr-2 font-semibold text-ink-soft">{e.driver_code}</span><span className="font-medium">{e.driver_name}</span>
                            {e.note && <span className="block text-xs text-ink-faint">{e.note}</span>}</td>
                          <td className="px-3 py-3">
                            {e.category === "advance"
                              ? <span className="flex flex-wrap items-center gap-1.5"><Badge tone="brass">Advance</Badge>{e.settled_on && <Badge tone="leaf">Recovered</Badge>}</span>
                              : <span className="text-ink-soft">{e.category_text}</span>}
                          </td>
                          <td className="num px-3 py-3 text-ink-soft">{e.reference || "-"}</td>
                          <td className="px-3 py-3 text-right font-medium"><Money value={e.amount} /></td>
                          <td className="px-5 py-3">
                            {!e.settled_on && (
                              <div className="flex justify-end gap-1">
                                <button onClick={() => setDialog({ expense: e })} className="rounded-md px-2 py-1 text-xs font-medium text-ink-soft hover:bg-paper-deep hover:text-ink">Correct</button>
                                <button onClick={() => setDeleting(e)} aria-label={`Delete ${e.category_text} for ${e.driver_code}`} className="rounded-md p-1 text-ink-faint hover:bg-short-soft hover:text-short"><Icon name="trash" className="h-4 w-4" /></button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          )}
        </div>
        <AdvancesPanel refreshKey={version} onChanged={changed} />
      </div>

      {dialog && drivers.data && (
        <ExpenseDialog day={day} expense={dialog.expense} drivers={drivers.data}
          onClose={() => setDialog(null)} onSaved={() => { setDialog(null); changed(); }} />
      )}
      {deleting && (
        <Modal title="Delete this payment?" onClose={() => setDeleting(null)}>
          <p className="text-sm text-ink-soft">{deleting.category_text} of {fmtMoney(deleting.amount)} SAR for {deleting.driver_code} {deleting.driver_name} on {fmtDay(deleting.business_date, true)}. The deletion is written to the activity log.</p>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setDeleting(null)} className="btn-quiet">Keep it</button>
            <button onClick={confirmDelete} className="btn-danger">Delete payment</button>
          </div>
        </Modal>
      )}
    </>
  );
}
