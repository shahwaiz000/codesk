import { FormEvent, useEffect, useState } from "react";
import { todayIso, useBusinessDay } from "../businessDay";
import DayPicker from "../components/DayPicker";
import { Icon } from "../components/icons";
import ImportDialog, { money, PreviewRow } from "../components/ImportDialog";
import { useCountUp } from "../components/VanArt";
import { Badge, Empty, ErrorBox, FormError, Loading, Modal, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, fmtMoney, parseAmount, send, useApi } from "../lib";
import type { Advances, DepositLedger, Driver, ExpenseDay, ExpenseRow, Unusual } from "../types";

const CATEGORIES = [
  { value: "fuel", text: "Fuel" }, { value: "toll", text: "Toll" }, { value: "parking", text: "Parking" },
  { value: "travel", text: "Travel" }, { value: "maintenance", text: "Maintenance" }, { value: "other", text: "Other" },
];

function ExpenseDialog({ day, expense, drivers, onClose, onSaved }: {
  day: string; expense: ExpenseRow | null; drivers: Driver[]; onClose: () => void; onSaved: () => void;
}) {
  const [kind, setKind] = useState<"expense" | "advance">(expense?.category === "advance" ? "advance" : "expense");
  const [driverId, setDriverId] = useState<number | "">(expense?.driver_id ?? "");
  const [category, setCategory] = useState(expense && expense.category !== "advance" ? expense.category : "expense");
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

/** Pay envelopes leaving the CODesk cash box for the drivers, each tagged with what it pays for. */
function PayEnvelopes({ labels, drivers }: { labels: string[]; drivers: number }) {
  const [sent, setSent] = useState(false);
  useEffect(() => { const id = requestAnimationFrame(() => setSent(true)); return () => cancelAnimationFrame(id); }, []);
  const tags = (labels.length ? labels : ["Paid"]).slice(0, 3);
  const spots = [{ x: 168, y: 96, r: -10 }, { x: 234, y: 58, r: 4 }, { x: 294, y: 98, r: 12 }];
  const people = [{ x: 318, s: 0.82, c: "#1d7a55" }, { x: 351, s: 0.92, c: "#145c3f" }, { x: 383, s: 0.8, c: "#21503e" }].slice(0, Math.max(1, Math.min(3, drivers)));
  return (
    <svg viewBox="0 0 420 270" className="h-full w-full" preserveAspectRatio="xMidYMid slice" role="img"
      aria-label={`Pay envelopes going from the cash box to ${drivers} drivers`}>
      <rect width="420" height="270" fill="#fbf6ea" />
      <circle cx="372" cy="54" r="96" fill="#f8eed9" />
      <g fill="#fff" opacity=".95"><ellipse cx="96" cy="46" rx="28" ry="8" /><ellipse cx="116" cy="39" rx="16" ry="9" /></g>
      <rect x="0" y="206" width="420" height="64" fill="#ece2cb" />
      <rect x="0" y="206" width="420" height="4" fill="#e2d3b4" />
      <path d="M118 150C150 40 280 26 336 120" fill="none" stroke="#e2b55a" strokeWidth="2" strokeDasharray="3 7" strokeLinecap="round" />
      {/* the cash box */}
      <g transform="translate(30 146) scale(.82)">
        <g transform="rotate(-8 30 0)">{[0, 1, 2].map((i) => <rect key={i} x={26 + i * 18} y={-18 - i * 3} width="40" height="22" rx="2" fill={i === 1 ? "#34a374" : "#2f8a63"} stroke="#9fd4b8" strokeOpacity=".6" />)}</g>
        <rect width="124" height="74" rx="8" fill="#1d7a55" />
        <rect width="124" height="10" rx="5" fill="#34a374" />
        <rect x="46" y="26" width="32" height="20" rx="4" fill="#e2b55a" />
        <circle cx="62" cy="36" r="4" fill="#86590c" />
        <text x="62" y="64" fontSize="9" textAnchor="middle" fill="#cfe0d7" fontWeight="700" letterSpacing="1.6">CODesk CASH</text>
      </g>
      {/* the envelopes */}
      {tags.map((tag, i) => {
        const p = spots[i];
        return (
          <g key={tag} style={{ transform: sent ? `translate(${p.x}px, ${p.y}px)` : "translate(84px, 140px) scale(.3)",
            transition: `transform 1.1s cubic-bezier(.25,.8,.3,1) ${0.15 + i * 0.22}s` }} className="motion-reduce:!transition-none">
            <g transform={`rotate(${p.r}) scale(.9)`}>
              <rect x="-30" y="-19" width="60" height="38" rx="4" fill="#fff" stroke="#e2b55a" strokeWidth="1.5" />
              <path d="M-30-17 0 4l30-21" fill="none" stroke="#e2b55a" strokeWidth="1.5" strokeLinejoin="round" />
              <circle cy="4" r="6" fill="#b8402e" /><text y="7" fontSize="7" textAnchor="middle" fill="#fff" fontWeight="800">C</text>
            </g>
            <g transform={`translate(${-(tag.length * 2.8 + 6)} 24)`}>
              <rect width={tag.length * 5.6 + 12} height="15" rx="7.5" fill="#0f2e22" />
              <text x="6" y="10.5" fontSize="9" fill="#e2b55a" fontWeight="700">{tag}</text>
            </g>
          </g>
        );
      })}
      {/* the drivers */}
      {people.map((m, i) => (
        <g key={i} transform={`translate(${m.x} 206) scale(${m.s})`}>
          <path d="M-24 0v-22q0-22 24-22t24 22V0z" fill={m.c} />
          <path d="M-6-44 0-36l6-8" fill="none" stroke="#e2b55a" strokeWidth="2.5" strokeLinejoin="round" />
          <circle cy="-58" r="15" fill="#c98f62" />
          <path d="M-16-62q2-14 16-14t16 14z" fill={i === 1 ? "#e2b55a" : "#0f2e22"} />
          {i === 1 && <rect x="-18" y="-64" width="36" height="5" rx="2.5" fill="#86590c" />}
          <circle cx="-5" cy="-56" r="1.6" fill="#16211c" /><circle cx="5" cy="-56" r="1.6" fill="#16211c" />
          <path d="M-5-50q5 4 10 0" stroke="#16211c" strokeWidth="1.6" fill="none" strokeLinecap="round" />
        </g>
      ))}
      {drivers > 3 && (
        <g transform="translate(351 234)"><rect x="-30" y="-11" width="60" height="22" rx="11" fill="#0f2e22" />
          <text y="4" fontSize="10.5" textAnchor="middle" fill="#e2b55a" fontWeight="800">+{drivers - 3} more</text></g>
      )}
    </svg>
  );
}

/** The day's paid-out total, big, with how much of the day's cash it took. */
function PaidOutHero({ day, t, drivers }: { day: string; t: ExpenseDay["totals"]; drivers: number }) {
  const dep = useApi<DepositLedger>(`/deposits?end=${day}&count=1`).data?.rows?.find((r) => r.date === day);
  const shown = useCountUp(t.total);
  const cash = dep?.cash_received ?? 0;
  const share = cash ? Math.min(100, (t.total / cash) * 100) : 0;
  return (
    <section aria-label="Paid out" className="mb-6 grid overflow-hidden rounded-[18px] bg-white shadow-[0_0_0_1px_rgba(22,33,28,.06),0_20px_40px_-24px_rgba(22,33,28,.35)] lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
      <div className="min-w-0 p-6 sm:p-9">
        <p className="text-sm font-semibold text-ink-soft">Paid out to drivers · {fmtDay(day)}</p>
        <p className="num mt-2 text-[2.75rem] font-extrabold leading-none tracking-tight text-brass-dark sm:text-7xl">
          <span className="whitespace-nowrap">{fmtMoney(shown)}</span>
          <span className="ml-2 inline-block whitespace-nowrap text-xl font-semibold text-ink-faint sm:text-2xl">SAR</span>
        </p>
        <p className="mt-4 text-[15px] text-ink-soft">
          {t.count} {t.count === 1 ? "payment" : "payments"} · {drivers} {drivers === 1 ? "driver" : "drivers"}
          {t.by_category.length > 0 && <> · {t.by_category.map((c) => `${c.category_text} ${fmtMoney(c.amount)}`).join(" · ")}</>}
        </p>
        {cash > 0 && (
          <div className="mt-6 border-t border-paper-line pt-5">
            <p className="mb-2 flex justify-between text-xs text-ink-faint">
              <span>From the day's cash <span className="num font-semibold text-ink">{fmtMoney(cash)}</span></span>
              <span className="num">{share.toFixed(1)}% paid out</span>
            </p>
            <div className="flex h-3 overflow-hidden rounded-full bg-leaf-soft" role="img" aria-label={`${share.toFixed(1)}% of the day's cash paid out`}>
              <span className="rounded-full bg-gradient-to-r from-brass-glow to-brass" style={{ width: `${Math.max(share, t.total ? 1.5 : 0)}%` }} />
            </div>
            <p className="mt-2 flex justify-between text-xs">
              <span className="text-brass-dark">Paid out <span className="num font-semibold">{fmtMoney(t.total)}</span></span>
              <span className="text-leaf-dark">To the bank <span className="num font-semibold">{fmtMoney(dep?.to_deposit ?? 0)}</span></span>
            </p>
          </div>
        )}
      </div>
      <div className="h-52 min-w-0 sm:h-64 lg:h-auto lg:min-h-[17rem]">
        <PayEnvelopes key={day} labels={[...t.by_category].sort((x, y) => y.amount - x.amount).map((c) => c.category_text)} drivers={drivers} />
      </div>
    </section>
  );
}

/** What CODesk found unusual on this day, with a way to say "looks fine". */
function UnusualBox({ items, onChanged }: { items: Unusual[]; onChanged: () => void }) {
  const [noteFor, setNoteFor] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const open = items.filter((a) => !a.review);
  if (!items.length) return null;
  async function fine(key: string) {
    setError(null);
    try { await send("/unusual/review", "POST", { key, note }); setNoteFor(null); setNote(""); onChanged(); }
    catch (e) { setError((e as Error).message); }
  }
  return (
    <div className={`mb-6 rounded-panel border p-5 ${open.length ? "border-brass/40 bg-brass-soft/50" : "border-paper-line bg-white"}`}>
      <p className="flex items-center gap-2 text-sm font-semibold text-brass-dark">
        <Icon name="spark" className="h-5 w-5" />
        {open.length ? `CODesk noticed ${open.length} unusual ${open.length === 1 ? "amount" : "amounts"} on this day` : "Unusual amounts on this day, all looked at"}
      </p>
      <p className="mt-1 text-xs text-ink-soft">Compared with the desk's own last 90 days. It may be fine; it is worth a look.</p>
      <ul className="mt-3 space-y-2">
        {items.map((a) => (
          <li key={a.key} className="rounded-lg bg-white/80 px-3 py-2 text-sm">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="min-w-0 flex-1">{a.text}</span>
              {a.review ? <span className="text-xs text-leaf-dark">Looked at by {a.review.by}{a.review.note && `: ${a.review.note}`}</span>
                : noteFor === a.key ? null
                : <button onClick={() => setNoteFor(a.key)} className="btn-quiet !px-3 !py-1 text-xs">Looks fine</button>}
            </div>
            {noteFor === a.key && (
              <form onSubmit={(e) => { e.preventDefault(); fine(a.key); }} className="mt-2 flex flex-wrap gap-2">
                <input className="field !mt-0 min-w-0 flex-1" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)}
                  placeholder="Why it is fine (optional), e.g. two trips to Riyadh" autoFocus />
                <button className="btn-primary !px-3 !py-1.5 text-xs">Save</button>
                <button type="button" onClick={() => setNoteFor(null)} className="btn-quiet !px-3 !py-1.5 text-xs">Cancel</button>
              </form>
            )}
          </li>
        ))}
      </ul>
      <FormError message={error} />
    </div>
  );
}

const EXPENSE_PREVIEW = [
  { label: "Driver", cell: (r: PreviewRow) => <><span className="num font-medium">{(r.driver_code as string) ?? "-"}</span> <span className="text-ink-soft">{r.driver_name as string}</span></> },
  { label: "Category", cell: (r: PreviewRow) => <span className="text-ink-soft">{r.category_text as string}</span> },
  { label: "Amount", right: true, cell: money("amount") },
];

export default function Expenses() {
  const { day, setDay } = useBusinessDay();
  const [importing, setImporting] = useState(false);
  const [version, setVersion] = useState(0);
  const { data, error, loading, reload } = useApi<ExpenseDay>(`/expenses?date=${day}&v=${version}`);
  const oddData = useApi<Unusual[]>(`/unusual?date=${day}&v=${version}`).data;
  const odd = Array.isArray(oddData) ? oddData : [];
  const oddByExpense = new Map(odd.filter((a) => a.expense_id && !a.review).map((a) => [a.expense_id!, a]));
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
      <PageHeader title="Expenses & advances" subtitle="Money paid to drivers out of the day's cash: salaries, incentives, final settlements, fuel, travel and advances. Everything here lowers that day's cash to deposit.">
        <button onClick={() => setImporting(true)} className="btn-quiet"><Icon name="upload" className="h-4 w-4" />Import sheet</button>
        <button onClick={() => setDialog({ expense: null })} className="btn-primary"><Icon name="plus" className="h-4 w-4" />Pay out</button>
      </PageHeader>
      {importing && (
        <ImportDialog day={day} title="Import the expense sheet" endpoint="/expenses/import" templateUrl="/api/expenses/template"
          noun={["payment", "payments"]} columns={EXPENSE_PREVIEW}
          intro="Your own sheet works as it is: date, driver ID, driver name and amount, with or without a heading row. Without a type column every row is saved as Expense; add a Type column (salary, incentive, final settlement, fuel...) to sort them. A driver who is not in CODesk yet is added from his name, and rows already saved are skipped."
          onClose={() => setImporting(false)}
          onSaved={(dates) => { setImporting(false); if (dates.length === 1) setDay(dates[0]); changed(); drivers.reload(); }} />
      )}
      <DayPicker refreshKey={version} />

      <UnusualBox items={odd} onChanged={changed} />
      {data && t && t.count > 0 && <PaidOutHero day={day} t={t} drivers={new Set(data.rows.map((r) => r.driver_id)).size} />}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && t && (
            <>
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
                          <td className="px-3 py-3 text-right font-medium">
                            {oddByExpense.has(e.id) && (
                              <span title={oddByExpense.get(e.id)!.text} className="mr-2 inline-flex items-center gap-1 rounded-full bg-brass-soft px-2 py-0.5 text-xs font-semibold text-brass-dark">
                                <Icon name="spark" className="h-3 w-3" />{oddByExpense.get(e.id)!.ratio}x usual</span>
                            )}
                            <Money value={e.amount} /></td>
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
            </>
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
