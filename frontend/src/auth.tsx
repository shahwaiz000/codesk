import { FormEvent, ReactNode, createContext, useCallback, useContext, useEffect, useState } from "react";
import { Mark } from "./components/icons";
import RouteArt from "./components/RouteArt";
import { FormError } from "./components/ui";
import { AUTH_LOST, api } from "./lib";
import type { AuthStatus } from "./types";

interface AuthValue { username: string | null; loginEnabled: boolean; logout: () => Promise<void> }
const AuthContext = createContext<AuthValue>({ username: null, loginEnabled: false, logout: async () => {} });
export const useAuth = () => useContext(AuthContext);

/** The login screen: the green ledger panel on the left, the form on paper. */
function Shell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="grid min-h-screen bg-paper lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden overflow-hidden bg-ledger-900 p-12 text-white lg:flex lg:flex-col">
        <div className="flex items-center gap-3"><Mark /><span className="text-lg font-semibold">CODesk</span></div>
        <div className="flex min-h-0 flex-1 items-center justify-center py-8">
          <RouteArt className="h-full max-h-[480px] w-full max-w-[560px]" />
        </div>
        <div className="max-w-md">
          <p className="text-[32px] font-semibold leading-[1.15]">Every riyal from the driver to the bank.</p>
          <p className="mt-4 text-sm leading-relaxed text-ledger-300">Cash and POS handovers, POS checks against closed orders, driver expenses and next-day deposits, in one place.</p>
        </div>
      </aside>
      <main className="grid place-items-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden"><Mark /><span className="text-lg font-semibold">CODesk</span></div>
          <h1 className="text-2xl font-semibold text-ink">{title}</h1>
          <p className="mb-7 mt-1.5 text-sm text-ink-soft">{subtitle}</p>
          {children}
        </div>
      </main>
    </div>
  );
}

function CredentialsForm({ setup, onDone }: { setup: boolean; onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api(setup ? "/auth/setup" : "/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
      onDone();
    } catch (err) { setError((err as Error).message); }
    setBusy(false);
  }
  return (
    <Shell title={setup ? "Create the owner account" : "Log in"}
      subtitle={setup ? "This is the first time CODesk is opened on this computer. Choose a username and password." : "Log in to open the finance desk."}>
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm font-medium text-ink">Username
          <input className="field" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus /></label>
        <label className="block text-sm font-medium text-ink">Password
          <input className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={setup ? "new-password" : "current-password"} /></label>
        {setup && <p className="text-xs text-ink-faint">At least 10 characters, with a capital letter and a number.</p>}
        <FormError message={error} />
        <button disabled={busy || !username || !password} className="btn-primary w-full py-2.5">
          {busy ? "Please wait..." : setup ? "Create account" : "Log in"}</button>
      </form>
    </Shell>
  );
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<AuthStatus>("/auth/status").then((s) => { setStatus(s); setError(null); }).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    const onLost = () => setStatus((s) => (s && s.auth_enabled ? { ...s, user: null } : s));
    window.addEventListener(AUTH_LOST, onLost);
    return () => window.removeEventListener(AUTH_LOST, onLost);
  }, []);

  const logout = useCallback(async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch { /* the session ends either way */ }
    load();
  }, [load]);

  if (error) return (
    <Shell title="The backend is not running" subtitle={error}>
      <button onClick={load} className="btn-primary">Try again</button>
    </Shell>
  );
  if (!status) return <div className="grid min-h-screen place-items-center text-sm text-ink-soft">Loading...</div>;
  if (status.auth_enabled && !status.user) return <CredentialsForm setup={status.needs_setup} onDone={load} />;
  return (
    <AuthContext.Provider value={{ username: status.user?.username ?? null, loginEnabled: status.auth_enabled, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
