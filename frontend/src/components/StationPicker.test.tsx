import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api, rememberStation, withStation } from "../lib";
import { StationProvider } from "../stations";
import { StationPicker } from "./Layout";

afterEach(() => { vi.restoreAllMocks(); rememberStation(""); });

const LIST = { unassigned_drivers: 0, stations: [
  { id: 1, code: "RUH", name: "Riyadh", city: "Riyadh", region: "Riyadh", active: true, drivers: 6 },
  { id: 2, code: "JED", name: "Jeddah", city: "Jeddah", region: "Makkah", active: true, drivers: 11 },
] };

test("choosing a station sends it with every request and on download links", async () => {
  const headers: (string | null)[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    headers.push(new Headers(init?.headers).get("X-Station"));
    return new Response(JSON.stringify(String(input).includes("/stations") ? LIST : {}), { status: 200 });
  });
  render(<MemoryRouter><StationProvider><StationPicker /></StationProvider></MemoryRouter>);
  const picker = await screen.findByLabelText("Station");
  await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(3));
  expect(screen.getAllByText("All stations")).toHaveLength(2);
  await userEvent.selectOptions(picker, "2");
  expect(await screen.findByText("Makkah")).toBeInTheDocument();
  await api("/dashboard");
  expect(headers[headers.length - 1]).toBe("2");
  expect(withStation("/api/reports/day?date=2026-10-27")).toBe("/api/reports/day?date=2026-10-27&station=2");
  await userEvent.selectOptions(picker, "");
  await api("/dashboard");
  expect(headers[headers.length - 1]).toBeNull();
});
