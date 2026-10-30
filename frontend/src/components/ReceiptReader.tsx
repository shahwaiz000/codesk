import { useEffect, useRef, useState } from "react";
import { fmtDay, fmtMoney, parseAmount, send, upload, useApi, withStation } from "../lib";
import { Icon } from "./icons";
import { FormError, Panel } from "./ui";

type Check = { ok: boolean; text: string };
type Receipt = { terminal: string; date: string | null; branch: string; count: number | null; total: number | null; lines: number[]; checks: Check[] };
type ReadResult = { date: string; ai: boolean; reason: string; photos: { file: string; receipts: Receipt[]; error: string }[] };
type Row = { key: number; photo: number; terminal: string; amount: string; count: number | null; checks: Check[] };

let next = 1;

/** The cashier's photos of the card machines' end-of-day receipts: the AI reads them (demo data), or the
 *  totals are typed from the photos; then they are saved as the day's card machine sheet. */
export default function ReceiptReader({ day, onSaved }: { day: string; onSaved: () => void }) {
  const ai = useApi<{ engine: string; ready: boolean; demo_mode: boolean }>("/ai").data;
  const parts = useApi<{ parts: number }>(`/receipts/demo/parts?date=${day}`).data?.parts ?? 0;
  const input = useRef<HTMLInputElement>(null);
  const [photos, setPhotos] = useState<{ url: string; name: string; error: string }[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"" | "reading" | "saving">("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  useEffect(() => () => photos.forEach((p) => URL.revokeObjectURL(p.url)), [photos]);

  async function choose(files: FileList | null) {
    if (!files?.length) return;
    const list = [...files].slice(0, 12);
    setPhotos(list.map((f) => ({ url: URL.createObjectURL(f), name: f.name, error: "" })));
    setRows([]); setError(null); setDone(null); setBusy("reading");
    const form = new FormData();
    list.forEach((f) => form.append("files", f));
    form.append("business_date", day);
    try {
      const r = await upload<ReadResult>("/receipts/read", form);
      setNote(r.ai ? "" : r.reason);
      setPhotos((ps) => ps.map((p, i) => ({ ...p, error: r.photos[i]?.error ?? "" })));
      const read: Row[] = r.photos.flatMap((p, i) => p.receipts.map((x) => ({ key: next++, photo: i, terminal: x.terminal, amount: x.total == null ? "" : String(x.total), count: x.count, checks: x.checks })));
      setRows(read.length ? read : list.map((_, i) => ({ key: next++, photo: i, terminal: "", amount: "", count: null, checks: [] })));
    } catch (e) { setError((e as Error).message); }
    setBusy("");
    if (input.current) input.current.value = "";
  }

  const set = (key: number, k: "terminal" | "amount", v: string) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, [k]: v } : r)));
  const filled = rows.filter((r) => r.terminal.trim() && parseAmount(r.amount) != null);
  const total = filled.reduce((t, r) => t + (parseAmount(r.amount) ?? 0), 0);

  async function save() {
    setBusy("saving"); setError(null);
    try {
      const r = await send<{ machines: number; total: number }>("/receipts/save", "POST", { date: day, rows: filled.map((x) => ({ terminal: x.terminal, amount: x.amount })) });
      setDone(`${r.machines} machines saved as the card machine sheet of ${fmtDay(day)}, total ${fmtMoney(r.total)}.`);
      setPhotos([]); setRows([]); onSaved();
    } catch (e) { setError((e as Error).message); }
    setBusy("");
  }

  const cloud = ai?.engine === "gemini" && ai.ready && ai.demo_mode;
  return (
    <Panel title="Card machine receipts" className="mb-6"
      action={<button onClick={() => input.current?.click()} disabled={!!busy} className="btn-primary"><Icon name="upload" className="h-4 w-4" />Add receipt photos</button>}>
      <input ref={input} type="file" accept="image/*,.pdf" multiple className="hidden" onChange={(e) => choose(e.target.files)} />
      <p className="-mt-2 text-sm text-ink-soft">
        The cashier photographs each machine's end-of-day receipt. {cloud ? "The AI reads every receipt in a photo: terminal, date, payments and total, and checks the lines add up." : "Add the photos and type each machine's total from them."} The totals become the day's card machine sheet, compared with the system above.
      </p>
      {cloud && parts > 0 && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-soft">
          <span className="rounded-full bg-leaf-soft px-2.5 py-0.5 text-xs font-semibold text-leaf-dark">Google Gemini · demo data</span>
          Demo receipt photos for {fmtDay(day)}:
          {Array.from({ length: parts }, (_, i) => (
            <a key={i} href={withStation(`/api/receipts/demo?date=${day}&part=${i + 1}`)} className="font-medium text-leaf-dark underline underline-offset-2">photo {i + 1}</a>))}
        </p>
      )}
      {busy === "reading" && <p className="mt-4 flex items-center gap-2 text-sm text-ink-soft" role="status">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-leaf border-t-transparent" />{cloud ? "The AI is reading the receipts… about 20 seconds a photo." : "Loading the photos…"}</p>}
      {note && <p className="mt-4 rounded-md bg-paper px-3 py-2 text-xs text-ink-soft">{note}</p>}
      {done && <p className="mt-4 rounded-md bg-leaf-soft px-3 py-2 text-sm text-leaf-dark">{done}</p>}
      <FormError message={error} />

      {photos.length > 0 && !busy && (
        <div className="mt-4 space-y-5">
          {photos.map((p, i) => (
            <div key={i} className="grid gap-4 rounded-lg border border-paper-line p-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
              <a href={p.url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-md bg-ledger-950">
                <img src={p.url} alt={`Receipt photo ${p.name}`} className="max-h-[26rem] w-full object-contain" />
              </a>
              <div className="min-w-0 space-y-2">
                <p className="truncate text-xs text-ink-faint">{p.name}</p>
                {p.error && <p className="text-sm text-short">{p.error}</p>}
                {rows.filter((r) => r.photo === i).map((r) => (
                  <div key={r.key} className="rounded-md bg-paper p-2.5">
                    <div className="flex items-center gap-2">
                      <input aria-label="Terminal ID" className="field num mt-0 w-36 py-1.5" value={r.terminal} placeholder="Terminal ID" onChange={(e) => set(r.key, "terminal", e.target.value)} />
                      <input aria-label="Total" className="field num mt-0 flex-1 py-1.5 text-right" inputMode="decimal" value={r.amount} placeholder="Total" onChange={(e) => set(r.key, "amount", e.target.value)} />
                      <button onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))} aria-label="Remove this machine" className="rounded p-1 text-ink-faint hover:bg-short-soft hover:text-short"><Icon name="trash" className="h-4 w-4" /></button>
                    </div>
                    {r.checks.length > 0 && (
                      <ul className="mt-1.5 space-y-0.5 text-xs">
                        {r.checks.map((c, j) => <li key={j} className={`flex gap-1.5 ${c.ok ? "text-leaf-dark" : "text-short"}`}><Icon name={c.ok ? "check" : "alert"} className="mt-px h-3.5 w-3.5 shrink-0" />{c.text}</li>)}
                      </ul>
                    )}
                  </div>
                ))}
                <button onClick={() => setRows((rs) => [...rs, { key: next++, photo: i, terminal: "", amount: "", count: null, checks: [] }])}
                  className="text-xs font-medium text-leaf-dark hover:underline">+ another machine in this photo</button>
              </div>
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-paper-line pt-3">
            <span className="text-sm text-ink-soft">{filled.length} machines, total <b className="num text-ink">{fmtMoney(total)}</b></span>
            <button onClick={() => { setPhotos([]); setRows([]); }} className="btn-quiet">Cancel</button>
            <button onClick={save} disabled={!filled.length || busy !== ""} className="btn-primary"><Icon name="check" className="h-4 w-4" />Save as the card machine sheet</button>
          </div>
        </div>
      )}
    </Panel>
  );
}
