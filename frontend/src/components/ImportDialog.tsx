import { FormEvent, ReactNode, useState } from "react";
import { fmtDay, upload } from "../lib";
import { Icon } from "./icons";
import { Badge, FormError, Modal, Money } from "./ui";

export type ImportStatus = "new" | "update" | "same" | "skipped" | "error";
export interface PreviewRow { line: number; status: ImportStatus; problems: string[]; date: string | null; [key: string]: unknown }
export interface ImportResult { file: string; rows: PreviewRow[]; counts: Partial<Record<ImportStatus, number>>; committed: boolean; saved: number; dates: string[] }
export interface PreviewColumn { label: string; right?: boolean; cell: (r: PreviewRow) => ReactNode }

const LABEL: Record<ImportStatus, { text: string; count: (n: number) => string; tone: "leaf" | "brass" | "muted" | "short" }> = {
  new: { text: "New", count: (n) => `${n} new`, tone: "leaf" },
  update: { text: "Will update", count: (n) => `${n} will update`, tone: "brass" },
  same: { text: "Already saved", count: (n) => `${n} already saved`, tone: "muted" },
  skipped: { text: "Skipped", count: (n) => `${n} skipped`, tone: "muted" },
  error: { text: "Problem", count: (n) => `${n} ${n === 1 ? "problem" : "problems"}`, tone: "short" },
};

export const money = (key: string): ((r: PreviewRow) => ReactNode) => (r) =>
  r[key] == null ? <span className="text-ink-faint">-</span> : <Money value={r[key] as number} />;

/** Two steps: check the file (nothing is saved), then save the good rows. */
export default function ImportDialog({ title, intro, endpoint, templateUrl, columns, noun, day, onClose, onSaved }: {
  title: string; intro: ReactNode; endpoint: string; templateUrl: string; columns: PreviewColumn[];
  noun: [string, string]; day: string; onClose: () => void; onSaved: (dates: string[]) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [date, setDate] = useState(day);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [onlyProblems, setOnlyProblems] = useState(false);

  async function run(commit: boolean) {
    if (!file) return;
    setBusy(true); setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("business_date", date);
    form.append("commit", String(commit));
    try {
      const res = await upload<ImportResult>(endpoint, form);
      if (commit) onSaved(res.dates);
      else { setPreview(res); setOnlyProblems((res.counts.error ?? 0) > 0); }
    } catch (err) { setError((err as Error).message); }
    setBusy(false);
  }

  const check = (e: FormEvent) => { e.preventDefault(); run(false); };
  const n = (k: ImportStatus) => preview?.counts[k] ?? 0;
  const toSave = n("new") + n("update");
  const shown = preview ? preview.rows.filter((r) => !onlyProblems || r.status === "error") : [];

  return (
    <Modal title={title} onClose={onClose} width={preview ? "max-w-4xl" : "max-w-lg"}>
      {!preview ? (
        <form onSubmit={check} className="space-y-4">
          <div className="text-sm text-ink-soft">{intro} The file is checked first and nothing is saved until you confirm.</div>
          <label className="block rounded-lg border border-dashed border-paper-line bg-paper/60 px-4 py-6 text-center text-sm hover:border-ledger-300">
            <Icon name="upload" className="mx-auto mb-2 h-6 w-6 text-ink-faint" />
            <span className="font-medium text-ink">{file ? file.name : "Choose a .csv or .xlsx file"}</span>
            <input type="file" accept=".csv,.xlsx" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <label className="block text-sm font-medium">Business date for rows without a date
            <input type="date" className="field" value={date} onChange={(e) => setDate(e.target.value)} /></label>
          <a href={templateUrl} className="inline-flex items-center gap-1.5 text-sm font-medium text-leaf-dark hover:underline">
            <Icon name="download" className="h-4 w-4" />Download the template</a>
          <FormError message={error} />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-quiet">Cancel</button>
            <button disabled={!file || busy} className="btn-primary">{busy ? "Checking..." : "Check file"}</button>
          </div>
        </form>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="mr-1 font-medium">{preview.file}</span>
            {(Object.keys(LABEL) as ImportStatus[]).filter((k) => n(k)).map((k) =>
              <Badge key={k} tone={LABEL[k].tone}>{LABEL[k].count(n(k))}</Badge>)}
            {n("error") > 0 && (
              <label className="ml-auto flex items-center gap-2 text-ink-soft">
                <input type="checkbox" className="h-4 w-4 accent-ledger-700" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
                Only rows with problems</label>
            )}
          </div>
          {n("error") > 0 && (
            <p className="rounded-lg bg-short-soft px-3 py-2 text-sm text-short-dark">
              {n("error")} {n("error") === 1 ? "row has a problem and will not be saved" : "rows have problems and will not be saved"}. Fix them in the file and import it again, or save the good rows now.
            </p>
          )}
          <div className="relative max-h-[50vh] overflow-auto rounded-lg border border-paper-line">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="sticky top-0 bg-paper text-left text-xs text-ink-faint">
                <tr>
                  <th className="px-3 py-2 font-medium">Row</th>
                  {columns.map((c) => <th key={c.label} className={`px-3 py-2 font-medium ${c.right ? "text-right" : ""}`}>{c.label}</th>)}
                  <th className="px-3 py-2 font-medium">Date</th>
                  <th className="px-3 py-2 font-medium">Result</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.line} className="border-t border-paper-line align-top">
                    <td className="num px-3 py-2 text-ink-faint">{r.line}</td>
                    {columns.map((c) => <td key={c.label} className={`px-3 py-2 ${c.right ? "text-right" : ""}`}>{c.cell(r)}</td>)}
                    <td className="whitespace-nowrap px-3 py-2 text-ink-soft">{r.date ? fmtDay(r.date) : "-"}</td>
                    <td className="px-3 py-2">
                      <Badge tone={LABEL[r.status].tone}>{LABEL[r.status].text}</Badge>
                      {r.problems.length > 0 && <p className={`mt-1 max-w-[16rem] text-xs ${r.status === "error" ? "text-short-dark" : "text-ink-faint"}`}>{r.problems.join("; ")}</p>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <FormError message={error} />
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button onClick={() => { setPreview(null); setFile(null); }} className="btn-quiet mr-auto">Choose another file</button>
            <button onClick={onClose} className="btn-quiet">Cancel</button>
            <button onClick={() => run(true)} disabled={busy || toSave === 0} className="btn-primary">
              {toSave === 0 ? "Nothing to save" : `Save ${toSave} ${toSave === 1 ? noun[0] : noun[1]}`}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
