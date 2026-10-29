import { ReactNode, createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, currentStation, rememberStation } from "./lib";
import type { Station, StationList } from "./types";

interface StationValue {
  /** The station being looked at, or null for all stations. */
  station: Station | null;
  stations: Station[];
  choose: (id: number | null) => void;
  refresh: () => void;
  /** Changes whenever the station changes, so pages reload their figures. */
  version: number;
}
const StationContext = createContext<StationValue>({ station: null, stations: [], choose: () => {}, refresh: () => {}, version: 0 });
export const useStation = () => useContext(StationContext);

/** Which station (warehouse) the desk is looking at. Every request carries it (see lib.ts). */
export function StationProvider({ children }: { children: ReactNode }) {
  const [stations, setStations] = useState<Station[]>([]);
  const [id, setId] = useState(currentStation());
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => {
    api<StationList>("/stations").then((d) => {
      const list = Array.isArray(d?.stations) ? d.stations : [];
      setStations(list);
      if (id && list.length && !list.some((s) => String(s.id) === id)) { rememberStation(""); setId(""); setVersion((v) => v + 1); }
    }).catch(() => {});
  }, [id]);
  useEffect(refresh, []); // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (next: number | null) => {
    const value = next == null ? "" : String(next);
    rememberStation(value);
    setId(value);
    setVersion((v) => v + 1);
  };
  const station = stations.find((s) => String(s.id) === id) ?? null;
  return <StationContext.Provider value={{ station, stations, choose, refresh, version }}>{children}</StationContext.Provider>;
}

/** Stations grouped by region, regions and stations in name order. */
export function byRegion<T extends { region: string; name: string }>(list: T[]): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const s of list) {
    const key = s.region || "Other";
    groups.set(key, [...(groups.get(key) ?? []), s]);
  }
  return [...groups.entries()].sort(([a], [b]) => (a === "Other" ? 1 : b === "Other" ? -1 : a.localeCompare(b)))
    .map(([r, l]) => [r, [...l].sort((x, y) => x.name.localeCompare(y.name))]);
}
