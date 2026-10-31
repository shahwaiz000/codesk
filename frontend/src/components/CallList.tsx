import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FollowDraft, RaiseDialog } from "./FollowUps";
import { fmtDay, useApi } from "../lib";
import { useStation } from "../stations";
import type { StationDay, StationOverview } from "../types";
import { Icon } from "./icons";
import { Money, Panel } from "./ui";

const LEVEL = {
  call: { bar: "bg-short", chip: "bg-short-soft text-short-dark", text: "Call" },
  check: { bar: "bg-brass", chip: "bg-brass-soft text-brass-dark", text: "Check" },
  ok: { bar: "bg-leaf", chip: "bg-leaf-soft text-leaf-dark", text: "Fine" },
};

function File({ ok, label, note }: { ok: boolean | null; label: string; note?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs ${ok === null ? "bg-paper text-ink-faint" : ok ? "bg-leaf-soft text-leaf-dark" : "bg-short-soft text-short-dark"}`}
      title={note ?? (ok ? `${label}: received` : ok === null ? `${label}: not needed yet` : `${label}: missing`)}>
      {ok === null ? <span className="h-3 w-3 text-center leading-3">·</span> : <Icon name={ok ? "check" : "close"} className="h-3 w-3" />}{label}
    </span>
  );
}

/** The supervisor's first look: every station with drivers, the ones to call on top, and which files each cashier sent. */
export default function CallList({ day, only }: { day: string; only?: number }) {
  const { data } = useApi<StationOverview>(`/stations/overview?date=${day}`);
  const { choose } = useStation();
  const go = useNavigate();
  const [raising, setRaising] = useState<FollowDraft | null>(null);
  const draftFor = (s: StationDay, p: StationDay["problems"][number]): FollowDraft => ({
    station_id: s.id, kind: p.kind ?? "other", title: p.text.replace(/\s*\(.*\)$/, ""), amount: p.amount ?? 0, date: p.date ?? day });
  const rows: StationDay[] = (Array.isArray(data?.stations) ? data!.stations : []).filter((r) => only == null || r.id === only);
  if (!data) return null;
  const count = (l: string) => rows.filter((r) => r.level === l).length;

  return (
    <Panel flush className="mb-6" title={only == null ? `Who needs a call on ${fmtDay(day)}` : `Does the cashier need a call? ${fmtDay(day)}`}
      action={<span className="flex flex-wrap items-center gap-1.5 text-xs font-semibold">
        {rows.length > 0 && (() => { const done = rows.filter((r) => r.check).length; return (
          <span className={`mr-2 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 ${done === rows.length ? "bg-leaf text-white" : "bg-ledger-800 text-white"}`}>
            <Icon name="check" className="h-3.5 w-3.5" />{done} of {rows.length} checked</span>); })()}
        {(["call", "check", "ok"] as const).map((l) => <span key={l} className={`rounded-full px-2.5 py-0.5 ${LEVEL[l].chip}`}>{count(l)} {LEVEL[l].text.toLowerCase()}</span>)}
      </span>}>
      {rows.length === 0 ? <p className="px-5 py-6 text-sm text-ink-soft">No station has drivers yet. Import your drivers with their station first.</p> : (
        <ul className="divide-y divide-paper-line">
          {rows.map((s) => (
            <li key={s.id} className="relative grid gap-3 py-3.5 pl-6 pr-5 md:grid-cols-[13rem_minmax(0,1fr)_auto] md:items-center">
              <span className={`absolute inset-y-2 left-0 w-1 rounded-r ${LEVEL[s.level].bar}`} />
              <span className="min-w-0">
                <span className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${LEVEL[s.level].chip}`}>{LEVEL[s.level].text}</span>
                  <span className="truncate font-semibold">{s.name}</span>
                </span>
                {s.check
                  ? <span className="mt-1 inline-flex items-center gap-1 text-xs text-leaf-dark"><Icon name="check" className="h-3 w-3" />Checked by {s.check.checked_by}</span>
                  : <span className="mt-1 block text-xs font-medium text-brass-dark">Not checked yet</span>}
                <span className="mt-0.5 block text-xs text-ink-faint">{s.code} · {s.handed_over}/{s.drivers} drivers · cash <Money value={s.cash_received} /></span>
              </span>
              <span className="min-w-0 space-y-1.5">
                <span className="flex flex-wrap gap-1">
                  <File ok={s.files.report} label="Report" />
                  <File ok={s.files.report ? s.files.pos_orders : null} label="POS orders" />
                  <File ok={s.files.pos_orders ? s.files.terminal_sheet : null} label="Machine sheet" />
                  <File ok={s.files.report ? true : null} label={`Expenses${s.files.expenses ? ` (${s.files.expenses})` : ""}`} note={s.files.expenses ? `${s.files.expenses} payments` : "No payments on this day"} />
                  <File ok={s.files.slip === "sent" ? true : s.files.slip === "missing" ? false : null} label="Bank slip"
                    note={s.files.slip === "sent" ? "Bank slip recorded" : s.files.slip === "waiting" ? "Not due yet: the cash goes to the bank the next working day" : s.files.slip === "missing" ? "The deposit is late" : "Nothing to deposit"} />
                </span>
                {s.problems.length > 0 && (
                  <span className="block text-sm">
                    {s.problems.map((p, i) => (
                      <span key={i} className={`mr-3 inline-block ${p.level === "call" ? "text-short" : "text-brass-dark"}`}>{p.text}
                        <button onClick={() => setRaising(draftFor(s, p))} className="ml-1.5 rounded px-1 text-xs font-medium text-ink-soft underline underline-offset-2 hover:text-ink">raise follow-up</button>
                      </span>))}
                  </span>
                )}
              </span>
              <button onClick={() => { choose(s.id); go("/station"); }}
                className={`justify-self-start whitespace-nowrap md:justify-self-end ${s.level === "ok" ? "btn-quiet" : "btn-primary"} px-3 py-1.5 text-xs`}>
                Review<Icon name="chevronRight" className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {raising && <RaiseDialog draft={raising} onClose={() => setRaising(null)} onSaved={() => setRaising(null)} />}
    </Panel>
  );
}
