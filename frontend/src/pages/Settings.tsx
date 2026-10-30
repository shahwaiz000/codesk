import { FormEvent, useState } from "react";
import { useAuth } from "../auth";
import { Empty, ErrorBox, FormError, Loading, PageHeader, Panel } from "../components/ui";
import { fmtWhen, send, useApi } from "../lib";
import type { AiStatus, AuditEntry } from "../types";

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setDone(false);
    try {
      await send("/auth/password", "POST", { current_password: current, new_password: next });
      setDone(true); setCurrent(""); setNext("");
    } catch (err) { setError((err as Error).message); }
    setBusy(false);
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <label className="block text-sm font-medium">Current password
        <input className="field" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
      <label className="block text-sm font-medium">New password
        <input className="field" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></label>
      <p className="text-xs text-ink-faint">At least 10 characters, with a capital letter and a number. Other devices will be logged out.</p>
      <FormError message={error} />
      {done && <p role="status" className="rounded-lg bg-leaf-soft px-3 py-2 text-sm text-leaf-dark">Password changed.</p>}
      <button disabled={busy || !current || !next} className="btn-primary">Change password</button>
    </form>
  );
}

const MODES = [
  { value: "paid", title: "Orders are closed only when paid in full",
    text: "A driver who cannot pay keeps the order pending, so a closed order is always paid. Collections shows each driver's cash from the system report, with no counting." },
  { value: "count", title: "The desk counts each driver's cash",
    text: "Orders can be closed before the money is counted. Collections compares the cash counted at the desk with the system's cash and shows short drivers in red." },
];

function CashMode() {
  const { data, reload } = useApi<{ cash_mode: string }>("/settings");
  const [error, setError] = useState<string | null>(null);
  async function choose(value: string) {
    setError(null);
    try { await send("/settings", "PUT", { cash_mode: value }); reload(); }
    catch (err) { setError((err as Error).message); }
  }
  return (
    <fieldset className="space-y-3">
      <legend className="sr-only">How your cash desk works</legend>
      {MODES.map((m) => (
        <label key={m.value} className={`flex cursor-pointer gap-3 rounded-lg border p-4 ${data?.cash_mode === m.value ? "border-ledger-700 bg-leaf-soft/40" : "border-paper-line hover:bg-paper/60"}`}>
          <input type="radio" name="cash_mode" className="mt-1 h-4 w-4 accent-ledger-700" checked={data?.cash_mode === m.value} onChange={() => choose(m.value)} />
          <span><span className="block text-sm font-medium">{m.title}</span><span className="mt-1 block text-sm text-ink-soft">{m.text}</span></span>
        </label>
      ))}
      <FormError message={error} />
    </fieldset>
  );
}

type WatchFile = { id: number; at: string; filename: string; kind_text: string; status: "done" | "attention" | "failed"; summary: string };
type Watch = { folder: string; exists: boolean; running: boolean; interval: number; last_scan: string | null; files: WatchFile[] };

const FILE_TONE = { done: "bg-leaf-soft text-leaf-dark", attention: "bg-brass-soft text-brass-dark", failed: "bg-short-soft text-short-dark" };
const FILE_TEXT = { done: "Imported", attention: "Imported, some rows left out", failed: "Could not import" };

function WatchFolder() {
  const { data, reload } = useApi<Watch>("/watch");
  const [path, setPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const value = path ?? data?.folder ?? "";

  async function save(folder: string, create = false) {
    setBusy(true); setError(null); setMissing(false);
    try { await send("/watch", "PUT", { folder, create }); setPath(null); reload(); }
    catch (err) {
      const msg = (err as Error).message;
      if (msg.includes("does not exist")) setMissing(true); else setError(msg);
    }
    setBusy(false);
  }
  async function scan() {
    setBusy(true); setError(null);
    try { await send("/watch/scan", "POST"); reload(); } catch (err) { setError((err as Error).message); }
    setBusy(false);
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-soft">
        Save the day's files in one folder: the collection report, the terminal sheet, the expense sheet. CODesk looks in it every
        {" "}{data?.interval ?? 10} seconds, recognises each file by its columns, imports the good rows and moves the file to <b>Imported</b>.
        A file it cannot read goes to <b>Problems</b>.
      </p>
      <form onSubmit={(e) => { e.preventDefault(); save(value.trim()); }} className="space-y-2">
        <label className="block text-sm font-medium">Folder on this computer
          <input className="field" value={value} onChange={(e) => { setPath(e.target.value); setMissing(false); }}
            placeholder={"C:\\Users\\you\\Documents\\CODesk inbox"} spellCheck={false} /></label>
        <div className="flex flex-wrap gap-2">
          <button disabled={busy || !value.trim() || value.trim() === data?.folder} className="btn-primary">Use this folder</button>
          {data?.folder && <button type="button" disabled={busy} onClick={scan} className="btn-quiet">Check now</button>}
          {data?.folder && <button type="button" disabled={busy} onClick={() => save("")} className="btn-quiet ml-auto">Turn off</button>}
        </div>
      </form>
      {missing && (
        <p className="flex flex-wrap items-center gap-2 rounded-md bg-brass-soft px-3 py-2 text-sm text-brass-dark">
          This folder does not exist yet.
          <button disabled={busy} onClick={() => save(value.trim(), true)} className="btn-primary !px-3 !py-1 text-xs">Create it</button>
        </p>
      )}
      <FormError message={error} />
      {data?.folder && (
        <p className={`flex items-center gap-2 text-sm ${data.exists ? "text-leaf-dark" : "text-short"}`}>
          <span className={`h-2 w-2 rounded-full ${data.exists && data.running ? "animate-pulse bg-leaf" : "bg-short"}`} />
          {!data.exists ? "The folder cannot be found. Check the path." : data.running ? "Watching" : "Watching is turned off on this server"}
          {data.last_scan && data.exists && <span className="text-ink-faint">· last look {fmtWhen(data.last_scan)}</span>}
        </p>
      )}
      {!!data?.files.length && (
        <ol className="max-h-72 divide-y divide-paper-line overflow-y-auto rounded-lg border border-paper-line">
          {data.files.map((f) => (
            <li key={f.id} className="px-3 py-2.5 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 truncate font-medium" title={f.filename}>{f.filename}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${FILE_TONE[f.status]}`}>{FILE_TEXT[f.status]}</span>
                <time className="num ml-auto text-xs text-ink-faint">{fmtWhen(f.at)}</time>
              </p>
              <p className="mt-0.5 text-xs text-ink-soft">{f.kind_text} · {f.summary}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function AiEngine() {
  const { data, reload } = useApi<AiStatus>("/ai");
  const [engine, setEngine] = useState<"local" | "gemini" | null>(null);
  const [key, setKey] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [ack, setAck] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const e = engine ?? data.engine;
  const sure = ack ?? data.ack;

  async function save(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true); setError(null); setNote(null);
    try {
      await send("/ai", "PUT", { engine: e, gemini_key: key || null, gemini_model: model || null, ack: e === "gemini" && sure });
      setKey(""); setEngine(null); setAck(null); setModel(null); reload(); setNote("Saved.");
    } catch (err) { setError((err as Error).message); }
    setBusy(false);
  }
  async function test() {
    setBusy(true); setError(null); setNote(null);
    try { const r = await send<{ reply: string }>("/ai/test", "POST"); setNote(`The AI answered: "${r.reply}"`); }
    catch (err) { setError((err as Error).message); }
    setBusy(false);
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <p className="text-sm text-ink-soft">Reads deposit slips and answers questions on the Ask CODesk page.</p>
      {[
        { v: "local" as const, t: "Local AI on this computer (Ollama)", d: "Private: nothing leaves this computer. Needs about 3 GB of free memory." },
        { v: "gemini" as const, t: "Google Gemini, free (cloud), demo data only", d: "Works on any laptop, in seconds. Google may use what is sent on its free tier, so CODesk only allows it in demo mode, with the fictional data." },
      ].map((o) => (
        <label key={o.v} className={`flex cursor-pointer gap-3 rounded-lg border p-4 ${e === o.v ? "border-ledger-700 bg-leaf-soft/40" : "border-paper-line hover:bg-paper/60"}`}>
          <input type="radio" name="engine" className="mt-1 h-4 w-4 accent-ledger-700" checked={e === o.v} onChange={() => setEngine(o.v)} />
          <span><span className="block text-sm font-medium">{o.t}</span><span className="mt-1 block text-sm text-ink-soft">{o.d}</span></span>
        </label>
      ))}
      {e === "gemini" && (
        <div className="space-y-3 rounded-lg border border-paper-line p-4">
          {!data.demo_mode && <p className="rounded-md bg-short-soft px-3 py-2 text-sm text-short-dark">CODesk is running with your real data, so the cloud AI stays off. Start CODesk in demo mode to use it.</p>}
          <label className="block text-sm font-medium">Gemini API key
            <input className="field" type="password" autoComplete="off" value={key} onChange={(ev) => setKey(ev.target.value)}
              placeholder={data.has_key ? `Saved (${data.key_hint}). Type a new one to replace it` : "Paste your free key from aistudio.google.com"} /></label>
          <label className="block text-sm font-medium">Model
            <input className="field" value={model ?? data.gemini_model} onChange={(ev) => setModel(ev.target.value)} /></label>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-ledger-700" checked={sure} onChange={(ev) => setAck(ev.target.checked)} />
            <span>I will use the cloud AI only with demo (fictional) data, never with company data.</span>
          </label>
        </div>
      )}
      <FormError message={error} />
      {note && <p role="status" className="rounded-md bg-leaf-soft px-3 py-2 text-sm text-leaf-dark">{note}</p>}
      <p className={`flex items-center gap-2 text-sm ${data.ready ? "text-leaf-dark" : "text-brass-dark"}`}>
        <span className={`h-2 w-2 rounded-full ${data.ready ? "bg-leaf" : "bg-brass"}`} />
        {data.ready ? `Ready: ${data.engine === "gemini" ? "Google Gemini" : "local AI"}` : data.reason}
      </p>
      <div className="flex flex-wrap gap-2">
        <button disabled={busy || (e === "gemini" && !sure)} className="btn-primary">Save</button>
        <button type="button" disabled={busy || !data.ready} onClick={test} className="btn-quiet">Test the AI</button>
      </div>
      {busy && <p role="status" className="flex items-center gap-2 text-sm text-ink-soft">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-leaf border-t-transparent" />
        Waiting for the AI… if Google is busy, CODesk tries again by itself (up to a minute and a half).</p>}
    </form>
  );
}

export default function Settings() {
  const { username, loginEnabled } = useAuth();
  const log = useApi<AuditEntry[]>("/audit?limit=200");
  return (
    <>
      <PageHeader title="Settings" subtitle={loginEnabled && username ? `Logged in as ${username}.` : "Login is turned off on this server."} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-6 self-start">
          {loginEnabled && <Panel title="Password"><PasswordForm /></Panel>}
        </div>
        <div className="min-w-0 space-y-6">
        <Panel title="Watch folder"><WatchFolder /></Panel>
        <Panel title="AI engine"><AiEngine /></Panel>
        <Panel title="Activity log" flush className="">
          <p className="border-b border-paper-line px-5 py-3 text-xs text-ink-faint">Every change made in CODesk, newest first. Entries cannot be edited or deleted.</p>
          {log.loading && !log.data ? <Loading /> : log.error ? <div className="p-5"><ErrorBox message={log.error} retry={log.reload} /></div>
            : !log.data?.length ? <Empty title="No changes yet" hint="When you add or change a record, it is written here with your name and the time." />
            : (
              <ol className="max-h-[32rem] divide-y divide-paper-line overflow-y-auto">
                {log.data.map((a) => (
                  <li key={a.id} className="flex gap-4 px-5 py-3 text-sm">
                    <time className="num w-28 shrink-0 text-ink-faint">{fmtWhen(a.at)}</time>
                    <span className="min-w-0"><span className="font-medium">{a.username}</span> <span className="text-ink-soft">{a.summary}</span></span>
                  </li>
                ))}
              </ol>
            )}
        </Panel>
        </div>
      </div>
    </>
  );
}
