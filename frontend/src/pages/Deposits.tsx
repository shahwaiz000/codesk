import { FormEvent, Fragment, useState } from "react";
import { todayIso } from "../businessDay";
import { Icon } from "../components/icons";
import SlipReader from "../components/SlipReader";
import { Badge, ErrorBox, FormError, Loading, Modal, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, fmtMoney, parseAmount, send, useApi } from "../lib";
import { useStation } from "../stations";
import type { DepositDay, DepositLedger, DepositStatus, Slip } from "../types";

const TONE: Record<DepositStatus, "leaf" | "brass" | "short" | "muted"> = {
  deposited: "leaf", not_due: "muted", due_today: "brass", overdue: "short", short: "short", over: "brass", nothing: "muted",
};

function DepositDialog({ row, banks, onClose, onSaved }: { row: DepositDay; banks: string[]; onClose: () => void; onSaved: () => void }) {
  const [date, setDate] = useState(todayIso() < row.due_on ? row.date : todayIso());
  const [bank, setBank] = useState(banks[0] ?? "");
  const [slip, setSlip] = useState("");
  const [amount, setAmount] = useState(String(row.left > 0 ? row.left : row.pending));
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const value = parseAmount(amount);
  const after = value != null ? Math.round((row.left - value) * 100) / 100 : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await send("/deposits", "POST", { business_date: row.date, deposit_date: date, bank, slip_ref: slip, amount, note, station_id: row.station_id ?? null });
      onSaved();
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }
  return (
    <Modal title={`Deposit the cash of ${fmtDay(row.date)}${row.station ? `, ${row.station}` : ""}`} onClose={onClose} width="max-w-lg">
      <form onSubmit={submit} className="space-y-4">
        <dl className="-mt-2 grid grid-cols-3 gap-3 rounded-lg bg-paper p-3 text-sm">
          <div><dt className="text-xs text-ink-faint">This day's cash</dt><dd><Money value={row.to_deposit} className="font-semibold" /></dd></div>
          <div><dt className="text-xs text-ink-faint">From earlier days</dt><dd><Money value={row.left - row.pending} className="font-semibold" /></dd></div>
          <div><dt className="text-xs text-ink-faint">Left to deposit</dt><dd><Money value={row.left} tone="brass" className="font-semibold" /></dd></div>
        </dl>
        {row.left > row.pending && <p className="-mt-1 text-xs text-ink-faint">The slip pays this day first; anything more pays the oldest day still short.</p>}
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium">Bank
            <input className="field" list="bank-list" value={bank} onChange={(e) => setBank(e.target.value)} />
            <datalist id="bank-list">{banks.map((b) => <option key={b} value={b} />)}</datalist></label>
          <label className="block text-sm font-medium">Deposit slip no.
            <input className="field num uppercase" value={slip} maxLength={60} onChange={(e) => setSlip(e.target.value)} placeholder="DS-000000" /></label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium">Deposit date
            <input type="date" className="field" value={date} min={row.date} max={todayIso()} onChange={(e) => setDate(e.target.value)} /></label>
          <label className="block text-sm font-medium">Slip amount (SAR)
            <input className="field num text-right" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        </div>
        {after != null && after > 0 && <p className="rounded-md bg-brass-soft px-3 py-2 text-sm text-brass-dark">After this slip, <span className="num font-semibold">{fmtMoney(after)}</span> SAR will still be left to deposit.</p>}
        {date > row.due_on && <p className="text-xs text-ink-faint">This deposit is after the due day ({fmtDay(row.due_on)}), so the day will be marked late.</p>}
        <label className="block text-sm font-medium">Note
          <input className="field" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="Optional" /></label>
        <FormError message={error} />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-quiet">Cancel</button>
          <button disabled={busy || bank.trim().length < 2 || slip.trim().length < 2 || !value || value <= 0} className="btn-primary">Save deposit</button>
        </div>
      </form>
    </Modal>
  );
}

function Slips({ row, onDelete }: { row: DepositDay; onDelete: (s: Slip) => void }) {
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <div>
        {row.slips.length === 0 ? <p className="text-sm text-ink-soft">No deposit slip recorded for this day yet.</p> : (
          <table className="w-full rounded-lg bg-white text-sm shadow-panel">
            <thead className="text-left text-xs text-ink-faint"><tr>
              <th className="px-3 py-2 font-medium">Slip</th><th className="px-3 py-2 font-medium">Bank</th><th className="px-3 py-2 font-medium">Deposited on</th>
              <th className="px-3 py-2 text-right font-medium">Amount</th><th className="px-3 py-2"><span className="sr-only">Delete</span></th>
            </tr></thead>
            <tbody>
              {row.slips.map((s) => (
                <tr key={s.id} className="border-t border-paper-line">
                  <td className="num px-3 py-2 font-medium">{s.slip_ref}</td>
                  <td className="px-3 py-2 text-ink-soft">{s.bank}</td>
                  <td className="px-3 py-2 text-ink-soft">{fmtDay(s.deposit_date)}{s.deposit_date > row.due_on && <span className="ml-1.5 text-xs text-short">late</span>}</td>
                  <td className="px-3 py-2 text-right"><Money value={s.amount} /></td>
                  <td className="px-3 py-2 text-right"><button onClick={() => onDelete(s)} aria-label={`Delete slip ${s.slip_ref}`} className="rounded-md p-1 text-ink-faint hover:bg-short-soft hover:text-short"><Icon name="trash" className="h-4 w-4" /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <dl className="space-y-1.5 text-sm">
        <div className="flex justify-between"><dt className="text-ink-soft">Cash received from drivers</dt><dd><Money value={row.cash_received} /></dd></div>
        <div className="flex justify-between"><dt className="text-ink-soft">Paid out (expenses, advances)</dt><dd><Money value={-row.paid_out} /></dd></div>
        {row.returned > 0 && <div className="flex justify-between"><dt className="text-ink-soft">Advances returned in cash</dt><dd><Money value={row.returned} /></dd></div>}
        <div className="flex justify-between border-t border-paper-line pt-1.5 font-semibold"><dt>Cash to deposit</dt><dd><Money value={row.to_deposit} /></dd></div>
        <div className="flex justify-between"><dt className="text-ink-soft">Deposited</dt><dd><Money value={-row.deposited} /></dd></div>
        <div className="flex justify-between border-t border-paper-line pt-1.5 font-semibold"><dt>This day still owes</dt><dd><Money value={row.pending} tone={row.pending > 0 ? "short" : "leaf"} /></dd></div>
        {row.paid_later_on && <div className="text-xs text-leaf-dark">Short amount paid with a later slip on {fmtDay(row.paid_later_on)}</div>}
        <div className="mt-2 space-y-1.5 rounded-lg bg-paper p-2.5">
          <div className="flex justify-between"><dt className="text-ink-soft">Left from earlier days</dt><dd><Money value={row.brought_forward} /></dd></div>
          <div className="flex justify-between"><dt className="text-ink-soft">Total to deposit</dt><dd><Money value={row.total_due} /></dd></div>
          <div className="flex justify-between font-semibold"><dt>Left after this day</dt><dd><Money value={row.left} tone={row.left > 0 ? "brass" : "leaf"} /></dd></div>
        </div>
        {!!row.rounding && <div className="flex justify-between text-xs text-ink-faint"><dt>Rounded to whole notes</dt><dd><Money value={row.rounding} tone="muted" /></dd></div>}
      </dl>
    </div>
  );
}

export default function Deposits() {
  const [version, setVersion] = useState(0);
  const [end, setEnd] = useState(todayIso());
  const { data, error, loading, reload } = useApi<DepositLedger>(`/deposits?count=30&end=${end}&v=${version}`);
  const { station } = useStation();
  const [open, setOpen] = useState<string | null>(null);
  const [depositing, setDepositing] = useState<DepositDay | null>(null);
  const [deleting, setDeleting] = useState<Slip | null>(null);
  const [onlyPending, setOnlyPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const changed = () => setVersion((v) => v + 1);
  const t = data?.totals;
  const rows = (data?.rows ?? []).filter((r) => !onlyPending || r.pending !== 0);
  const all = data?.rows ?? [];
  const days = (list: DepositDay[]) => {  // "Thu 29 Oct" or "Mon 26 Oct, Tue 27 Oct and 2 more"
    const d = [...new Set(list.map((r) => r.date))].sort();
    return d.length ? d.slice(0, 2).map((x) => fmtDay(x)).join(", ") + (d.length > 2 ? ` and ${d.length - 2} more` : "") : "";
  };
  const holding = all.filter((r) => r.pending > 0);
  const dueToday = all.filter((r) => r.status === "due_today");
  const notDue = all.filter((r) => r.status === "not_due");
  const late = all.filter((r) => r.status === "overdue" || r.status === "short");
  const inWindow = [...all].map((r) => r.date).sort();
  const from = inWindow[0], to = inWindow[inWindow.length - 1];

  async function confirmDelete() {
    if (!deleting) return;
    try { await send(`/deposits/${deleting.id}`, "DELETE"); setDeleting(null); changed(); }
    catch (e) { setActionError((e as Error).message); setDeleting(null); }
  }

  return (
    <>
      <PageHeader title="Bank deposits" subtitle={`${station ? `${station.name}: ` : "Each station deposits its own cash. "}Each day's cash goes to the bank on the next working day. A day's cash is the cash received from drivers, minus expenses and advances paid out, plus advances returned in cash. Anything not deposited is carried to the next day, like a bank statement.`} />
      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && t && (
        <>
          <dl className="mb-6 grid grid-cols-2 overflow-hidden rounded-panel bg-white shadow-panel lg:grid-cols-4 [&>div]:border-paper-line max-lg:[&>div:nth-child(-n+2)]:border-b max-lg:[&>div:nth-child(odd)]:border-r lg:[&>div:not(:last-child)]:border-r">
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Cash on hand</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={t.cash_on_hand} /> <span className="text-sm font-normal text-ink-faint">SAR</span></dd>
              <dd className="mt-1 text-xs text-ink-faint">{holding.length ? <>Not yet in the bank: cash of {days(holding)}</> : "Everything is in the bank"}</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Due today</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={t.due_today} tone={t.due_today ? "brass" : undefined} /></dd>
              <dd className="mt-1 text-xs text-ink-faint">{dueToday.length ? <>Cash of {days(dueToday)}</> : "Nothing due today"}
                {notDue.length > 0 && <> · <span className="num">{fmtMoney(t.not_due)}</span> of {days(notDue)} due {fmtDay(notDue[0].due_on)}</>}</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Overdue or short</dt>
              <dd className={`mt-1 text-[22px] font-semibold ${t.overdue + t.short ? "text-short" : "text-leaf-dark"}`}><Money value={t.overdue + t.short} tone={t.overdue + t.short ? "short" : "leaf"} /></dd>
              <dd className={`mt-1 text-xs ${late.length ? "text-short" : "text-ink-faint"}`}>{late.length ? <>Cash of {days(late)}</> : "Nothing late"}</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Deposited{from ? <>, {fmtDay(from)} to {fmtDay(to)}</> : ""}</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={t.deposited} /></dd>
              <dd className="mt-1 text-xs text-ink-faint">{t.late_days ? `${t.late_days} ${t.late_days === 1 ? "day" : "days"} deposited late` : "All on time"}</dd>
            </div>
          </dl>

          <SlipReader days={data.rows} onRecorded={changed} />

          <Panel flush title={from ? `Day by day: ${fmtDay(from)} to ${fmtDay(to, true)}` : "Day by day"}
            action={<div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 text-sm text-ink-soft">Show up to
                <input type="date" className="field mt-0 w-auto py-1" value={end} max={todayIso()} onChange={(e) => e.target.value && setEnd(e.target.value)} /></label>
              <label className="flex items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" className="h-4 w-4 accent-ledger-700" checked={onlyPending} onChange={(e) => setOnlyPending(e.target.checked)} />Only days with money pending</label>
            </div>}>
            {actionError && <div className="px-5 pt-3"><FormError message={actionError} /></div>}
            <div className="relative overflow-x-auto">
              <table className="w-full min-w-[1220px] text-sm">
                <thead><tr className="border-b border-paper-line text-left text-xs text-ink-faint">
                  <th className="px-5 py-2.5 font-medium">Cash of</th>
                  <th className="px-3 py-2.5 text-right font-medium">Cash received</th>
                  <th className="px-3 py-2.5 text-right font-medium">Paid out</th>
                  <th className="px-3 py-2.5 text-right font-medium">Day's cash</th>
                  <th className="px-3 py-2.5 text-right font-medium">From before</th>
                  <th className="px-3 py-2.5 text-right font-medium">Total to deposit</th>
                  <th className="px-3 py-2.5 text-right font-medium">Deposited</th>
                  <th className="px-3 py-2.5 font-medium">Deposited on</th>
                  <th className="px-3 py-2.5 text-right font-medium" title="What is still not in the bank after this day, this day's and earlier days'">Left</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-5 py-2.5"><span className="sr-only">Actions</span></th>
                </tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const key = `${r.date}-${r.station_id ?? ""}`;
                    const expanded = open === key;
                    const attention = r.status === "overdue" || r.status === "short";
                    return (
                      <Fragment key={key}>
                        <tr onClick={() => setOpen(expanded ? null : key)}
                          className={`cursor-pointer border-b border-paper-line hover:bg-paper/60 ${attention ? "bg-short-soft/40" : ""} ${expanded ? "bg-paper/80" : ""}`}>
                          <td className="px-5 py-3">
                            <span className="font-medium">{fmtDay(r.date)}</span>
                            {!station && r.station && <span className="ml-2 inline-flex items-center gap-1 align-middle text-xs text-ink-soft"><Icon name="pin" className="h-3 w-3 text-brass-dark" />{r.station}</span>}
                            <span className="block text-xs text-ink-faint">Due {fmtDay(r.due_on)}{r.slips.length > 1 ? `, ${r.slips.length} slips` : ""}</span>
                          </td>
                          <td className="px-3 py-3 text-right"><Money value={r.cash_received} /></td>
                          <td className="px-3 py-3 text-right"><Money value={r.paid_out - r.returned} tone="muted" /></td>
                          <td className="px-3 py-3 text-right"><Money value={r.to_deposit} /></td>
                          <td className="px-3 py-3 text-right">{r.brought_forward ? <Money value={r.brought_forward} tone="brass" /> : <span className="text-ink-faint">-</span>}</td>
                          <td className="px-3 py-3 text-right font-medium"><Money value={r.total_due} /></td>
                          <td className="px-3 py-3 text-right"><Money value={r.deposited} /></td>
                          <td className="px-3 py-3 text-xs text-ink-soft">
                            {r.slips.length ? [...new Set(r.slips.map((x) => x.deposit_date))].map((x) => fmtDay(x)).join(", ") : <span className="text-ink-faint">Not yet</span>}
                            {r.paid_later_on && <span className="block text-leaf-dark">short paid {fmtDay(r.paid_later_on)}</span>}
                          </td>
                          <td className="px-3 py-3 text-right font-semibold">{r.left > 0 ? <Money value={r.left} tone={attention ? "short" : "brass"} />
                            : r.rounding ? <span className="text-xs font-normal text-ink-faint" title="Cash goes to the bank in whole notes">rounded {r.rounding > 0 ? "+" : ""}{fmtMoney(r.rounding)}</span>
                            : <span className="text-ink-faint">0.00</span>}</td>
                          <td className="px-3 py-3">
                            <span className="flex flex-wrap items-center gap-1.5">
                              <Badge tone={TONE[r.status]}>{r.status_text}</Badge>
                              {r.late && <Badge tone="short">{r.days_late} {r.days_late === 1 ? "day" : "days"} late</Badge>}
                            </span>
                          </td>
                          <td className="px-5 py-3 text-right">
                            {r.pending > 0 && (
                              <button onClick={(e) => { e.stopPropagation(); setDepositing(r); }} className={`${r.status === "not_due" ? "btn-quiet" : "btn-primary"} px-3 py-1.5 text-xs`}>Record deposit</button>
                            )}
                          </td>
                        </tr>
                        {expanded && (
                          <tr className="border-b border-paper-line bg-paper/50">
                            <td colSpan={11} className="px-5 py-5"><Slips row={r} onDelete={setDeleting} /></td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
      {depositing && data && (
        <DepositDialog row={depositing} banks={data.banks} onClose={() => setDepositing(null)} onSaved={() => { setDepositing(null); changed(); }} />
      )}
      {deleting && (
        <Modal title={`Delete slip ${deleting.slip_ref}?`} onClose={() => setDeleting(null)}>
          <p className="text-sm text-ink-soft">{fmtMoney(deleting.amount)} SAR at {deleting.bank} on {fmtDay(deleting.deposit_date, true)}. The day will show this amount as pending again, and the deletion is written to the activity log.</p>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setDeleting(null)} className="btn-quiet">Keep it</button>
            <button onClick={confirmDelete} className="btn-danger">Delete slip</button>
          </div>
        </Modal>
      )}
    </>
  );
}
