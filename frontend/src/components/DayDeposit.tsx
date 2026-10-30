import { useState } from "react";
import { DepositDialog, Slips, TONE } from "../pages/Deposits";
import { fmtDay, send, useApi } from "../lib";
import type { DepositLedger, Slip } from "../types";
import SlipReader from "./SlipReader";
import { Badge, ErrorBox, FormError, Loading, Modal, Panel } from "./ui";

/** The bank deposit of one station's day: what it had to deposit, the slips, and recording a new one. */
export default function DayDeposit({ day }: { day: string }) {
  const [version, setVersion] = useState(0);
  const { data, error, loading, reload } = useApi<DepositLedger>(`/deposits?end=${day}&count=1&v=${version}`);
  const [depositing, setDepositing] = useState(false);
  const [deleting, setDeleting] = useState<Slip | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const changed = () => setVersion((v) => v + 1);
  const row = data?.rows?.find((r) => r.date === day);

  async function confirmDelete() {
    if (!deleting) return;
    try { await send(`/deposits/${deleting.id}`, "DELETE"); setDeleting(null); changed(); }
    catch (e) { setActionError((e as Error).message); setDeleting(null); }
  }

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error} retry={reload} />;
  return (
    <>
      <Panel title={`Bank deposit for the cash of ${fmtDay(day)}`}
        action={row && <span className="flex items-center gap-2">
          <Badge tone={TONE[row.status]}>{row.status_text}</Badge>
          {row.late && <Badge tone="short">{row.days_late} {row.days_late === 1 ? "day" : "days"} late</Badge>}
          {row.pending > 0 && <button onClick={() => setDepositing(true)} className="btn-primary px-3 py-1.5 text-xs">Record deposit</button>}
        </span>}>
        <FormError message={actionError} />
        {row ? <>
          <p className="mb-4 text-sm text-ink-soft">Due in the bank on <b className="text-ink">{fmtDay(row.due_on, true)}</b>
            {row.paid_later_on && <>. The short amount was paid on <b className="text-leaf-dark">{fmtDay(row.paid_later_on)}</b></>}.</p>
          <Slips row={row} onDelete={setDeleting} />
        </> : <p className="text-sm text-ink-soft">No cash recorded for this day, so there is nothing to deposit.</p>}
      </Panel>
      {data && <div className="mt-6"><SlipReader days={data.rows} onRecorded={changed} /></div>}
      {depositing && row && data && (
        <DepositDialog row={row} banks={data.banks} onClose={() => setDepositing(false)} onSaved={() => { setDepositing(false); changed(); }} />
      )}
      {deleting && (
        <Modal title={`Delete slip ${deleting.slip_ref}?`} onClose={() => setDeleting(null)}>
          <p className="text-sm text-ink-soft">The day will show this amount as not deposited again, and the deletion is written to the activity log.</p>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setDeleting(null)} className="btn-quiet">Keep it</button>
            <button onClick={confirmDelete} className="btn-danger">Delete slip</button>
          </div>
        </Modal>
      )}
    </>
  );
}
