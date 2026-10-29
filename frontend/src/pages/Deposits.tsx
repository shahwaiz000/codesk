import { FormEvent, Fragment, useState } from "react";
import { todayIso } from "../businessDay";
import { Icon } from "../components/icons";
import { Badge, ErrorBox, FormError, Loading, Modal, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, fmtMoney, parseAmount, send, useApi } from "../lib";
import type { DepositDay, DepositLedger, DepositStatus, Slip } from "../types";

const TONE: Record<DepositStatus, "leaf" | "brass" | "short" | "muted"> = {
  deposited: "leaf", not_due: "muted", due_today: "brass", overdue: "short", short: "short", over: "brass", nothing: "muted",
};

function DepositDialog({ row, banks, onClose, onSaved }: { row: DepositDay; banks: string[]; onClose: () => void; onSaved: () => void }) {
  const [date, setDate] = useState(todayIso() < row.due_on ? row.date : todayIso());
  const [bank, setBank] = useState(banks[0] ?? "");
  const [slip, setSlip] = useState("");
  const [amount, setAmount] = useState(String(row.pending));
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const value = parseAmount(amount);
  const after = value != null ? Math.round((row.pending - value) * 100) / 100 : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await send("/deposits", "POST", { business_date: row.date, deposit_date: date, bank, slip_ref: slip, amount, note });
      onSaved();
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }
  return (
    <Modal title={`Deposit the cash of ${fmtDay(row.date)}`} onClose={onClose} width="max-w-lg">
      <form onSubmit={submit} className="space-y-4">
        <dl className="-mt-2 grid grid-cols-3 gap-3 rounded-lg bg-paper p-3 text-sm">
          <div><dt className="text-xs text-ink-faint">To deposit</dt><dd><Money value={row.to_deposit} className="font-semibold" /></dd></div>
          <div><dt className="text-xs text-ink-faint">Already deposited</dt><dd><Money value={row.deposited} className="font-semibold" /></dd></div>
          <div><dt className="text-xs text-ink-faint">Still pending</dt><dd><Money value={row.pending} tone="brass" className="font-semibold" /></dd></div>
        </dl>
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
        {after != null && after > 0 && <p className="rounded-md bg-brass-soft px-3 py-2 text-sm text-brass-dark">After this slip, <span className="num font-semibold">{fmtMoney(after)}</span> SAR will still be pending for this day.</p>}
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
        <div className="flex justify-between border-t border-paper-line pt-1.5 font-semibold"><dt>Pending</dt><dd><Money value={row.pending} tone={row.pending > 0 ? "short" : "leaf"} /></dd></div>
        {!!row.rounding && <div className="flex justify-between text-xs text-ink-faint"><dt>Rounded to whole notes</dt><dd><Money value={row.rounding} tone="muted" /></dd></div>}
      </dl>
    </div>
  );
}

export default function Deposits() {
  const [version, setVersion] = useState(0);
  const { data, error, loading, reload } = useApi<DepositLedger>(`/deposits?count=30&v=${version}`);
  const [open, setOpen] = useState<string | null>(null);
  const [depositing, setDepositing] = useState<DepositDay | null>(null);
  const [deleting, setDeleting] = useState<Slip | null>(null);
  const [onlyPending, setOnlyPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const changed = () => setVersion((v) => v + 1);
  const t = data?.totals;
  const rows = (data?.rows ?? []).filter((r) => !onlyPending || r.pending !== 0);

  async function confirmDelete() {
    if (!deleting) return;
    try { await send(`/deposits/${deleting.id}`, "DELETE"); setDeleting(null); changed(); }
    catch (e) { setActionError((e as Error).message); setDeleting(null); }
  }

  return (
    <>
      <PageHeader title="Bank deposits" subtitle="Each day's cash goes to the bank on the next working day. Cash to deposit is the cash received from drivers, minus expenses and advances paid out, plus advances returned in cash." />
      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && t && (
        <>
          <dl className="mb-6 grid grid-cols-2 overflow-hidden rounded-panel bg-white shadow-panel lg:grid-cols-4 [&>div]:border-paper-line max-lg:[&>div:nth-child(-n+2)]:border-b max-lg:[&>div:nth-child(odd)]:border-r lg:[&>div:not(:last-child)]:border-r">
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Cash on hand</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={t.cash_on_hand} /> <span className="text-sm font-normal text-ink-faint">SAR</span></dd>
              <dd className="mt-1 text-xs text-ink-faint">Not yet in the bank</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Due today</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={t.due_today} tone={t.due_today ? "brass" : undefined} /></dd>
              <dd className="mt-1 text-xs text-ink-faint">{t.not_due ? <>Plus <span className="num">{fmtMoney(t.not_due)}</span> due on the next working day</> : "Yesterday's cash"}</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Overdue or short</dt>
              <dd className={`mt-1 text-[22px] font-semibold ${t.overdue + t.short ? "text-short" : "text-leaf-dark"}`}><Money value={t.overdue + t.short} tone={t.overdue + t.short ? "short" : "leaf"} /></dd>
              <dd className="mt-1 text-xs text-ink-faint">{t.overdue_days + t.short_days ? [t.overdue_days && `${t.overdue_days} overdue`, t.short_days && `${t.short_days} short`].filter(Boolean).join(", ") + (t.overdue_days + t.short_days === 1 ? " day" : " days") : "Nothing late"}</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Deposited, last 30 working days</dt>
              <dd className="mt-1 text-[22px] font-semibold"><Money value={t.deposited} /></dd>
              <dd className="mt-1 text-xs text-ink-faint">{t.late_days ? `${t.late_days} ${t.late_days === 1 ? "day" : "days"} deposited late` : "All on time"}</dd>
            </div>
          </dl>

          <Panel flush title="Day by day"
            action={<label className="flex items-center gap-2 text-sm text-ink-soft">
              <input type="checkbox" className="h-4 w-4 accent-ledger-700" checked={onlyPending} onChange={(e) => setOnlyPending(e.target.checked)} />Only days with money pending</label>}>
            {actionError && <div className="px-5 pt-3"><FormError message={actionError} /></div>}
            <div className="relative overflow-x-auto">
              <table className="w-full min-w-[980px] text-sm">
                <thead><tr className="border-b border-paper-line text-left text-xs text-ink-faint">
                  <th className="px-5 py-2.5 font-medium">Business day</th>
                  <th className="px-3 py-2.5 text-right font-medium">Cash received</th>
                  <th className="px-3 py-2.5 text-right font-medium">Paid out</th>
                  <th className="px-3 py-2.5 text-right font-medium">To deposit</th>
                  <th className="px-3 py-2.5 text-right font-medium">Deposited</th>
                  <th className="px-3 py-2.5 text-right font-medium">Pending</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-5 py-2.5"><span className="sr-only">Actions</span></th>
                </tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const expanded = open === r.date;
                    const attention = r.status === "overdue" || r.status === "short";
                    return (
                      <Fragment key={r.date}>
                        <tr onClick={() => setOpen(expanded ? null : r.date)}
                          className={`cursor-pointer border-b border-paper-line hover:bg-paper/60 ${attention ? "bg-short-soft/40" : ""} ${expanded ? "bg-paper/80" : ""}`}>
                          <td className="px-5 py-3">
                            <span className="font-medium">{fmtDay(r.date)}</span>
                            <span className="block text-xs text-ink-faint">Due {fmtDay(r.due_on)}{r.slips.length > 1 ? `, ${r.slips.length} slips` : ""}</span>
                          </td>
                          <td className="px-3 py-3 text-right"><Money value={r.cash_received} /></td>
                          <td className="px-3 py-3 text-right"><Money value={r.paid_out - r.returned} tone="muted" /></td>
                          <td className="px-3 py-3 text-right font-medium"><Money value={r.to_deposit} /></td>
                          <td className="px-3 py-3 text-right"><Money value={r.deposited} /></td>
                          <td className="px-3 py-3 text-right font-semibold">{r.pending ? <Money value={r.pending} tone={attention ? "short" : "brass"} />
                            : r.rounding ? <span className="text-xs font-normal text-ink-faint" title="Cash goes to the bank in whole notes">rounded {r.rounding > 0 ? "+" : ""}{fmtMoney(r.rounding)}</span>
                            : <span className="text-ink-faint">-</span>}</td>
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
                            <td colSpan={8} className="px-5 py-5"><Slips row={r} onDelete={setDeleting} /></td>
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
