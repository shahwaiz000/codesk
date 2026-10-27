import { FormEvent, useState } from "react";
import { fmtDay, fmtMoney, parseAmount, send } from "../lib";
import type { Handover } from "../types";
import { FormError, Modal } from "./ui";

type DriverOption = { id: number; code: string; name: string };

const asText = (n: number | undefined) => (n == null ? "" : String(n));

/** Record or correct one driver's handover. The cash difference updates while you type. */
export default function HandoverDialog({ day, handover, drivers, presetDriver, onClose, onSaved }: {
  day: string; handover: Handover | null; drivers: DriverOption[]; presetDriver?: number;
  onClose: () => void; onSaved: () => void;
}) {
  const [driverId, setDriverId] = useState<number | "">(handover?.driver_id ?? presetDriver ?? "");
  const [orders, setOrders] = useState(asText(handover?.orders));
  const [expected, setExpected] = useState(asText(handover?.expected_cash));
  const [received, setReceived] = useState(asText(handover?.cash_received));
  const [pos, setPos] = useState(asText(handover?.pos_amount));
  const [note, setNote] = useState(handover?.note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const exp = parseAmount(expected);
  const rec = parseAmount(received);
  const diff = exp != null && rec != null ? Math.round((rec - exp) * 100) / 100 : null;
  const ready = driverId !== "" && exp != null && rec != null && (pos.trim() === "" || parseAmount(pos) != null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true); setError(null);
    try {
      await send("/collections", "PUT", {
        business_date: day, driver_id: driverId, orders: Number(orders || 0),
        expected_cash: expected, cash_received: received, pos_amount: pos.trim() || "0", note,
      });
      onSaved();
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }

  const options = handover ? drivers.filter((d) => d.id === handover.driver_id) : drivers;
  return (
    <Modal title={handover ? `Correct ${handover.driver_code} handover` : "Record a handover"} onClose={onClose} width="max-w-lg">
      <form onSubmit={submit} className="space-y-4">
        <p className="-mt-3 text-sm text-ink-soft">Business date {fmtDay(day, true)}</p>
        <div className="grid grid-cols-[1fr_7rem] gap-3">
          <label className="block text-sm font-medium">Driver
            <select className="field" value={driverId} disabled={!!handover} onChange={(e) => setDriverId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Choose a driver</option>
              {options.map((d) => <option key={d.id} value={d.id}>{d.code}  {d.name}</option>)}
            </select></label>
          <label className="block text-sm font-medium">COD orders
            <input className="field num" inputMode="numeric" value={orders} onChange={(e) => setOrders(e.target.value.replace(/\D/g, ""))} /></label>
        </div>

        <fieldset className="rounded-lg border border-paper-line p-4">
          <legend className="px-1 text-sm font-medium">Cash</legend>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm text-ink-soft">Expected (system)
              <input className="field num text-right" inputMode="decimal" value={expected} onChange={(e) => setExpected(e.target.value)} placeholder="0.00" /></label>
            <label className="block text-sm text-ink-soft">Counted at the desk
              <input className="field num text-right" inputMode="decimal" value={received} onChange={(e) => setReceived(e.target.value)} placeholder="0.00" /></label>
          </div>
          <p aria-live="polite" className={`mt-3 flex items-center justify-between rounded-md px-3 py-2 text-sm ${diff == null ? "bg-paper text-ink-faint" : diff < 0 ? "bg-short-soft text-short-dark" : diff > 0 ? "bg-brass-soft text-brass-dark" : "bg-leaf-soft text-leaf-dark"}`}>
            <span>{diff == null ? "Enter both amounts to see the difference" : diff < 0 ? "Driver is short" : diff > 0 ? "Driver handed over extra" : "Cash agrees"}</span>
            {diff != null && <span className="num font-semibold">{diff > 0 ? "+" : ""}{fmtMoney(diff)}</span>}
          </p>
        </fieldset>

        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium">POS (card) total
            <input className="field num text-right" inputMode="decimal" value={pos} onChange={(e) => setPos(e.target.value)} placeholder="0.00" /></label>
          <label className="block text-sm font-medium">Note
            <input className="field" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder={diff && diff < 0 ? "Reason for the shortage" : "Optional"} /></label>
        </div>
        <FormError message={error} />
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="btn-quiet">Cancel</button>
          <button disabled={busy || !ready} className="btn-primary">{handover ? "Save correction" : "Save handover"}</button>
        </div>
      </form>
    </Modal>
  );
}
