import { useEffect, useState } from "react";

/** Counts up to the value when it changes, so the day's cash "arrives" on screen. Still for reduced motion. */
export function useCountUp(value: number, ms = 900) {
  const [shown, setShown] = useState(value);
  useEffect(() => {
    const still = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still || !value) { setShown(value); return; }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const k = Math.min(1, (now - start) / ms);
      setShown(Math.round(value * (1 - Math.pow(1 - k, 3)) * 100) / 100);
      if (k < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, ms]);
  return shown;
}

function Wheel({ cx, spin }: { cx: number; spin: boolean }) {
  return (
    <g transform={`translate(${cx} 84)`}>
      <circle r="16" fill="#16211c" />
      <circle r="9.5" fill="#dfe8e2" />
      <g stroke="#7c8781" strokeWidth="1.6" strokeLinecap="round">
        <path d="M0-8V8M-8 0H8M-5.7-5.7l11.4 11.4M-5.7 5.7l11.4-11.4" />
        {spin && <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="0.35s" repeatCount="5" />}
      </g>
      <circle r="3" fill="#86590c" />
    </g>
  );
}

/** The CODesk delivery van, drawn facing the bank. */
export function Van({ deposited, late, spin }: { deposited: boolean; late: boolean; spin: boolean }) {
  const bag = late ? { body: "#c9503b", dark: "#922f20", text: "#fff" } : { body: "#e8bd62", dark: "#86590c", text: "#0f2e22" };
  return (
    <g>
      <defs>
        <linearGradient id="van-body" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#34a374" /><stop offset=".55" stopColor="#1d7a55" /><stop offset="1" stopColor="#145c3f" />
        </linearGradient>
        <linearGradient id="van-glass" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#e9f6ef" /><stop offset="1" stopColor="#9fc9b6" />
        </linearGradient>
        <radialGradient id="van-beam" cx="0" cy=".5" r="1">
          <stop offset="0" stopColor="#fff3c4" stopOpacity=".9" /><stop offset="1" stopColor="#fff3c4" stopOpacity="0" />
        </radialGradient>
      </defs>
      {/* shadow and headlight beam */}
      <ellipse cx="98" cy="100" rx="96" ry="5" fill="#16211c" opacity=".16" />
      {!deposited && <ellipse cx="214" cy="62" rx="34" ry="12" fill="url(#van-beam)" />}
      {/* speed lines */}
      {!deposited && <g stroke="#9fbcae" strokeWidth="3" strokeLinecap="round" opacity=".9"><path d="M-14 36h-30M-8 52h-44M-18 68h-22" /></g>}

      {/* roof rack and the cash bag */}
      <path d="M22 6h96" stroke="#0f2e22" strokeWidth="3" strokeLinecap="round" />
      <path d="M30 6v4M110 6v4" stroke="#0f2e22" strokeWidth="2.5" />
      {!deposited && (
        <g transform="translate(46 -40)">
          <path d="M8 16C2 26 0 36 4 42h44c4-6 2-16-4-26z" fill={bag.body} />
          <path d="M14 16h24l-4-7H18z" fill={bag.dark} />
          <path d="M20 9c-2-6 2-9 6-6 4-3 8 0 6 6" fill="none" stroke={bag.dark} strokeWidth="2.5" strokeLinecap="round" />
          <path d="M10 22c3 10 3 14 0 18" stroke="#fff" strokeOpacity=".45" strokeWidth="2.5" fill="none" strokeLinecap="round" />
          <text x="26" y="36" fontSize="11" textAnchor="middle" fill={bag.text} fontWeight="800">SAR</text>
        </g>
      )}

      {/* body */}
      <path d="M8 12q0-6 6-6h112q11 0 18 7l26 30q14 3 18 15v20q0 6-6 6H10q-6 0-6-6V18q0-6 4-6z" fill="url(#van-body)" />
      <path d="M8 12q0-6 6-6h112q11 0 18 7l4 5H8z" fill="#fff" opacity=".12" />
      {/* cab window, door and mirror */}
      <path d="M132 15h8q6 0 10 5l18 22h-36z" fill="url(#van-glass)" />
      <path d="M140 18l-4 20M148 22l-4 18" stroke="#fff" strokeOpacity=".7" strokeWidth="2" strokeLinecap="round" />
      <path d="M128 10v72" stroke="#145c3f" strokeWidth="1.5" />
      <rect x="138" y="50" width="10" height="3" rx="1.5" fill="#0f2e22" opacity=".6" />
      <path d="M166 34h6v8h-4z" fill="#0f2e22" />
      {/* brass stripe, logo, lights, bumper */}
      <rect x="4" y="60" width="184" height="5" fill="#e2b55a" />
      <rect x="4" y="66" width="184" height="1.5" fill="#86590c" opacity=".5" />
      <g transform="translate(30 30)">
        <circle cx="8" cy="8" r="9" fill="#e2b55a" /><text x="8" y="12" fontSize="10" textAnchor="middle" fill="#0f2e22" fontWeight="800">C</text>
        <text x="22" y="13" fontSize="17" fill="#fff" fontWeight="800" letterSpacing="-.3">CODesk</text>
        <text x="23" y="25" fontSize="7" fill="#cfe0d7" letterSpacing="1.4">CASH ON DELIVERY</text>
      </g>
      <rect x="181" y="50" width="7" height="8" rx="2" fill="#fff3c4" />
      <rect x="4" y="22" width="4" height="14" rx="1.5" fill="#d9573f" />
      <rect x="150" y="78" width="40" height="8" rx="3" fill="#0f2e22" />
      <rect x="2" y="78" width="22" height="8" rx="3" fill="#0f2e22" />
      {/* wheel arches and wheels */}
      <path d="M22 84a20 20 0 0 1 40 0z" fill="#0f2e22" />
      <path d="M132 84a20 20 0 0 1 40 0z" fill="#0f2e22" />
      <Wheel cx={42} spin={spin} />
      <Wheel cx={152} spin={spin} />
    </g>
  );
}

