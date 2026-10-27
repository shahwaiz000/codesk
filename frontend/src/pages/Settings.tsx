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

export default function Settings() {
  const { username, loginEnabled } = useAuth();
  const log = useApi<AuditEntry[]>("/audit?limit=200");
  return (
    <>
      <PageHeader title="Settings" subtitle={loginEnabled && username ? `Logged in as ${username}.` : "Login is turned off on this server."} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        {loginEnabled && <Panel title="Password" className="self-start"><PasswordForm /></Panel>}
        <Panel title="Activity log" flush className={loginEnabled ? "" : "lg:col-span-2"}>
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
