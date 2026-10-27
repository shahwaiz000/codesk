import { ReactNode, useEffect, useState } from "react";
import { fmtDay, fmtMoney } from "../lib";
import type { DashFigures } from "../types";

/* The day's money drawn as a delivery route: handed over → counted → to deposit → bank.
   The van parks at the stop the money has really reached, so the picture IS the status. */

const STOPS = [12.5, 37.5, 62.5, 87.5]; // stop centres, % of the width
const BRASS = "#e2b55a";

type Tone = "leaf" | "brass" | "short";
const TONE: Record<Tone, { line: string; text: string; chip: string }> = {
  leaf: { line: "#5fbf8e", text: "text-[#7fd3a6]", chip: "bg-[#5fbf8e]/15 text-[#a9e6c4]" },
  brass: { line: BRASS, text: "text-brass-glow", chip: "bg-brass-glow/15 text-brass-glow" },
  short: { line: "#e8715d", text: "text-[#f09a8a]", chip: "bg-[#e8715d]/20 text-[#f6b1a4]" },
};

/** Where the van is (0 = handed over … 3 = bank) and what colour the trip is. */
export function routeState(f: DashFigures): { at: number; tone: Tone; note: string } {
  if (!f.drivers) return { at: 0, tone: "brass", note: "No handovers yet" };
  if (f.deposit_status === "deposited" || f.deposit_status === "over") return { at: 3, tone: "leaf", note: "Banked in full" };
  if (f.deposit_status === "short") return { at: 2.55, tone: "short", note: `${fmtMoney(f.pending)} still missing` };
  if (f.deposit_status === "overdue") return { at: 2, tone: "short", note: "Late for the bank" };
  if (f.deposit_status === "nothing") return { at: 2, tone: "leaf", note: "Nothing to bank" };
  return { at: 2, tone: "brass", note: f.deposit_status === "due_today" ? "Waiting for the bank today" : "Cash on hand" };
}

function Van({ color }: { color: string }) {
  return (
    <svg viewBox="-24 -16 50 30" className="h-[30px] w-[50px]" aria-hidden="true">
      <rect x="-21" y="-11" width="30" height="19" rx="3" fill={color} />
      <path d="M9 -6H17L22 0V8H9Z" fill={color} />
      <path d="M11 -3.5H16L19 0.5H11Z" fill="#0f2e22" opacity="0.75" />
      <path d="M-15 -4H3" stroke="#0f2e22" strokeOpacity="0.35" strokeWidth="2" strokeLinecap="round" />
      <circle cx="-12" cy="9" r="4" fill="#0f2e22" stroke={color} strokeWidth="1.5" />
      <circle cx="14" cy="9" r="4" fill="#0f2e22" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

const ICONS: ReactNode[] = [
  <><rect x="-14" y="-11" width="28" height="23" rx="2" fill="none" strokeWidth="2" /><path d="M-14 -3H14M0 -11V12" strokeWidth="2" /></>,
  <><rect x="-17" y="-12" width="26" height="17" rx="2" fill="none" strokeWidth="2" /><circle cx="-4" cy="-3.5" r="3.5" fill="none" strokeWidth="1.6" /><rect x="-3" y="1" width="20" height="13" rx="2.5" fill="currentColor" stroke="none" /></>,
  <><path d="M-11 -14H11V14L7 11L3 14L-1 11L-5 14L-9 11L-11 14Z" fill="none" strokeWidth="2" strokeLinejoin="round" /><path d="M-6 -6H6M-6 1H6" strokeWidth="2" /></>,
  <><path d="M-16 -6L0 -16L16 -6Z" fill="none" strokeWidth="2" strokeLinejoin="round" /><path d="M-10 -2V9M-3.5 -2V9M3.5 -2V9M10 -2V9M-17 13H17" strokeWidth="2" strokeLinecap="round" /></>,
];

export default function MoneyRoute({ f, activeDrivers }: { f: DashFigures; activeDrivers: number }) {
  const state = routeState(f);
  const tone = TONE[state.tone];
  const [shown, setShown] = useState(0); // the van starts at the first stop and drives to its place
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(state.at));
    return () => cancelAnimationFrame(id);
  }, [state.at]);
  const vanLeft = STOPS[0] + 25 * shown;

  const stops = [
    { label: "Handed over", value: <><span className="num">{f.drivers}</span><span className="text-base font-normal text-ledger-300"> of {activeDrivers} drivers</span></>,
      foot: <>collected <span className="num">{fmtMoney(f.total_collected)}</span></> },
    { label: "Cash counted", value: <span className="num">{fmtMoney(f.cash_received)}</span>,
      foot: f.cash_short ? <span className="text-[#f09a8a]"><span className="num">{fmtMoney(f.cash_short)}</span> short</span> : <>plus <span className="num">{fmtMoney(f.pos_terminal)}</span> on POS</> },
    { label: "To deposit", value: <span className="num">{fmtMoney(f.to_deposit)}</span>,
      foot: <>after <span className="num">{fmtMoney(f.paid_out - f.returned)}</span> paid out</> },
    { label: "In the bank", value: <span className="num">{fmtMoney(f.deposited)}</span>,
      foot: f.pending > 0 ? <span className={tone.text}><span className="num">{fmtMoney(f.pending)}</span> pending</span> : f.deposited ? "nothing pending" : "no slip yet" },
  ];

  return (
    <section aria-label="Cash from driver to bank" className="relative mb-6 overflow-hidden rounded-panel bg-ledger-900 text-white shadow-panel"
      style={{ backgroundImage: "linear-gradient(rgba(159,188,174,.07) 1px, transparent 1px), linear-gradient(90deg, rgba(159,188,174,.07) 1px, transparent 1px)", backgroundSize: "28px 28px" }}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-5">
        <div>
          <h2 className="text-[15px] font-semibold">Cash from driver to bank</h2>
          <p className="text-xs text-ledger-300">{f.due_on ? <>Bank deposit due {fmtDay(f.due_on)}</> : "Where the day’s money is now"}</p>
        </div>
        <span className="flex items-center gap-2">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${tone.chip}`}>{f.deposit_status_text}</span>
          <span className="text-sm text-ledger-300">{state.note}</span>
        </span>
      </div>

      {/* the road */}
      <div className="relative mx-6 mt-4 hidden h-24 sm:block" aria-hidden="true">
        <div className="absolute top-1/2 h-[26px] -translate-y-1/2 rounded-full bg-ledger-800" style={{ left: `${STOPS[0]}%`, right: `${100 - STOPS[3]}%` }} />
        <div className="absolute top-1/2 h-0 -translate-y-1/2 border-t-2 border-dotted border-white/25" style={{ left: `${STOPS[0]}%`, right: `${100 - STOPS[3]}%` }} />
        <div className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full transition-[width] duration-[2400ms] ease-[cubic-bezier(.45,0,.3,1)]"
          style={{ left: `${STOPS[0]}%`, width: `${vanLeft - STOPS[0]}%`, background: tone.line, boxShadow: `0 0 12px ${tone.line}` }} />
        {STOPS.map((x, i) => {
          const reached = i <= state.at;
          const banked = i === 3 && state.tone === "leaf" && reached;
          return (
            <svg key={i} viewBox="-34 -34 68 68" className="absolute top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 transition-opacity duration-700"
              style={{ left: `${x}%`, color: banked ? TONE.leaf.line : reached ? BRASS : "#9fbcae", opacity: reached ? 1 : 0.55 }}>
              <circle r="31" fill="#173d2f" stroke="currentColor" strokeWidth="1.5" strokeDasharray={reached ? undefined : "3 4"} />
              <g stroke="currentColor">{ICONS[i]}</g>
            </svg>
          );
        })}
        <div className={`absolute top-1/2 -translate-x-1/2 transition-[left,transform] duration-[2400ms] ease-[cubic-bezier(.45,0,.3,1)] ${Number.isInteger(shown) ? "-translate-y-[calc(50%+46px)]" : "-translate-y-[calc(50%+2px)]"}`}
          style={{ left: `${vanLeft}%` }}>
          <Van color={state.tone === "short" ? "#e8715d" : BRASS} />
        </div>
      </div>

      {/* the numbers under each stop */}
      <dl className="grid grid-cols-2 gap-y-5 px-6 pb-6 pt-4 sm:grid-cols-4 sm:pt-1">
        {stops.map((s, i) => (
          <div key={s.label} className="px-2 sm:text-center">
            <dt className={`text-sm ${i <= state.at ? "text-ledger-300" : "text-ledger-300/60"}`}>{s.label}</dt>
            <dd className={`mt-1 text-[22px] font-semibold leading-tight ${i === 2 ? "text-brass-glow" : ""}`}>{s.value}</dd>
            <dd className="mt-1 text-xs text-ledger-300">{s.foot}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
