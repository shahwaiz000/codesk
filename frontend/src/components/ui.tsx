import { ReactNode, useEffect, useRef } from "react";
import { fmtMoney } from "../lib";
import { Icon } from "./icons";

export const Panel = ({ title, action, children, className = "", flush = false }:
  { title?: string; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) => (
  <section className={`rounded-panel bg-white shadow-panel ${flush ? "" : "p-5"} ${className}`}>
    {(title || action) && (
      <div className={`flex items-center justify-between gap-3 ${flush ? "border-b border-paper-line px-5 py-3.5" : "mb-4"}`}>
        {title && <h2 className="text-[15px] font-semibold text-ink">{title}</h2>}
        {action}
      </div>
    )}
    {children}
  </section>
);

export const PageHeader = ({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) => (
  <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
    <div className="max-w-2xl">
      <h1 className="text-[28px] font-semibold leading-tight text-ink">{title}</h1>
      {subtitle && <p className="mt-1.5 text-sm text-ink-soft">{subtitle}</p>}
    </div>
    {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
  </div>
);

/** An amount with a quiet currency label, right-aligned in tables. */
export function Money({ value, tone, className = "" }: { value: number | null | undefined; tone?: "short" | "brass" | "leaf" | "muted"; className?: string }) {
  const color = tone ? { short: "text-short", brass: "text-brass-dark", leaf: "text-leaf-dark", muted: "text-ink-faint" }[tone] : "text-ink";
  return <span className={`num whitespace-nowrap ${color} ${className}`}>{fmtMoney(value)}</span>;
}

const BADGE = {
  leaf: "bg-leaf-soft text-leaf-dark", brass: "bg-brass-soft text-brass-dark",
  short: "bg-short-soft text-short-dark", muted: "bg-paper-deep text-ink-soft",
};
export const Badge = ({ tone, children }: { tone: keyof typeof BADGE; children: ReactNode }) => (
  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${BADGE[tone]}`}>{children}</span>
);

export const Loading = () => (
  <p role="status" className="flex items-center justify-center gap-3 py-16 text-sm text-ink-soft">
    <span className="h-4 w-4 animate-spin rounded-full border-2 border-paper-line border-t-leaf" aria-hidden="true" />
    Loading...
  </p>
);

export const ErrorBox = ({ message, retry }: { message: string; retry?: () => void }) => (
  <div role="alert" className="rounded-panel border border-short/25 bg-short-soft p-5 text-sm text-short-dark">
    <p className="font-medium">This could not be loaded</p>
    <p className="mt-1">{message}</p>
    {retry && <button onClick={retry} className="btn-danger mt-3">Try again</button>}
  </div>
);

export const Empty = ({ title, hint, children }: { title: string; hint: string; children?: ReactNode }) => (
  <div className="px-6 py-14 text-center">
    <p className="font-medium text-ink">{title}</p>
    <p className="mx-auto mt-1 max-w-sm text-sm text-ink-soft">{hint}</p>
    {children && <div className="mt-4">{children}</div>}
  </div>
);

/** A centred dialog. Escape or the backdrop closes it; focus moves into it when it opens. */
export function Modal({ title, onClose, children, width = "max-w-md" }: { title: string; onClose: () => void; children: ReactNode; width?: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); before?.focus(); };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <button aria-label="Close" tabIndex={-1} onClick={onClose} className="absolute inset-0 cursor-default bg-ledger-950/45" />
      <div ref={box} role="dialog" aria-modal="true" aria-label={title} className={`relative w-full ${width} animate-rise rounded-panel bg-white p-6 shadow-pop`}>
        <div className="mb-5 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          <button onClick={onClose} aria-label="Close dialog" className="-mr-2 -mt-1 rounded-lg p-1.5 text-ink-faint hover:bg-paper-deep hover:text-ink">
            <Icon name="close" className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export const FormError = ({ message }: { message: string | null }) =>
  message ? <p role="alert" className="rounded-lg bg-short-soft px-3 py-2 text-sm text-short-dark">{message}</p> : null;
