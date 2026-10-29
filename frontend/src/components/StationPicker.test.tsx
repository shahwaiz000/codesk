import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api, rememberStation, withStation } from "../lib";
import { StationProvider } from "../stations";
import { StationPicker } from "./StationPicker";

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
  const picker = await screen.findByRole("button", { name: "Station" });
  await waitFor(() => expect(screen.getByText("2 stations")).toBeInTheDocument());
  await userEvent.click(picker);
  expect(screen.getAllByRole("option")).toHaveLength(3);
  await userEvent.type(screen.getByPlaceholderText("Find a city or code"), "jed");
  expect(screen.getAllByRole("option")).toHaveLength(1);
  await userEvent.keyboard("{Enter}");
  expect(await screen.findByText("JED · Makkah")).toBeInTheDocument();
  await api("/dashboard");
  expect(headers[headers.length - 1]).toBe("2");
  expect(withStation("/api/reports/day?date=2026-10-27")).toBe("/api/reports/day?date=2026-10-27&station=2");
  await userEvent.click(picker);
  await userEvent.click(screen.getByRole("option", { name: /All stations/ }));
  await api("/dashboard");
  expect(headers[headers.length - 1]).toBeNull();
});
