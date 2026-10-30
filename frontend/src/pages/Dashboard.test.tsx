import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { BusinessDayProvider } from "../businessDay";
import Dashboard from "./Dashboard";
import Reports from "./Reports";
import type { Dashboard as Dash, DashFigures } from "../types";

const F: DashFigures = {
  cash_received: 40966.5, expected_cash: 41016.5, cash_short: 50, cash_over: 0, short_count: 1, over_count: 0,
  pos_terminal: 23576, pos_system: 23726, pos_difference: -150, pos_open: 1, pos_differences: 1,
  total_collected: 64542.5, orders: 288, drivers: 11, expenses: 245, advances: 0, paid_out: 245, returned: 0,
  to_deposit: 40721.5, deposited: 40000, pending: 721.5, deposit_status: "short", deposit_status_text: "Deposit short", due_on: "2026-10-26",
};
const DASH: Dash = {
  date: "2026-10-25", previous_date: "2026-10-24", figures: F, previous: { ...F, total_collected: 60000 }, active_drivers: 11, cash_on_hand: 37307.5,
  attention: [{ driver_code: "D-103", driver_name: "Yousef Al-Amri", issues: [{ kind: "cash_short", amount: -50, page: "/collections" }] }],
  alerts: [{ kind: "deposit_short", date: "2026-10-12", amount: 500, page: "/deposits", text: "Bank deposit short" }],
  alert_count: 1, alert_kinds: { deposit_short: 1 },
  trend: [{ date: "2026-10-25", cash: 40966.5, pos: 23576, deposit_status: "short" }],
};

afterEach(() => vi.restoreAllMocks());

function mock() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.includes("/meta") ? { latest_business_date: "2026-10-25" } : url.includes("/dashboard") ? DASH
      : url.includes("/reports/preview") ? { start: "2026-10-25", end: "2026-10-25", days: 0, totals: {} } : [];
    return new Response(JSON.stringify(body), { status: 200 });
  });
}

test("the overview shows the day's money in four boxes, and no driver differences", async () => {
  mock();
  render(<MemoryRouter><BusinessDayProvider><Dashboard /></BusinessDayProvider></MemoryRouter>);
  expect(await screen.findByText("Cash collected")).toBeInTheDocument();
  expect(screen.getByText("40,000.00")).toBeInTheDocument(); // in the bank
  expect(screen.getByText("37,307.50")).toBeInTheDocument(); // not yet in the bank, all days
  expect(screen.getByText("Includes late or short deposits")).toBeInTheDocument();
  expect(screen.queryByText("Yousef Al-Amri")).not.toBeInTheDocument(); // driver cash differences are not the supervisor's view
  expect(screen.queryByRole("region", { name: "Cash from driver to bank" })).not.toBeInTheDocument(); // the overview stays simple
});

test("reports offer both downloads for the chosen day", async () => {
  mock();
  render(<MemoryRouter><BusinessDayProvider><Reports /></BusinessDayProvider></MemoryRouter>);
  const links = await screen.findAllByRole("link", { name: /Excel workbook/ });
  expect(links[0].getAttribute("href")).toMatch(/\/api\/reports\/day\?date=\d{4}-\d{2}-\d{2}&format=xlsx/);
  expect(screen.getAllByRole("link", { name: /Printable PDF/ })[1].getAttribute("href")).toMatch(/\/api\/reports\/range\?start=.*&format=pdf/);
});

test("the van parks where the day's money really is", async () => {
  const { routeState } = await import("../components/MoneyRoute");
  expect(routeState({ ...F, drivers: 0 }).at).toBe(0);
  expect(routeState({ ...F, deposit_status: "due_today", deposited: 0 }).at).toBe(2);
  expect(routeState(F)).toMatchObject({ tone: "short" }); // a short deposit is stuck before the bank
  expect(routeState({ ...F, deposit_status: "deposited", pending: 0 })).toMatchObject({ at: 3, tone: "leaf" });
  expect(routeState({ ...F, deposit_status: "overdue", deposited: 0 })).toMatchObject({ at: 2, tone: "short" });
});
