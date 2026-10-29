import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import Ask from "./Ask";

afterEach(() => vi.restoreAllMocks());

test("a question is answered with the figures it used", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.method === "POST"
      ? { answer: "Cash collected on Wed 28 Oct: **36,873.50 SAR**\n- Deposited: no, due today", used: [{ tool: "day_summary", args: { date: "2026-10-28" } }] }
      : url.includes("/ai") ? { engine: "gemini", ready: true, reason: "", gemini_model: "gemini-2.5-flash", demo_mode: true } : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  render(<MemoryRouter><Ask /></MemoryRouter>);
  expect(await screen.findByText(/Google Gemini \(gemini-2.5-flash\), demo data only/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /How much cash did we collect/ }));
  expect(await screen.findByText("36,873.50 SAR")).toBeInTheDocument();
  expect(screen.getByText("Deposited: no, due today")).toBeInTheDocument();
  expect(screen.getByText("Figures used (1)")).toBeInTheDocument();
});
