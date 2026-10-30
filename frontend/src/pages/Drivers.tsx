import { FormEvent, useMemo, useState } from "react";
import { Icon } from "../components/icons";
import ImportDialog, { PreviewRow } from "../components/ImportDialog";
import { Badge, Empty, ErrorBox, FormError, Loading, Modal, Money, PageHeader, Panel } from "../components/ui";
import { fmtDay, send, useApi } from "../lib";
import { byRegion, useStation } from "../stations";
import type { Driver } from "../types";

type Draft = { code: string; name: string; phone: string; hub: string; pos_terminal: string; station_id: string };
const BLANK: Draft = { code: "", name: "", phone: "", hub: "", pos_terminal: "", station_id: "" };

function DriverForm({ driver, hubs, onClose, onSaved }: { driver: Driver | null; hubs: string[]; onClose: () => void; onSaved: () => void }) {
  const { station, stations } = useStation();
  const [draft, setDraft] = useState<Draft>(driver
    ? { code: driver.code, name: driver.name, phone: driver.phone, hub: driver.hub, pos_terminal: driver.pos_terminal, station_id: driver.station_id ? String(driver.station_id) : "" }
    : { ...BLANK, station_id: station ? String(station.id) : "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const station_id = draft.station_id ? Number(draft.station_id) : null;
      if (driver) await send(`/drivers/${driver.id}`, "PATCH", { name: draft.name, phone: draft.phone, hub: draft.hub, pos_terminal: draft.pos_terminal, station_id });
      else await send("/drivers", "POST", { ...draft, station_id });
      onSaved();
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }

  return (
    <Modal title={driver ? `Edit ${driver.code}` : "Add a driver"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-[8rem_1fr] gap-3">
          <label className="block text-sm font-medium">Driver ID
            <input className="field uppercase disabled:bg-paper disabled:text-ink-soft" value={draft.code} onChange={set("code")} disabled={!!driver} placeholder="D-113" /></label>
          <label className="block text-sm font-medium">Full name
            <input className="field" value={draft.name} onChange={set("name")} /></label>
        </div>
        <label className="block text-sm font-medium">Station
          <select className="field" value={draft.station_id} onChange={set("station_id")}>
            <option value="">Choose the station</option>
            {byRegion(stations.filter((s) => s.active || String(s.id) === draft.station_id)).map(([region, list]) => (
              <optgroup key={region} label={region}>{list.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.code})</option>)}</optgroup>
            ))}
          </select>
          {driver && driver.station_id && String(driver.station_id) !== draft.station_id && (
            <span className="mt-1 block text-xs font-normal text-ink-faint">His past handovers stay with {driver.station}; new ones go to the new station.</span>)}</label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium">Hub
            <input className="field" list="hub-list" value={draft.hub} onChange={set("hub")} />
            <datalist id="hub-list">{hubs.map((h) => <option key={h} value={h} />)}</datalist></label>
          <label className="block text-sm font-medium">Mobile
            <input className="field" inputMode="tel" value={draft.phone} onChange={set("phone")} placeholder="05XXXXXXXX" /></label>
        </div>
        <label className="block text-sm font-medium">POS terminal ID
          <input className="field num" value={draft.pos_terminal} onChange={set("pos_terminal")} placeholder="From your terminal sheet, e.g. 60311101" />
          <span className="mt-1 block text-xs font-normal text-ink-faint">Used to match the terminal sheet to this driver. One terminal belongs to one active driver.</span></label>
        {driver && <p className="text-xs text-ink-faint">The driver ID cannot change, because collections and expenses are linked to it.</p>}
        <FormError message={error} />
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="btn-quiet">Cancel</button>
          <button disabled={busy || draft.code.trim().length < 2 || draft.name.trim().length < 2} className="btn-primary">
            {driver ? "Save changes" : "Add driver"}</button>
        </div>
      </form>
    </Modal>
  );
}

const DRIVER_PREVIEW = [
  { label: "Driver ID", cell: (r: PreviewRow) => <span className="num font-medium">{(r.driver_code as string) ?? "-"}</span> },
  { label: "Name", cell: (r: PreviewRow) => <>{r.driver_name as string}{r.inactive ? <span className="ml-1.5 text-xs text-ink-faint">(inactive)</span> : null}</> },
  { label: "Station", cell: (r: PreviewRow) => <span className="text-ink-soft">{(r.station as string) || "-"}</span> },
  { label: "Hub", cell: (r: PreviewRow) => <span className="text-ink-soft">{(r.hub as string) || "-"}</span> },
  { label: "POS terminal", cell: (r: PreviewRow) => <span className="num text-ink-soft">{(r.terminal as string) ?? "-"}</span> },
];

export default function Drivers({ embedded = false }: { embedded?: boolean }) {
  const { data, error, loading, reload } = useApi<Driver[]>("/drivers");
  const { station, refresh: refreshStations } = useStation();
  const [query, setQuery] = useState("");
  const [hub, setHub] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Driver | "new" | null>(null);
  const [importing, setImporting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const hubs = useMemo(() => [...new Set((data ?? []).map((d) => d.hub).filter(Boolean))].sort(), [data]);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter((d) => (showInactive || d.active) && (!hub || d.hub === hub)
      && (!q || d.code.toLowerCase().includes(q) || d.name.toLowerCase().includes(q) || d.phone.includes(q) || d.pos_terminal.toLowerCase().includes(q)));
  }, [data, query, hub, showInactive]);

  const active = (data ?? []).filter((d) => d.active);
  const totals = {
    shortage: active.reduce((s, d) => s + d.cash_shortage, 0),
    advances: (data ?? []).reduce((s, d) => s + d.open_advances, 0),
    advanceDrivers: (data ?? []).filter((d) => d.open_advance_count > 0).length,
    inactive: (data ?? []).length - active.length,
  };

  async function toggleActive(d: Driver) {
    setActionError(null);
    try { await send(`/drivers/${d.id}`, "PATCH", { active: !d.active }); reload(); }
    catch (e) { setActionError((e as Error).message); }
  }

  return (
    <>
      <PageHeader embedded={embedded} title="Drivers" subtitle={`The driver IDs every collection, POS check and expense is matched against${station ? `, at ${station.name}` : ", at every station"}. Open advances cover all recorded days.`}>
        <button onClick={() => setImporting(true)} className="btn-quiet"><Icon name="upload" className="h-4 w-4" />Import drivers</button>
        <button onClick={() => setEditing("new")} className="btn-primary"><Icon name="plus" className="h-4 w-4" />Add driver</button>
      </PageHeader>

      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && (
        <>
          <dl className="mb-6 grid grid-cols-1 overflow-hidden rounded-panel bg-white shadow-panel sm:grid-cols-2">
            <div className="border-b border-paper-line p-5 sm:border-b-0 sm:border-r">
              <dt className="text-sm text-ink-soft">Active drivers</dt>
              <dd className="num mt-1 text-2xl font-semibold">{active.length}{totals.inactive > 0 && <span className="ml-2 text-sm font-normal text-ink-faint">+{totals.inactive} inactive</span>}</dd>
            </div>
            <div className="p-5">
              <dt className="text-sm text-ink-soft">Advances not yet recovered</dt>
              <dd className="mt-1 text-2xl font-semibold"><Money value={totals.advances} tone={totals.advances ? "brass" : undefined} /> <span className="text-sm font-normal text-ink-faint">SAR, {totals.advanceDrivers} {totals.advanceDrivers === 1 ? "driver" : "drivers"}</span></dd>
            </div>
          </dl>

          <Panel flush>
            <div className="flex flex-wrap items-center gap-3 border-b border-paper-line px-5 py-3.5">
              <label className="relative min-w-[14rem] flex-1 sm:max-w-xs">
                <span className="sr-only">Search drivers</span>
                <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
                <input className="field mt-0 pl-9" placeholder="Search by ID, name, mobile or terminal" value={query} onChange={(e) => setQuery(e.target.value)} />
              </label>
              <label className="text-sm"><span className="sr-only">Hub</span>
                <select className="field mt-0 w-auto" value={hub} onChange={(e) => setHub(e.target.value)}>
                  <option value="">All hubs</option>{hubs.map((h) => <option key={h}>{h}</option>)}
                </select></label>
              <label className="ml-auto flex items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" className="h-4 w-4 accent-ledger-700" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
                Show inactive
              </label>
            </div>
            {actionError && <div className="px-5 pt-4"><FormError message={actionError} /></div>}
            {rows.length === 0 ? (
              data.length === 0
                ? <Empty title="No drivers yet" hint="Import your driver list, or add drivers one by one, with the same IDs your delivery system uses so other imports match them.">
                    <div className="flex justify-center gap-2">
                      <button onClick={() => setImporting(true)} className="btn-quiet">Import drivers</button>
                      <button onClick={() => setEditing("new")} className="btn-primary">Add driver</button>
                    </div>
                  </Empty>
                : <Empty title="No driver matches" hint="Try another search, choose all hubs, or show inactive drivers." />
            ) : (
              <div className="relative overflow-x-auto">
                <table className="w-full min-w-[860px] text-sm">
                  <thead>
                    <tr className="border-b border-paper-line text-left text-xs text-ink-faint">
                      <th className="px-5 py-2.5 font-medium">Driver</th>
                      {!station && <th className="px-3 py-2.5 font-medium">Station</th>}
                      <th className="px-3 py-2.5 font-medium">Hub</th>
                      <th className="px-3 py-2.5 font-medium">POS terminal</th>
                      <th className="px-3 py-2.5 font-medium">Last handover</th>
                      <th className="px-3 py-2.5 text-right font-medium">Open advances (SAR)</th>
                      <th className="px-5 py-2.5 text-right font-medium"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((d) => (
                      <tr key={d.id} className={`border-b border-paper-line last:border-0 hover:bg-paper/60 ${d.active ? "" : "text-ink-faint"}`}>
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-3">
                            <span className="num shrink-0 whitespace-nowrap font-semibold text-ink-soft">{d.code}</span>
                            <span className="min-w-0">
                              <span className={`block truncate font-medium ${d.active ? "text-ink" : ""}`}>{d.name}</span>
                              {d.phone && <span className="num block text-xs text-ink-faint">{d.phone}</span>}
                            </span>
                            {!d.active && <Badge tone="muted">Inactive</Badge>}
                          </div>
                        </td>
                        {!station && <td className="px-3 py-3">{d.station
                          ? <span className="inline-flex items-center gap-1.5 text-ink-soft"><span className="num rounded bg-paper-deep px-1.5 py-0.5 text-[11px] font-semibold text-ink-soft">{d.station_code}</span>{d.station}</span>
                          : <span className="text-xs text-brass-dark">Not set</span>}</td>}
                        <td className="px-3 py-3 text-ink-soft">{d.hub || "-"}</td>
                        <td className="num px-3 py-3 text-ink-soft">{d.pos_terminal || <span className="text-ink-faint">Not set</span>}</td>
                        <td className="px-3 py-3 text-ink-soft">{d.last_collection ? fmtDay(d.last_collection) : "None yet"}</td>
                        <td className="px-3 py-3 text-right">
                          {d.open_advances > 0
                            ? <span title={`${d.open_advance_count} open`}><Money value={d.open_advances} tone="brass" className="font-medium" /></span>
                            : <span className="text-ink-faint">-</span>}
                        </td>
                        <td className="px-5 py-3">
                          <div className="flex justify-end gap-1">
                            <button onClick={() => setEditing(d)} className="rounded-md px-2 py-1 text-xs font-medium text-ink-soft hover:bg-paper-deep hover:text-ink" aria-label={`Edit ${d.code}`}>Edit</button>
                            <button onClick={() => toggleActive(d)} className="rounded-md px-2 py-1 text-xs font-medium text-ink-soft hover:bg-paper-deep hover:text-ink">
                              {d.active ? "Deactivate" : "Reactivate"}</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}

      {importing && (
        <ImportDialog day="" noDate title="Import drivers" endpoint="/drivers/import" templateUrl="/api/drivers/template"
          noun={["driver", "drivers"]} columns={DRIVER_PREVIEW}
          intro="Upload your driver list as CSV or Excel. Each row needs the driver ID and name; station, hub, mobile and POS terminal ID are optional. A system report with a Site column puts each driver in his station, and a station not seen before is added. Drivers already saved are updated, never doubled, and an empty cell never wipes a saved value."
          onClose={() => setImporting(false)} onSaved={() => { setImporting(false); reload(); refreshStations(); }} />
      )}
      {editing && (
        <DriverForm driver={editing === "new" ? null : editing} hubs={hubs}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />
      )}
    </>
  );
}
