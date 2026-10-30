import { FormEvent, useMemo, useState } from "react";
import { Icon } from "../components/icons";
import { Badge, ErrorBox, FormError, Loading, Modal, PageHeader } from "../components/ui";
import { send, useApi } from "../lib";
import { byRegion, useStation } from "../stations";
import type { Station, StationList } from "../types";

const REGIONS = ["Riyadh", "Makkah", "Madinah", "Eastern Province", "Qassim", "Asir", "Tabuk", "Hail", "Northern Borders",
  "Jazan", "Najran", "Al Baha", "Al Jouf"];

function StationForm({ station, onClose, onSaved }: { station: Station | null; onClose: () => void; onSaved: () => void }) {
  const [code, setCode] = useState(station?.code ?? "");
  const [name, setName] = useState(station?.name ?? "");
  const [city, setCity] = useState(station?.city ?? "");
  const [region, setRegion] = useState(station?.region ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    const body = { code, name, city, region, active: station?.active ?? true };
    try {
      if (station) await send(`/stations/${station.id}`, "PUT", body);
      else await send("/stations", "POST", body);
      onSaved();
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }
  return (
    <Modal title={station ? `Edit ${station.name}` : "Add a station"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-[7rem_1fr] gap-3">
          <label className="block text-sm font-medium">Code
            <input className="field num uppercase" value={code} maxLength={30} onChange={(e) => setCode(e.target.value)} placeholder="JED2" /></label>
          <label className="block text-sm font-medium">Station name
            <input className="field" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="Jeddah South" /></label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium">City
            <input className="field" value={city} maxLength={60} onChange={(e) => setCity(e.target.value)} /></label>
          <label className="block text-sm font-medium">Region
            <input className="field" list="region-list" value={region} maxLength={60} onChange={(e) => setRegion(e.target.value)} />
            <datalist id="region-list">{REGIONS.map((r) => <option key={r} value={r} />)}</datalist></label>
        </div>
        <p className="text-xs text-ink-faint">Use the same code or name as the Site column of your system's reports, so imports find this station by themselves.</p>
        <FormError message={error} />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-quiet">Cancel</button>
          <button disabled={busy || code.trim().length < 2 || name.trim().length < 2} className="btn-primary">{station ? "Save changes" : "Add station"}</button>
        </div>
      </form>
    </Modal>
  );
}

function Unassigned({ count, stations, onDone }: { count: number; stations: Station[]; onDone: (text: string) => void }) {
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function move() {
    setBusy(true); setError(null);
    try {
      const r = await send<{ drivers: number; station: Station }>(`/stations/${target}/adopt`, "POST");
      onDone(`${r.drivers} ${r.drivers === 1 ? "driver" : "drivers"} put in ${r.station.name}, with their past records.`);
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  return (
    <div className="mb-6 rounded-panel border border-brass/30 bg-brass-soft/60 p-4">
      <p className="text-sm font-medium text-brass-dark">{count} {count === 1 ? "driver has" : "drivers have"} no station yet</p>
      <p className="mt-0.5 text-sm text-ink-soft">Put them all in one station. Their handovers, expenses and deposits from before move with them.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select aria-label="Put them in" className="field mt-0 w-auto" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Choose the station</option>
          {byRegion(stations.filter((s) => s.active)).map(([region, list]) => (
            <optgroup key={region} label={region}>{list.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.code})</option>)}</optgroup>
          ))}
        </select>
        <button disabled={!target || busy} onClick={move} className="btn-primary">Put them in this station</button>
      </div>
      <FormError message={error} />
    </div>
  );
}

export default function Stations() {
  const { data, error, loading, reload } = useApi<StationList>("/stations");
  const { station: current, choose, refresh } = useStation();
  const [editing, setEditing] = useState<Station | "new" | null>(null);
  const [query, setQuery] = useState("");
  const [showOff, setShowOff] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const changed = () => { reload(); refresh(); };

  const list = Array.isArray(data?.stations) ? data!.stations : [];
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return byRegion(list.filter((s) => (showOff || s.active)
      && (!q || [s.code, s.name, s.city, s.region].some((x) => x.toLowerCase().includes(q)))));
  }, [list, query, showOff]);
  const active = list.filter((s) => s.active);
  const staffed = active.filter((s) => s.drivers > 0).length;

  async function toggle(s: Station) {
    setActionError(null);
    try { await send(`/stations/${s.id}`, "PUT", { ...s, active: !s.active }); changed(); }
    catch (e) { setActionError((e as Error).message); }
  }

  return (
    <>
      <PageHeader title="Stations" subtitle="Every warehouse across the Kingdom, each with its own drivers, cash and bank deposits. Choose a station at the top of the menu to work on it, or All stations to see them together.">
        <button onClick={() => setEditing("new")} className="btn-primary"><Icon name="plus" className="h-4 w-4" />Add station</button>
      </PageHeader>
      {loading && !data ? <Loading /> : error ? <ErrorBox message={error} retry={reload} /> : data && (
        <>
          <dl className="mb-6 grid grid-cols-3 overflow-hidden rounded-panel bg-white shadow-panel [&>div:not(:last-child)]:border-r [&>div]:border-paper-line">
            <div className="p-5"><dt className="text-sm text-ink-soft">Active stations</dt><dd className="num mt-1 text-2xl font-semibold">{active.length}</dd></div>
            <div className="p-5"><dt className="text-sm text-ink-soft">With drivers</dt><dd className="num mt-1 text-2xl font-semibold">{staffed}</dd></div>
            <div className="p-5"><dt className="text-sm text-ink-soft">Drivers without a station</dt>
              <dd className={`num mt-1 text-2xl font-semibold ${data.unassigned_drivers ? "text-brass-dark" : ""}`}>{data.unassigned_drivers}</dd>
              {data.unassigned_drivers > 0 && <dd className="mt-1 text-xs text-ink-faint">Import a report with a Site column, or put them in a station below</dd>}</div>
          </dl>

          {data.unassigned_drivers > 0 && <Unassigned count={data.unassigned_drivers} stations={list} onDone={(t) => { setDone(t); changed(); }} />}
          {done && <p className="mb-4 rounded-md bg-leaf-soft px-3 py-2 text-sm text-leaf-dark">{done}</p>}
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <label className="relative min-w-[14rem] flex-1 sm:max-w-xs">
              <span className="sr-only">Search stations</span>
              <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
              <input className="field mt-0 pl-9" placeholder="Search by code, city or region" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <label className="ml-auto flex items-center gap-2 text-sm text-ink-soft">
              <input type="checkbox" className="h-4 w-4 accent-ledger-700" checked={showOff} onChange={(e) => setShowOff(e.target.checked)} />Show switched off</label>
          </div>
          <FormError message={actionError} />

          <div className="space-y-6">
            {groups.map(([region, stations]) => (
              <section key={region}>
                <h2 className="mb-2 flex items-baseline gap-2 text-sm font-semibold text-ink">{region}
                  <span className="text-xs font-normal text-ink-faint">{stations.length} {stations.length === 1 ? "station" : "stations"}, {stations.reduce((t, s) => t + s.drivers, 0)} drivers</span></h2>
                <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {stations.map((s) => {
                    const here = current?.id === s.id;
                    return (
                      <li key={s.id} className={`group relative overflow-hidden rounded-panel bg-white p-4 shadow-panel transition hover:shadow-pop ${here ? "ring-2 ring-brass-glow" : ""} ${s.active ? "" : "opacity-60"}`}>
                        <span aria-hidden="true" className="absolute -right-3 -top-3 grid h-16 w-16 place-items-center rounded-full bg-paper text-ledger-700/20"><Icon name="warehouse" className="h-8 w-8" /></span>
                        <div className="relative flex items-start gap-3">
                          <span className="num grid h-10 w-12 shrink-0 place-items-center rounded-lg bg-ledger-900 text-xs font-bold tracking-wide text-brass-glow">{s.code}</span>
                          <span className="min-w-0">
                            <span className="block truncate font-semibold">{s.name}</span>
                            <span className="block truncate text-xs text-ink-faint">{s.city && s.city !== s.name ? `${s.city}, ` : ""}{s.region || "Region not set"}</span>
                          </span>
                        </div>
                        <div className="relative mt-4 flex items-center justify-between gap-2">
                          <span className="flex items-center gap-1.5 text-sm text-ink-soft"><Icon name="drivers" className="h-4 w-4" />
                            <span className="num font-medium text-ink">{s.drivers}</span> {s.drivers === 1 ? "driver" : "drivers"}</span>
                          {!s.active ? <Badge tone="muted">Switched off</Badge> : here ? <Badge tone="brass">Looking at it</Badge> : null}
                        </div>
                        <div className="relative mt-3 flex gap-1 border-t border-paper-line pt-3">
                          {s.active && !here && <button onClick={() => choose(s.id)} className="rounded-md px-2 py-1 text-xs font-semibold text-leaf-dark hover:bg-leaf-soft">Open</button>}
                          <button onClick={() => setEditing(s)} className="rounded-md px-2 py-1 text-xs font-medium text-ink-soft hover:bg-paper-deep hover:text-ink" aria-label={`Edit ${s.name}`}>Edit</button>
                          <button onClick={() => toggle(s)} className="ml-auto rounded-md px-2 py-1 text-xs font-medium text-ink-soft hover:bg-paper-deep hover:text-ink">{s.active ? "Switch off" : "Switch on"}</button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
            {groups.length === 0 && <p className="text-sm text-ink-soft">No station matches.</p>}
          </div>
        </>
      )}
      {editing && <StationForm station={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); changed(); }} />}
    </>
  );
}
