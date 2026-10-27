import { ReactNode, createContext, useContext, useEffect, useState } from "react";
import { api } from "./lib";
import type { Meta } from "./types";

/** Local calendar date as YYYY-MM-DD (not UTC, so late evening in Riyadh is still today). */
export function todayIso(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

/** Move a YYYY-MM-DD date by whole days, skipping Fridays (the weekly day off). */
export function shiftWorkingDay(iso: string, step: 1 | -1): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  do { dt.setUTCDate(dt.getUTCDate() + step); } while (dt.getUTCDay() === 5);
  return dt.toISOString().slice(0, 10);
}

interface DayValue { day: string; setDay: (d: string) => void; latest: string | null; today: string; refreshMeta: () => void }
const DayContext = createContext<DayValue>({ day: todayIso(), setDay: () => {}, latest: null, today: todayIso(), refreshMeta: () => {} });
export const useBusinessDay = () => useContext(DayContext);

/** The business day every daily page works on. It starts on the latest day that has handovers,
 *  and stays the same as you move between pages. */
export function BusinessDayProvider({ children }: { children: ReactNode }) {
  const today = todayIso();
  const [day, setDay] = useState<string | null>(null);
  const [latest, setLatest] = useState<string | null>(null);

  const refreshMeta = () => {
    api<Meta>("/meta").then((m) => {
      setLatest(m.latest_business_date);
      setDay((d) => d ?? m.latest_business_date ?? today);
    }).catch(() => setDay((d) => d ?? today));
  };
  useEffect(refreshMeta, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <DayContext.Provider value={{ day: day ?? today, setDay, latest, today, refreshMeta }}>
      {children}
    </DayContext.Provider>
  );
}
