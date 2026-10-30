import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { BusinessDayProvider } from "../businessDay";
import PosCheck from "./PosCheck";
import type { PosDay } from "../types";

const DAY: PosDay = {
  date: "2026-10-25", orders_imported: true,
  rows: [
    { driver_id: 1, driver_code: "D-101", driver_name: "Faisal Al-Harbi", terminal: null, system_total: 900, order_count: 4,
      terminal_total: null, difference: 0, status: "agrees", status_text: "Agrees", review: null, open: false },
    { driver_id: 8, driver_code: "D-108", driver_name: "Naveed Iqbal", terminal: null, system_total: 1500, order_count: 3,
      terminal_total: null, difference: 0, status: "agrees", status_text: "Agrees", review: null, open: false },
  ],
  totals: { system_total: 2400, terminal_total: 0, difference: -20, order_count: 7, drivers: 2, agrees: 2, differences: 0,
    no_terminal: 0, awaiting: 0, open: 0, explained: 0, short: 0, over: 0, sheet: true, machines: 2, machines_total: 2380 },
  machines: [
    { id: 1, terminal: "64812175", amount: 1000, driver_id: null, driver_code: null, driver_name: null, paired_by: null, suggestions: [] },
    { id: 2, terminal: "64813998", amount: 1380, driver_id: null, driver_code: null, driver_name: null, paired_by: null, suggestions: [] },
  ],
};
const ORDERS = [{ order_no: "ORD1", amount: 700 }, { order_no: "ORD2", amount: 800 }];

afterEach(() => vi.restoreAllMocks());

test("the card machine sheet is compared with the system's card payments as two totals", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.includes("/meta") ? { latest_business_date: "2026-10-25" }
      : url.includes("/collections/days") ? []
      : url.includes("/pos/orders") ? ORDERS
      : url.includes("/pos") ? DAY : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  render(<BusinessDayProvider><PosCheck /></BusinessDayProvider>);
  expect(await screen.findByText("Card payments in the system")).toBeInTheDocument();
  expect(screen.getByText("The sheet is below the system by 20.00")).toBeInTheDocument();
  expect(screen.getByText("Total, 2 machines")).toBeInTheDocument();
  expect(screen.queryByText(/match with a driver/)).not.toBeInTheDocument();  // no machine matching: that is operations' work
  await userEvent.click(screen.getByText("Naveed Iqbal"));
  expect(await screen.findByText("ORD2")).toBeInTheDocument();
  const total = screen.getAllByText("Total")[0].closest("tr")!;
  expect(within(total).getByText("2,400.00")).toBeInTheDocument();
});
