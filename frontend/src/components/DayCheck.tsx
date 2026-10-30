import { useState } from "react";
import { fmtDay, fmtWhen, send, useApi } from "../lib";
import { Icon } from "./icons";
import { FormError } from "./ui";

type Check = { checked_by: string; checked_at: string; note: string } | null;

/** The supervisor's sign-off: this station's day has been checked, by whom and when. */
export default function DayCheck({ day, stationId, empty = false }: { day: string; stationId: number; empty?: boolean }) {
  const [version, setVersion] = useState(0);
  const { data } = useApi<{ check: Check }>(`/supervisor/check?date=${day}&station_id=${stationId}&v=${version}`);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const c = data?.check;
  async function act(method: string) {
    setBusy(true); setError(null);
    try {
      if (method === "POST") await send("/supervisor/check", "POST", { date: day, station_id: stationId, note });
      else await send(`/supervisor/check?date=${day}&station_id=${stationId}`, "DELETE");
      setNote(""); setVersion((v) => v + 1);
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  if (!data) return null;
  if (empty && !data.check) return null;  // nothing came in on this day, so there is nothing to sign off
  return c ? (
    <div className="mb-6 flex flex-wrap items-center gap-3 rounded-panel border border-leaf/30 bg-leaf-soft/60 px-5 py-3 text-sm">
      <span className="grid h-7 w-7 place-items-center rounded-full bg-leaf text-white"><Icon name="check" className="h-4 w-4" /></span>
      <span className="flex-1 text-leaf-dark"><b>{fmtDay(day)} checked</b> by {c.checked_by}, {fmtWhen(c.checked_at)}{c.note ? <> · “{c.note}”</> : null}</span>
      <button disabled={busy} onClick={() => act("DELETE")} className="text-xs font-medium text-ink-soft underline underline-offset-2 hover:text-ink">Undo</button>
    </div>
  ) : (
    <div className="mb-6 flex flex-wrap items-center gap-3 rounded-panel border border-dashed border-paper-line bg-white px-5 py-3 text-sm">
      <span className="text-ink-soft">When you have looked at every tab, sign the day off:</span>
      <input className="field mt-0 min-w-[12rem] flex-1 py-1.5" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" />
      <button disabled={busy} onClick={() => act("POST")} className="btn-primary px-3 py-1.5 text-xs"><Icon name="check" className="h-3.5 w-3.5" />Mark {fmtDay(day)} as checked</button>
      <FormError message={error} />
    </div>
  );
}
