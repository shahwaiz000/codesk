import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import RouteArt from "./RouteArt";

test("the welcome illustration tells the day's story in words too", () => {
  render(<RouteArt />);
  expect(screen.getByRole("img", { name: /parcel is delivered.*deposited at the bank/ })).toBeInTheDocument();
  for (const word of ["Delivered", "Collected", "Deposited"]) expect(screen.getByText(word)).toBeInTheDocument();
});
