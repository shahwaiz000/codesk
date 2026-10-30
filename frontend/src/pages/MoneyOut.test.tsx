import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { BusinessDayProvider } from "../businessDay";
import Deposits from "./Deposits";
import Expenses from "./Expenses";
import type { Advances, DepositLedger } from "../types";

afterEach(() => vi.restoreAllMocks());

const LEDGER: DepositLedger = {
  today: "2026-10-27", banks: ["Coastal National Bank"],
  totals: { cash_on_hand: 33000, overdue: 0, overdue_days: 0, short: 500, short_days: 1, due_today: 32500, not_due: 0, deposited: 900000, late_days: 1 },
  rows: [
    { date: "2026-10-26", due_on: "2026-10-27", cash_received: 33000, paid_out: 500, returned: 0, to_deposit: 32500, deposited: 0,
      pending: 32500, brought_forward: 500, total_due: 33000, left: 33000, status: "due_today", status_text: "Due today", late: false, days_late: 0, slips: [] },
    { date: "2026-10-11", due_on: "2026-10-12", cash_received: 30000, paid_out: 400, returned: 0, to_deposit: 29600, deposited: 29100,
      pending: 500, brought_forward: 0, total_due: 29600, left: 500, status: "short", status_text: "Deposit short", late: false, days_late: 0,
      slips: [{ id: 7, deposit_date: "2026-10-12", bank: "Gulf Trade Bank", slip_ref: "DS-123456", amount: 29100, note: "", created_by: "demo" }] },
  ],
};

function mock(routes: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method && init.method !== "GET") return new Response("{}", { status: 200 });
    const key = Object.keys(routes).find((k) => url.includes(k));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200 });
  });
}

test("deposits show what is due and short, and a slip can be recorded", async () => {
  const f = mock({ "/deposits": LEDGER });
  render(<Deposits />);
  const short = (await screen.findByText("Deposit short")).closest("tr")!;
  expect(within(short).getByText("500.00")).toBeInTheDocument();
  const due = screen.getByText("Due today", { selector: "span.rounded-full" }).closest("tr")!;
  await userEvent.click(within(due).getByRole("button", { name: "Record deposit" }));
  const dialog = screen.getByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("Deposit slip no."), "ds-999");
  const amount = within(dialog).getByLabelText("Slip amount (SAR)");
  await userEvent.clear(amount);
  await userEvent.type(amount, "32000");
  expect(within(dialog).getByText("500.00")).toBeInTheDocument(); // carried from an earlier short day
  expect(within(dialog).getByText("1,000.00")).toBeInTheDocument(); // left after this slip: 33,000 - 32,000
  await userEvent.click(within(dialog).getByRole("button", { name: "Save deposit" }));
  await waitFor(() => {
    const post = f.mock.calls.find(([, i]) => i?.method === "POST");
    expect(JSON.parse(String(post![1]!.body))).toMatchObject({ business_date: "2026-10-26", bank: "Coastal National Bank", slip_ref: "ds-999", amount: "32000" });
  });
});

test("an advance can be recovered by salary or cash", async () => {
  const advances: Advances = {
    open_total: 800, open_count: 1, drivers: 1,
    rows: [{ id: 5, business_date: "2026-10-23", driver_id: 11, driver_code: "D-111", driver_name: "Omar Al-Ghamdi", category: "advance",
      category_text: "Advance", amount: 800, reference: "", note: "", created_by: "demo", settled_on: null, settlement_method: null, settlement_note: "", days_open: 4 }],
  };
  const f = mock({ "/meta": { latest_business_date: "2026-10-26" }, "/collections/days": [], "/advances": advances,
    "/expenses": { date: "2026-10-26", rows: [], totals: { expenses: 0, advances: 0, total: 0, count: 0, by_category: [] }, categories: [] }, "/drivers": [] });
  render(<BusinessDayProvider><Expenses /></BusinessDayProvider>);
  expect(await screen.findByText("Nothing paid out on this day")).toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: "Recover" }));
  await userEvent.click(screen.getByLabelText(/Cash returned at the desk/));
  await userEvent.click(screen.getByRole("button", { name: "Mark recovered" }));
  await waitFor(() => {
    const post = f.mock.calls.find(([u, i]) => i?.method === "POST" && String(u).includes("/advances/5/settle"));
    expect(JSON.parse(String(post![1]!.body)).method).toBe("cash");
  });
});
