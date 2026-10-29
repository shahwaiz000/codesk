import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { BusinessDayProvider, shiftWorkingDay } from "../businessDay";
import HandoverDialog from "../components/HandoverDialog";
import Collections from "./Collections";
import type { CollectionDay, Handover } from "../types";

const row = (over: Partial<Handover>): Handover => ({
  id: 1, business_date: "2026-10-25", driver_id: 1, driver_code: "D-101", driver_name: "Faisal Al-Harbi", hub: "North Hub",
  orders: 20, expected_cash: 1000, cash_received: 1000, difference: 0, status: "ok", pos_amount: 500, pos_terminal: "60311101", total: 1500,
  note: "", created_by: "demo", ...over,
});
const DAY: CollectionDay = {
  date: "2026-10-25",
  rows: [row({}), row({ id: 2, driver_id: 3, driver_code: "D-103", driver_name: "Yousef Al-Amri", cash_received: 950, difference: -50, status: "short", total: 1450 })],
  totals: { expected_cash: 2000, cash_received: 1950, difference: -50, short: 50, over: 0, short_count: 1, over_count: 0, pos_amount: 1000, total: 2950, orders: 40, drivers: 2 },
  missing: [{ id: 2, code: "D-102", name: "Imran Qureshi", hub: "North Hub" }],
};

function mockApi(cashMode = "count") {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.includes("/settings") ? { cash_mode: cashMode }
      : url.includes("/meta") ? { latest_business_date: "2026-10-25", currency: "SAR" }
      : url.includes("/collections/days") ? [{ date: "2026-10-25", drivers: 2, cash_received: 1950, pos_amount: 1000, difference: -50, short: 50 }]
      : url.includes("/collections") ? DAY
      : url.includes("/drivers") ? [{ id: 1, code: "D-101", name: "Faisal Al-Harbi", active: true }, { id: 2, code: "D-102", name: "Imran Qureshi", active: true }]
      : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
}

afterEach(() => vi.restoreAllMocks());

test("working days skip Friday", () => {
  expect(shiftWorkingDay("2026-10-22", 1)).toBe("2026-10-24"); // Thursday -> Saturday
  expect(shiftWorkingDay("2026-10-24", -1)).toBe("2026-10-22");
});

test("the day shows each handover, the shortage and who still has to hand over", async () => {
  mockApi();
  render(<BusinessDayProvider><Collections /></BusinessDayProvider>);
  const short = (await screen.findByText("Yousef Al-Amri")).closest("tr")!;
  expect(within(short).getByText("Short")).toBeInTheDocument();
  expect(within(short).getByText("-50.00")).toBeInTheDocument();
  expect(screen.getByText("1 driver short")).toBeInTheDocument();
  expect(screen.getByText("Not handed over yet")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /D-102\s*Imran Qureshi/ })).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Only differences"));
  expect(screen.queryByText("Faisal Al-Harbi", { selector: "td span" })).not.toBeInTheDocument();
});

test("the handover form shows the cash difference while typing", async () => {
  const saved = vi.fn();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
  render(<HandoverDialog day="2026-10-25" handover={null} drivers={[{ id: 2, code: "D-102", name: "Imran Qureshi" }]}
    presetDriver={2} onClose={() => {}} onSaved={saved} />);
  await userEvent.type(screen.getByLabelText("Expected (system)"), "1,200");
  await userEvent.type(screen.getByLabelText("Counted at the desk"), "1180");
  expect(screen.getByText("Driver is short")).toBeInTheDocument();
  expect(screen.getByText("-20.00")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Save handover" }));
  const [, init] = vi.mocked(fetch).mock.calls[0];
  expect(JSON.parse(String(init!.body))).toMatchObject({ driver_id: 2, expected_cash: "1,200", cash_received: "1180", pos_amount: "0" });
  expect(saved).toHaveBeenCalled();
});

test("a desk that closes orders only when paid sees cash per driver without counting", async () => {
  mockApi("paid");
  render(<BusinessDayProvider><Collections /></BusinessDayProvider>);
  const hero = await screen.findByRole("region", { name: "Cash collected" });
  expect(within(hero).getByText("1,950.00")).toBeInTheDocument(); // the day's cash, shown large
  expect(screen.queryByText("Cash counted")).not.toBeInTheDocument();
  expect(screen.queryByText("Short")).not.toBeInTheDocument();
  expect(screen.queryByText("Not handed over yet")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Add by hand/ })).toBeInTheDocument();
});
