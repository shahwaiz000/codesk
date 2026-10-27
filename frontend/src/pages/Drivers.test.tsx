import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import Drivers from "./Drivers";
import type { Driver } from "../types";

const base: Omit<Driver, "id" | "code" | "name" | "hub" | "active"> = {
  phone: "", pos_terminal: "", last_collection: "2026-10-26", days_collected: 30, cash_shortage: 0, open_advances: 0, open_advance_count: 0,
};
const DRIVERS: Driver[] = [
  { ...base, id: 1, code: "D-101", name: "Faisal Al-Harbi", hub: "North Hub", active: true, cash_shortage: 20 },
  { ...base, id: 2, code: "D-111", name: "Omar Al-Ghamdi", hub: "South Hub", active: true, open_advances: 800, open_advance_count: 1 },
  { ...base, id: 3, code: "D-112", name: "Kamran Malik", hub: "South Hub", active: false },
];

function mockApi(onPost?: (body: unknown) => void) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    if (init?.method === "POST") {
      onPost?.(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ ...DRIVERS[0], id: 9 }), { status: 201 });
    }
    return new Response(JSON.stringify(DRIVERS), { status: 200 });
  });
}

afterEach(() => vi.restoreAllMocks());

test("shows active drivers with totals and hides inactive ones until asked", async () => {
  mockApi();
  render(<Drivers />);
  expect(await screen.findByText("Faisal Al-Harbi")).toBeInTheDocument();
  expect(screen.getByText("800.00", { selector: "dd span" })).toBeInTheDocument();
  expect(screen.queryByText("Kamran Malik")).not.toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Show inactive"));
  expect(screen.getByText("Kamran Malik")).toBeInTheDocument();
});

test("search narrows the list", async () => {
  mockApi();
  render(<Drivers />);
  await screen.findByText("Faisal Al-Harbi");
  await userEvent.type(screen.getByPlaceholderText(/Search by ID/), "d-111");
  expect(screen.queryByText("Faisal Al-Harbi")).not.toBeInTheDocument();
  expect(screen.getByText("Omar Al-Ghamdi")).toBeInTheDocument();
});

test("adding a driver sends the form", async () => {
  const posted: unknown[] = [];
  mockApi((b) => posted.push(b));
  render(<Drivers />);
  await screen.findByText("Faisal Al-Harbi");
  await userEvent.click(screen.getByRole("button", { name: "Add driver" }));
  await userEvent.type(screen.getByLabelText("Driver ID"), "D-113");
  await userEvent.type(screen.getByLabelText("Full name"), "New Driver");
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Add driver" }));
  await waitFor(() => expect(posted).toEqual([{ code: "D-113", name: "New Driver", phone: "", hub: "", pos_terminal: "" }]));
});
