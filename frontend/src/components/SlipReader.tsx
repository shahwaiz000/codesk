import { FormEvent, useRef, useState } from "react";
import { fmtDay, fmtMoney, fmtWhen, send, upload, useApi } from "../lib";
import type { DepositDay } from "../types";
import { Icon } from "./icons";
import { FormError, Money, Panel } from "./ui";

export interface SlipCheck { ok: boolean; text: string }
export interface SlipDraft {
  id: number; at: string; filename: string; status: "draft" | "failed"; error: string | null;
  bank: string; slip_number: string; date_written: string; total: number | null; amount_in_words: string;
  denominations: { note: number | null; count: number | null; amount: number | null }[];
  checks: SlipCheck[]; business_date: string | null; deposit_date: string | null; has_image: boolean;
}
interface AiStatus { ready: boolean; ollama: boolean; model: string; small_model: string; has_model: boolean; models: string[] }

/** How to switch the local AI on, shown until it is ready. */
function AiSetup({ ai }: { ai: AiStatus }) {
  return (
    <div className="rounded-lg border border-brass/30 bg-brass-soft/60 p-4 text-sm text-brass-dark">
      <p className="font-semibold">{ai.ollama ? `The slip-reading model is not downloaded yet` : "The local AI is not running"}</p>
      <ol className="mt-2 list-decimal space-y-1 pl-5">
        {!ai.ollama && <li>Install <b>Ollama</b> from ollama.com (free), and open it once.</li>}
        <li>In PowerShell, run <code className="rounded bg-white/70 px-1.5 py-0.5">ollama pull {ai.small_model}</code> (about 1.9 GB, once). It fits a laptop with 8 GB of memory.
          With 16 GB or more, <code className="rounded bg-white/70 px-1.5 py-0.5">ollama pull {ai.model}</code> reads handwriting better; CODesk uses it when it fits.</li>
        <li>Come back here and read the slip.</li>
      </ol>
      <p className="mt-2 text-xs">The AI runs on this computer, so your slips are never sent anywhere.</p>
    </div>
  );
}

function Draft({ s, days, onDone }: { s: SlipDraft; days: DepositDay[]; onDone: () => void }) {
  const [day, setDay] = useState(s.business_date ?? "");
  const [when, setWhen] = useState(s.deposit_date ?? "");
  const [bank, setBank] = useState(s.bank);
  const [ref, setRef] = useState(s.slip_number);
  const [amount, setAmount] = useState(s.total != null ? String(s.total) : "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState(false);
  const bad = s.checks.filter((c) => !c.ok).length;
  const open = days.filter((d) => d.pending > 0 || d.date === s.business_date);

  async function act(path: string, body?: unknown) {
    setBusy(true); setError(null);
    try { await send(path, "POST", body); onDone(); } catch (e) { setError((e as Error).message); setBusy(false); }
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    act(`/slips/${s.id}/record`, { business_date: day, deposit_date: when, bank, slip_ref: ref, amount });
  }

  return (
    <li className={`grid gap-5 rounded-lg border p-4 md:grid-cols-[9rem_minmax(0,1fr)] ${s.status === "failed" ? "border-short/30 bg-short-soft/30" : bad ? "border-brass/40 bg-brass-soft/30" : "border-leaf/30 bg-leaf-soft/30"}`}>
      <div>
        {s.has_image ? (
          <button type="button" onClick={() => setZoom(true)} className="block w-full overflow-hidden rounded-md border border-paper-line bg-white" aria-label="Show the slip larger">
            <img src={`/api/slips/${s.id}/image`} alt={`Scan of ${s.filename}`} className="h-44 w-full object-cover object-top" />
          </button>
        ) : <div className="grid h-44 place-items-center rounded-md border border-dashed border-paper-line text-xs text-ink-faint">No picture</div>}
        <p className="mt-1.5 truncate text-xs text-ink-faint" title={s.filename}>{s.filename}</p>
        <p className="text-xs text-ink-faint">{fmtWhen(s.at)}</p>
      </div>

      {s.status === "failed" ? (
        <div className="space-y-3">
          <p className="text-sm font-semibold text-short">Could not read this slip</p>
          <p className="text-sm text-ink-soft">{s.error}</p>
          <FormError message={error} />
          {busy && <p className="flex items-center gap-2 text-sm text-ink-soft" role="status">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-leaf border-t-transparent" />Reading again… 1 to 3 minutes.</p>}
          <div className="flex flex-wrap gap-2">
            {s.has_image && <button disabled={busy} onClick={() => act(`/slips/${s.id}/retry`)} className="btn-primary">Read again</button>}
            <button disabled={busy} onClick={() => act(`/slips/${s.id}/dismiss`)} className="btn-quiet">Put aside</button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm text-ink-soft">The AI read <span className="num text-2xl font-bold text-ink">{s.total != null ? fmtMoney(s.total) : "?"}</span> SAR</p>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${bad ? "bg-brass-soft text-brass-dark" : "bg-leaf text-white"}`}>
              {bad ? `${bad} ${bad === 1 ? "check" : "checks"} to look at` : "All checks passed"}
            </span>
          </div>
          <ul className="space-y-1 text-sm">
            {s.checks.map((c, i) => (
              <li key={i} className={`flex gap-2 ${c.ok ? "text-leaf-dark" : "text-short"}`}>
                <Icon name={c.ok ? "check" : "alert"} className="mt-0.5 h-4 w-4 shrink-0" /><span>{c.text}</span>
              </li>
            ))}
          </ul>
          {s.denominations.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-ink-soft">Denominations read ({s.denominations.length} lines){s.amount_in_words && <> · “{s.amount_in_words}”</>}</summary>
              <table className="mt-2 w-full max-w-sm text-xs">
                <tbody>{s.denominations.map((d, i) => (
                  <tr key={i} className="border-b border-paper-line"><td className="num py-1">{d.note} ×</td><td className="num py-1">{d.count}</td>
                    <td className="py-1 text-right"><Money value={d.amount} /></td></tr>
                ))}</tbody>
              </table>
            </details>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <label className="block text-xs font-medium text-ink-soft lg:col-span-2">Cash of the day
              <select className="field" value={day} onChange={(e) => setDay(e.target.value)} required>
                <option value="">Choose the day</option>
                {open.map((d) => <option key={d.date} value={d.date}>{fmtDay(d.date)}: {fmtMoney(d.pending)} to deposit</option>)}
              </select></label>
            <label className="block text-xs font-medium text-ink-soft">Deposited on
              <input type="date" className="field" value={when} onChange={(e) => setWhen(e.target.value)} required /></label>
            <label className="block text-xs font-medium text-ink-soft">Bank
              <input className="field" value={bank} onChange={(e) => setBank(e.target.value)} required /></label>
            <label className="block text-xs font-medium text-ink-soft">Slip no.
              <input className="field num uppercase" value={ref} onChange={(e) => setRef(e.target.value)} required placeholder="Write one" /></label>
            <label className="block text-xs font-medium text-ink-soft">Amount
              <input className="field num text-right" value={amount} onChange={(e) => setAmount(e.target.value)} required /></label>
          </div>
          <FormError message={error} />
          <div className="flex flex-wrap gap-2">
            <button disabled={busy || !day || !when || !ref.trim() || !bank.trim()} className="btn-primary"><Icon name="check" className="h-4 w-4" />Record deposit</button>
            <button type="button" disabled={busy} onClick={() => act(`/slips/${s.id}/dismiss`)} className="btn-quiet">Put aside</button>
          </div>
        </form>
      )}
      {zoom && (
        <div role="dialog" aria-label="Slip" onClick={() => setZoom(false)} className="fixed inset-0 z-50 grid place-items-center bg-ink/70 p-4">
          <img src={`/api/slips/${s.id}/image`} alt={`Scan of ${s.filename}`} className="max-h-full max-w-full rounded-lg bg-white shadow-pop" />
        </div>
      )}
    </li>
  );
}

/** Slips read by the local AI and waiting for a person, plus the button to read one. */
export default function SlipReader({ days, onRecorded }: { days: DepositDay[]; onRecorded: () => void }) {
  const [version, setVersion] = useState(0);
  const slips = useApi<SlipDraft[]>(`/slips?v=${version}`);
  const ai = useApi<AiStatus>(`/slips/ai?v=${version}`).data;
  const [reading, setReading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const waiting = slips.data ?? [];
  const refresh = () => { setVersion((v) => v + 1); onRecorded(); };

  async function read(file: File) {
    setReading(file.name); setError(null);
    const form = new FormData();
    form.append("file", file);
    try { await upload("/slips/read", form); setVersion((v) => v + 1); }
    catch (e) { setError((e as Error).message); }
    setReading(null);
    if (input.current) input.current.value = "";
  }

  return (
    <Panel className="mb-6" title={waiting.length ? `Slips read by CODesk (${waiting.length} to confirm)` : "Read a deposit slip"}
      action={
        <label className={`btn-primary cursor-pointer ${reading || ai?.ready === false ? "pointer-events-none opacity-50" : ""}`}>
          <Icon name="upload" className="h-4 w-4" />Read a slip
          <input ref={input} type="file" accept=".pdf,.jpg,.jpeg,.png" className="sr-only" disabled={!!reading || ai?.ready === false}
            onChange={(e) => e.target.files?.[0] && read(e.target.files[0])} />
        </label>
      }>
      <p className="mb-4 text-sm text-ink-soft">
        Scan or photograph the bank slip and read it here, or drop it in the watch folder. The AI on this computer reads the date, total and
        every note line; CODesk checks the sums and finds the day's cash it belongs to. You confirm it with one click.
      </p>
      {ai && !ai.ready && <AiSetup ai={ai} />}
      {reading && (
        <p className="flex items-center gap-3 rounded-lg bg-paper px-4 py-3 text-sm text-ink-soft" role="status">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-leaf border-t-transparent" />
          Reading {reading}… on a laptop this takes 1 to 3 minutes.
        </p>
      )}
      <FormError message={error} />
      {waiting.length > 0 && (
        <ul className="mt-4 space-y-4">{waiting.map((s) => <Draft key={s.id} s={s} days={days} onDone={refresh} />)}</ul>
      )}
    </Panel>
  );
}
