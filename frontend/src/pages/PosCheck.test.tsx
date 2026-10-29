import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { BusinessDayProvider } from "../businessDay";
import PosCheck from "./PosCheck";
import type { PosDay } from "../types";

const DAY: PosDay = {
  date: "2026-10-25", orders_imported: true,
  rows: [
    { driver_id: 1, driver_code: "D-101", driver_name: "Faisal Al-Harbi", terminal: "60311101", system_total: 900, order_count: 4,
      terminal_total: 900, difference: 0, status: "agrees", status_text: "Agrees", review: null, open: false },
    { driver_id: 8, driver_code: "D-108", driver_name: "Naveed Iqbal", terminal: "60311108", system_total: 1500, order_count: 3,
      terminal_total: 1180, difference: -320, status: "terminal_short", status_text: "Terminal short", review: null, open: true },
  ],
  totals: { system_total: 2400, terminal_total: 2080, difference: -320, order_count: 7, drivers: 2, agrees: 1, differences: 1,
    no_terminal: 0, awaiting: 0, open: 1, explained: 0, short: 320, over: 0 },
};
const ORDERS = [{ order_no: "ORD1", amount: 700 }, { order_no: "ORD2", amount: 480 }, { order_no: "ORD3", amount: 320 }];

afterEach(() => vi.restoreAllMocks());

test("a terminal shortage can be opened, traced to an order and explained", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "PUT") return new Response(JSON.stringify(DAY.rows[1]), { status: 200 });
    const body = url.includes("/meta") ? { latest_business_date: "2026-10-25" }
      : url.includes("/collections/days") ? []
      : url.includes("/pos/orders") ? ORDERS
      : url.includes("/pos") ? DAY : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  render(<BusinessDayProvider><PosCheck /></BusinessDayProvider>);
  const row = (await screen.findByText("Naveed Iqbal")).closest("tr")!;
  expect(within(row).getByText("Terminal short")).toBeInTheDocument();
  expect(within(row).getByText("-320.00")).toBeInTheDocument();

  await userEvent.click(row);
  expect(await screen.findByText(/Order ORD3 is exactly 320.00/)).toBeInTheDocument();
  expect(screen.getByText("matches the difference")).toBeInTheDocument();

  const explain = screen.getByRole("button", { name: "Mark explained" });
  expect(explain).toBeDisabled(); // a reason is required
  await userEvent.type(screen.getByLabelText("Reason or note"), "ORD3 was paid in cash");
  await userEvent.click(explain);
  await waitFor(() => {
    const put = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT");
    expect(JSON.parse(String(put![1]!.body))).toEqual({ business_date: "2026-10-25", driver_id: 8, status: "explained", note: "ORD3 was paid in cash" });
  });
});

test("a POS machine without a driver is matched with one click", async () => {
  const day: PosDay = {
    ...DAY,
    totals: { ...DAY.totals, sheet: true, machines: 2, machines_total: 2400.2, unpaired: 1, unpaired_total: 1500.2 },
    machines: [
      { id: 7, terminal: "64800002", amount: 1500.2, driver_id: null, driver_code: null, driver_name: null, paired_by: null,
        suggestions: [{ driver_id: 8, driver_code: "D-108", driver_name: "Naveed Iqbal", system_total: 1500, difference: 0.2 }] },
      { id: 6, terminal: "64800001", amount: 900, driver_id: 1, driver_code: "D-101", driver_name: "Faisal Al-Harbi", paired_by: "amount", suggestions: [] },
    ],
  };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "PUT") return new Response("{}", { status: 200 });
    const body = url.includes("/meta") ? { latest_business_date: "2026-10-25" } : url.includes("/collections/days") ? [] : url.includes("/pos") ? day : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  render(<BusinessDayProvider><PosCheck /></BusinessDayProvider>);
  expect(await screen.findByText("1 POS machine to match with a driver")).toBeInTheDocument();
  expect(screen.getByText("1 of 2 machines were matched automatically.", { exact: false })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /D-108\s*Naveed Iqbal/ }));
  await waitFor(() => {
    const put = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT");
    expect(String(put![0])).toContain("/pos/machines/7");
    expect(JSON.parse(String(put![1]!.body))).toEqual({ driver_id: 8 });
  });
});
