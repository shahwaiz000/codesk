import { FormEvent, useEffect, useState } from "react";
import { useBusinessDay } from "../businessDay";
import { fmtDay, fmtMoney, fmtWhen, send, useApi } from "../lib";
import { byRegion, useStation } from "../stations";
import { Icon } from "./icons";
import { Empty, ErrorBox, FormError, Loading, Modal, Money, Panel } from "./ui";

export type FollowUp = {
  id: number; station_id: number; station: string; station_code: string; cashier_name: string; cashier_phone: string;
  date: string | null; kind: string; kind_text: string; title: string; amount: number; status: "open" | "closed";
  created_by: string; created_at: string; closed_by: string; closed_at: string | null; days_open: number;
  notes: { id: number; text: string; by: string; at: string }[];
};
export type FollowDraft = { kind?: string; title?: string; amount?: number; date?: string | null; station_id?: number };

const KINDS = [
  { value: "deposit_short", label: "Deposit short" }, { value: "deposit_late", label: "Deposit late" },
  { value: "card_sheet", label: "Card sheet difference" }, { value: "missing_file", label: "File missing" }, { value: "other", label: "Other" },
];

/** Raise a follow-up with a station's cashier. Can be opened already filled in from a problem. */
export function RaiseDialog({ draft, onClose, onSaved }: { draft: FollowDraft; onClose: () => void; onSaved: () => void }) {
  const { station, stations } = useStation();
  const { day } = useBusinessDay();
  const [sid, setSid] = useState(String(draft.station_id ?? station?.id ?? ""));
  const [kind, setKind] = useState(draft.kind ?? "other");
  const [title, setTitle] = useState(draft.title ?? "");
  const [amount, setAmount] = useState(draft.amount ? String(draft.amount) : "");
  const [when, setWhen] = useState(draft.date === undefined ? day : draft.date ?? "");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await send("/supervisor/follow-ups", "POST", { station_id: Number(sid), date: when || null, kind, title, amount: amount || 0, note });
      onSaved();
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }
  return (
    <Modal title="Raise a follow-up with the cashier" onClose={onClose} width="max-w-lg">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium">Station
            <select className="field" value={sid} onChange={(e) => setSid(e.target.value)} required>
              <option value="">Choose the station</option>
              {byRegion(stations.filter((s) => s.active)).map(([region, list]) => (
                <optgroup key={region} label={region}>{list.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>))}
            </select></label>
          <label className="block text-sm font-medium">What kind
            <select className="field" value={kind} onChange={(e) => setKind(e.target.value)}>
              {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select></label>
        </div>
        <label className="block text-sm font-medium">What is wrong
          <input className="field" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Deposit 500 SAR short" /></label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium">Day it is about
            <input type="date" className="field" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
          <label className="block text-sm font-medium">Amount (SAR)
            <input className="field num text-right" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Optional" /></label>
        </div>
        <label className="block text-sm font-medium">First note
          <input className="field" value={note} maxLength={600} onChange={(e) => setNote(e.target.value)} placeholder="Optional, e.g. called the cashier" /></label>
        <FormError message={error} />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-quiet">Cancel</button>
          <button disabled={busy || !sid || title.trim().length < 3} className="btn-primary">Raise follow-up</button>
        </div>
      </form>
    </Modal>
  );
}

/** A ready-to-send message to the cashier: copy it, or open WhatsApp or e-mail with it. */
function MessageDialog({ f, onClose }: { f: FollowUp; onClose: () => void }) {
  const [lang, setLang] = useState<"en" | "ar">("en");
  const [text, setText] = useState("");
  const [meta, setMeta] = useState<{ phone: string; email: string; subject: string; by: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function write(polish: boolean, l = lang) {
    setBusy(true); setError(null);
    try {
      const r = await send<{ text: string; phone: string; email: string; subject: string; by: string }>(`/supervisor/follow-ups/${f.id}/message`, "POST", { lang: l, polish });
      setText(r.text); setMeta(r);
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  useEffect(() => { void write(false); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function copy() {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* not allowed */ }
  }
  return (
    <Modal title={`Message to the cashier of ${f.station}`} onClose={onClose} width="max-w-xl">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {(["en", "ar"] as const).map((l) => (
            <button key={l} type="button" onClick={() => { setLang(l); void write(false, l); }}
              className={`rounded-full px-3 py-1 text-xs font-semibold ${lang === l ? "bg-ledger-800 text-white" : "bg-paper text-ink-soft hover:bg-paper-deep"}`}>
              {l === "en" ? "English" : "العربية"}</button>))}
          <button type="button" disabled={busy} onClick={() => write(true)} className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-leaf-soft px-3 py-1 text-xs font-semibold text-leaf-dark hover:bg-leaf/20 disabled:opacity-50">
            <Icon name="spark" className="h-3.5 w-3.5" />Improve with AI</button>
        </div>
        <textarea dir={lang === "ar" ? "rtl" : "ltr"} className="field min-h-[12rem] font-sans text-sm leading-relaxed" value={busy ? "Writing…" : text} onChange={(e) => setText(e.target.value)} />
        {meta?.by === "ai" && <p className="text-xs text-ink-faint">Rewritten by the AI. Read it before you send it.</p>}
        <FormError message={error} />
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={copy} disabled={!text} className="btn-quiet">{copied ? "Copied" : "Copy"}</button>
          {meta?.email && <a className="btn-quiet" href={`mailto:${meta.email}?subject=${encodeURIComponent(meta.subject)}&body=${encodeURIComponent(text)}`}>E-mail</a>}
          {meta?.phone
            ? <a className="btn-primary" target="_blank" rel="noreferrer" href={`https://wa.me/${meta.phone}?text=${encodeURIComponent(text)}`}>Open WhatsApp</a>
            : <span className="self-center text-xs text-ink-faint">Add the cashier's mobile on the Stations page to send it on WhatsApp.</span>}
        </div>
      </div>
    </Modal>
  );
}

function Item({ f, onChanged }: { f: FollowUp; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [messaging, setMessaging] = useState(false);
  async function act(path: string, body?: unknown) {
    setError(null);
    try { await send(path, "POST", body); setNote(""); onChanged(); } catch (e) { setError((e as Error).message); }
  }
  const closed = f.status === "closed";
  return (
    <li className={`px-5 py-3.5 ${closed ? "bg-paper/40" : ""}`}>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left">
        <span className={`h-2 w-2 shrink-0 rounded-full ${closed ? "bg-leaf" : f.days_open > 2 ? "bg-short" : "bg-brass"}`} />
        <span className="min-w-0 flex-1">
          <span className={`block font-medium ${closed ? "text-ink-soft line-through decoration-ink-faint/50" : ""}`}>{f.title}</span>
          <span className="block text-xs text-ink-faint">{f.station}{f.date ? ` · ${fmtDay(f.date)}` : ""} · {f.kind_text} · raised by {f.created_by}, {closed ? `closed ${fmtWhen(f.closed_at)}` : `open ${f.days_open} ${f.days_open === 1 ? "day" : "days"}`}</span>
        </span>
        {f.amount > 0 && <Money value={f.amount} tone={closed ? "muted" : "short"} className="font-semibold" />}
        <Icon name="chevronRight" className={`h-4 w-4 text-ink-faint transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="mt-3 space-y-3 pl-5">
          {f.notes.length > 0 && (
            <ol className="space-y-1.5 border-l-2 border-paper-line pl-3 text-sm">
              {f.notes.map((n) => <li key={n.id}><span className="text-ink">{n.text}</span> <span className="text-xs text-ink-faint">— {n.by}, {fmtWhen(n.at)}</span></li>)}
            </ol>
          )}
          {!closed && (
            <form onSubmit={(e) => { e.preventDefault(); if (note.trim().length > 1) void act(`/supervisor/follow-ups/${f.id}/notes`, { text: note }); }} className="flex gap-2">
              <input className="field mt-0" value={note} maxLength={600} onChange={(e) => setNote(e.target.value)} placeholder="Add a note, e.g. called, he will deposit tomorrow" />
              <button disabled={note.trim().length < 2} className="btn-quiet shrink-0">Add note</button>
            </form>
          )}
          <FormError message={error} />
          <div className="flex flex-wrap gap-2">
            {!closed && <button onClick={() => setMessaging(true)} className="btn-quiet px-3 py-1.5 text-xs"><Icon name="spark" className="h-3.5 w-3.5" />Message to cashier</button>}
            {closed
              ? <button onClick={() => act(`/supervisor/follow-ups/${f.id}/reopen`)} className="btn-quiet px-3 py-1.5 text-xs">Open again</button>
              : <button onClick={() => act(`/supervisor/follow-ups/${f.id}/close`, { note: note.trim() })} className="btn-primary px-3 py-1.5 text-xs"><Icon name="check" className="h-3.5 w-3.5" />Sorted out, close it</button>}
          </div>
        </div>
      )}
      {messaging && <MessageDialog f={f} onClose={() => setMessaging(false)} />}
    </li>
  );
}

/** The follow-ups of the station being looked at (or all stations). */
export default function FollowUps({ title = "Follow-ups with cashiers" }: { title?: string }) {
  const [status, setStatus] = useState<"open" | "closed" | "all">("open");
  const [version, setVersion] = useState(0);
  const [raising, setRaising] = useState(false);
  const { data, error, loading, reload } = useApi<{ rows: FollowUp[]; open: number; closed: number }>(`/supervisor/follow-ups?status=${status}&v=${version}`);
  const changed = () => setVersion((v) => v + 1);
  const rows = Array.isArray(data?.rows) ? data!.rows : [];
  const owed = rows.filter((r) => r.status === "open").reduce((t, r) => t + r.amount, 0);
  return (
    <Panel flush title={title}
      action={<span className="flex flex-wrap items-center gap-2">
        {(["open", "closed", "all"] as const).map((s) => (
          <button key={s} onClick={() => setStatus(s)} className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${status === s ? "bg-ledger-800 text-white" : "bg-paper text-ink-soft hover:bg-paper-deep"}`}>
            {s === "open" ? `Open${data ? ` (${data.open})` : ""}` : s === "closed" ? "Closed" : "All"}</button>))}
        <button onClick={() => setRaising(true)} className="btn-primary px-3 py-1.5 text-xs"><Icon name="plus" className="h-3.5 w-3.5" />Raise follow-up</button>
      </span>}>
      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : rows.length === 0 ? (
        <Empty title={status === "open" ? "Nothing open" : "No follow-ups"} hint={status === "open" ? "Every follow-up raised with a cashier is sorted out." : "Raise one when a cashier's day has a problem."} />
      ) : (<>
        {status === "open" && owed > 0 && <p className="border-b border-paper-line px-5 py-2.5 text-sm text-ink-soft">Open amounts: <b className="num text-short">{fmtMoney(owed)}</b> SAR</p>}
        <ul className="divide-y divide-paper-line">{rows.map((f) => <Item key={f.id} f={f} onChanged={changed} />)}</ul>
      </>)}
      {raising && <RaiseDialog draft={{}} onClose={() => setRaising(false)} onSaved={() => { setRaising(false); setStatus("open"); changed(); }} />}
    </Panel>
  );
}
