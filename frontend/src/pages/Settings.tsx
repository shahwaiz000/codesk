import { FormEvent, useState } from "react";
import { useAuth } from "../auth";
import { Empty, ErrorBox, FormError, Loading, PageHeader, Panel } from "../components/ui";
import { fmtWhen, send, useApi } from "../lib";
import type { AuditEntry } from "../types";

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

export default function Settings() {
  const { username, loginEnabled } = useAuth();
  const log = useApi<AuditEntry[]>("/audit?limit=200");
  return (
    <>
      <PageHeader title="Settings" subtitle={loginEnabled && username ? `Logged in as ${username}.` : "Login is turned off on this server."} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-6 self-start">
          <Panel title="How your cash desk works"><CashMode /></Panel>
          {loginEnabled && <Panel title="Password"><PasswordForm /></Panel>}
        </div>
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
    </>
  );
}
