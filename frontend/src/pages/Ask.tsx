import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../components/icons";
import { FormError, PageHeader } from "../components/ui";
import { send, useApi } from "../lib";
import type { AiStatus } from "../types";

interface Turn { q: string; answer?: string; used?: { tool: string; args: Record<string, unknown> }[]; error?: string }

const SUGGESTIONS = [
  "How much cash did we collect on the last business day, and is it deposited?",
  "Which 3 drivers collected the most cash this month?",
  "Which driver had the most POS differences in the last 30 days?",
  "What needs my attention today?",
  "How much did we pay out to drivers this week, and to whom?",
];

const TOOL_TEXT: Record<string, string> = {
  day_summary: "Day figures", period: "Period figures", driver: "Driver's days", top_drivers: "Driver ranking",
  open_items: "Open items", drivers: "Driver list",
};

/** The answer as written by the AI: short paragraphs and "-" or "*" lists, with **bold** kept. */
function Answer({ text }: { text: string }) {
  const bold = (line: string) => line.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : part));
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flush = () => { if (list.length) { blocks.push(<ul key={blocks.length} className="list-disc space-y-1 pl-5">{list.map((l, i) => <li key={i}>{bold(l)}</li>)}</ul>); list = []; } };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const item = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (item) { list.push(item[1]); continue; }
    flush();
    if (line) blocks.push(<p key={blocks.length}>{bold(line.replace(/^#+\s*/, ""))}</p>);
  }
  flush();
  return <div className="space-y-2 text-[15px] leading-relaxed">{blocks}</div>;
}

export default function Ask() {
  const ai = useApi<AiStatus>("/ai").data;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }); }, [turns]);

  async function askIt(q: string, e?: FormEvent) {
    e?.preventDefault();
    const text = q.trim();
    if (text.length < 3 || busy) return;
    setQuestion(""); setBusy(true);
    setTurns((t) => [...t, { q: text }]);
    try {
      const r = await send<{ answer: string; used: Turn["used"] }>("/ask", "POST", { question: text });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, answer: r.answer, used: r.used } : x)));
    } catch (err) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: (err as Error).message } : x)));
    }
    setBusy(false);
  }

  return (
    <>
      <PageHeader title="Ask CODesk" subtitle="Ask about your cash, POS, expenses and deposits in plain English. The AI looks the figures up with CODesk's own calculations and answers from them only." />

      {ai && (
        <div className={`mb-6 flex flex-wrap items-center gap-2 rounded-panel px-4 py-3 text-sm ${ai.ready ? "bg-leaf-soft text-leaf-dark" : "bg-brass-soft text-brass-dark"}`}>
          <Icon name="spark" className="h-4 w-4" />
          {ai.ready
            ? <span>Answering with <b>{ai.engine === "gemini" ? `Google Gemini (${ai.gemini_model}), demo data only` : "the local AI on this computer"}</b>.</span>
            : <span>{ai.reason || "The AI is not set up yet."}</span>}
          <Link to="/settings" className="ml-auto font-medium underline underline-offset-2">AI settings</Link>
        </div>
      )}

      <div className="rounded-panel bg-white shadow-panel">
        <div className="max-h-[60vh] min-h-[16rem] space-y-6 overflow-y-auto p-5 sm:p-6" aria-live="polite">
          {turns.length === 0 && (
            <div>
              <p className="text-sm text-ink-soft">Try one of these:</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => askIt(s)} disabled={busy || ai?.ready === false}
                    className="rounded-full border border-paper-line bg-paper px-3.5 py-1.5 text-left text-sm hover:border-ledger-700 hover:bg-white disabled:opacity-50">{s}</button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className="space-y-3">
              <div className="flex justify-end"><p className="max-w-[85%] rounded-2xl rounded-br-md bg-ledger-900 px-4 py-2.5 text-sm text-white">{t.q}</p></div>
              <div className="flex gap-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brass-soft text-brass-dark"><Icon name="spark" className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md bg-paper px-4 py-3">
                  {t.answer ? <Answer text={t.answer} /> : t.error ? <FormError message={t.error} />
                    : <p className="flex items-center gap-2 text-sm text-ink-soft"><span className="h-4 w-4 animate-spin rounded-full border-2 border-leaf border-t-transparent" />Looking up the figures…</p>}
                  {!!t.used?.length && (
                    <details className="mt-3 text-xs text-ink-faint">
                      <summary className="cursor-pointer">Figures used ({t.used.length})</summary>
                      <ul className="mt-1 space-y-0.5">{t.used.map((u, j) => (
                        <li key={j}>{TOOL_TEXT[u.tool] ?? u.tool}{Object.keys(u.args).length ? `: ${Object.entries(u.args).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}</li>
                      ))}</ul>
                    </details>
                  )}
                </div>
              </div>
            </div>
          ))}
          <div ref={end} />
        </div>
        <form onSubmit={(e) => askIt(question, e)} className="flex gap-2 border-t border-paper-line p-4">
          <input className="field !mt-0 min-w-0 flex-1" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
            placeholder="Ask a question about your desk…" aria-label="Your question" disabled={ai?.ready === false} />
          <button disabled={busy || question.trim().length < 3 || ai?.ready === false} className="btn-primary"><Icon name="spark" className="h-4 w-4" />Ask</button>
        </form>
      </div>
    </>
  );
}
