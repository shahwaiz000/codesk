import { useEffect, useState } from "react";

/* The welcome illustration: the day's money as a delivery route.
   A parcel is delivered, the van drives back, cash and POS are checked at the desk,
   and the cash reaches the bank. The van drives once when the page opens. */

const ROUTE = "M70 120 C 200 120, 170 250, 280 250 C 390 250, 370 390, 480 390";
const BRASS = "#e2b55a";
const MINT = "#9fbcae";
const PAPER = "#f3f5f2";

function Stop({ x, y, children }: { x: number; y: number; children: React.ReactNode }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <circle r="34" fill="#173d2f" stroke={BRASS} strokeWidth="1.5" />
      {children}
    </g>
  );
}

function Label({ x, y, title, sub, anchor = "start", delay }: { x: number; y: number; title: string; sub: string; anchor?: "start" | "middle"; delay: number }) {
  return (
    <g className="route-fade" style={{ animationDelay: `${delay}s` }}>
      <text x={x} y={y} textAnchor={anchor} fill={PAPER} fontSize="16" fontWeight="600">{title}</text>
      <text x={x} y={y + 20} textAnchor={anchor} fill={MINT} fontSize="13">{sub}</text>
    </g>
  );
}

export default function RouteArt({ className = "" }: { className?: string }) {
  const [still, setStill] = useState(false);
  useEffect(() => {
    setStill(typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }, []);

  return (
    <svg viewBox="0 0 560 490" className={className} role="img"
      aria-label="A parcel is delivered, the van brings the cash back, cash and POS are checked at the desk, and the cash is deposited at the bank">
      <defs>
        <pattern id="map-grid" width="28" height="28" patternUnits="userSpaceOnUse">
          <path d="M28 0H0V28" fill="none" stroke={MINT} strokeOpacity="0.09" strokeWidth="1" />
        </pattern>
        <radialGradient id="map-fade" cx="50%" cy="50%" r="55%">
          <stop offset="55%" stopColor="#fff" />
          <stop offset="100%" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <mask id="map-mask"><rect width="560" height="490" fill="url(#map-fade)" /></mask>
      </defs>
      <rect width="560" height="490" fill="url(#map-grid)" mask="url(#map-mask)" />

      {/* the road: a wide soft band, then the dashed lane marking */}
      <path d={ROUTE} fill="none" stroke="#173d2f" strokeWidth="26" strokeLinecap="round" />
      <path d={ROUTE} fill="none" stroke={BRASS} strokeOpacity="0.85" strokeWidth="2" strokeDasharray="2 9" strokeLinecap="round" />

      {/* 1. parcel delivered, customer pays */}
      <Stop x={70} y={120}>
        <rect x="-14" y="-11" width="28" height="23" rx="2" fill="none" stroke={BRASS} strokeWidth="2" />
        <path d="M-14 -3H14M0 -11V12" stroke={BRASS} strokeWidth="2" />
      </Stop>
      <Label x={36} y={62} title="Delivered" sub="customer pays cash or card" delay={0.2} />

      {/* 2. at the desk: cash counted, POS checked */}
      <Stop x={280} y={250}>
        <rect x="-17" y="-12" width="26" height="17" rx="2" fill="none" stroke={MINT} strokeWidth="2" />
        <circle cx="-4" cy="-3.5" r="3.5" fill="none" stroke={MINT} strokeWidth="1.6" />
        <rect x="-3" y="1" width="20" height="13" rx="2.5" fill={BRASS} />
        <path d="M-3 5.5H17" stroke="#0f2e22" strokeWidth="2" />
      </Stop>
      <Label x={322} y={214} title="Collected" sub="cash counted, POS checked" delay={1.6} />

      {/* 3. the bank */}
      <Stop x={480} y={390}>
        <path d="M-16 -6L0 -16L16 -6Z" fill="none" stroke={BRASS} strokeWidth="2" strokeLinejoin="round" />
        <path d="M-10 -2V9M-3.5 -2V9M3.5 -2V9M10 -2V9M-17 13H17" stroke={BRASS} strokeWidth="2" strokeLinecap="round" />
      </Stop>
      <Label x={480} y={452} title="Deposited" sub="next working day" anchor="middle" delay={3.4} />

      {/* the day's ledger, filling in as the van passes each stop */}
      <g transform="translate(24 300)">
        <rect width="232" height="138" rx="12" fill="#173d2f" stroke={MINT} strokeOpacity="0.25" />
        <text x="18" y="30" fill={MINT} fontSize="13">Today</text>
        {[
          { y: 60, label: "Cash received", value: "36,873.50", delay: 1.7 },
          { y: 88, label: "POS checked", value: "21,506.00", delay: 2.2 },
          { y: 116, label: "To the bank", value: "36,807.50", delay: 3.5, strong: true },
        ].map((r) => (
          <g key={r.label} className="route-fade" style={{ animationDelay: `${r.delay}s` }}>
            <text x="18" y={r.y} fill={r.strong ? PAPER : MINT} fontSize="14" fontWeight={r.strong ? 600 : 400}>{r.label}</text>
            <text x="214" y={r.y} textAnchor="end" fill={r.strong ? BRASS : PAPER} fontSize="14" fontWeight="600"
              style={{ fontVariantNumeric: "tabular-nums" }}>{r.value}</text>
          </g>
        ))}
      </g>

      {/* the van; it drives the route once and parks before the bank */}
      <g transform={still ? "translate(416 390)" : undefined}>
        {!still && <animateMotion dur="4s" begin="0s" fill="freeze" rotate="auto" path={ROUTE}
          keyPoints="0;0;0.9" keyTimes="0;0.1;1" calcMode="spline" keySplines="0 0 1 1;0.45 0 0.3 1" />}
        <g transform={still ? "scale(1.35)" : "translate(0 -1) scale(1.35)"}>
          <rect x="-21" y="-11" width="30" height="19" rx="3" fill={BRASS} />
          <path d="M9 -6H17L22 0V8H9Z" fill={BRASS} />
          <path d="M11 -3.5H16L19 0.5H11Z" fill="#0f2e22" opacity="0.75" />
          <circle cx="-12" cy="9" r="4" fill="#0f2e22" stroke={BRASS} strokeWidth="1.5" />
          <circle cx="14" cy="9" r="4" fill="#0f2e22" stroke={BRASS} strokeWidth="1.5" />
          <path d="M-15 -4H3" stroke="#0f2e22" strokeOpacity="0.35" strokeWidth="2" strokeLinecap="round" />
        </g>
      </g>
    </svg>
  );
}
