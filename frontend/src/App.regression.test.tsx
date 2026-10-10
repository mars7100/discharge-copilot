/** Review regressions for ticket 03b (not part of the protected spec tests). */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("the case picker has an accessible name", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ cases: ["case_001"] })));
  render(<App />);
  expect(await screen.findByRole("combobox", { name: /case/i })).toBeTruthy();
});

it("Retry after a failed session create does not reload the previous case's session", async () => {
  const calls: string[] = [];
  let creates = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${input}`;
    calls.push(key);
    if (key === "GET /api/cases") return json({ cases: ["case_001", "case_002"] });
    if (key === "POST /api/sessions") return ++creates === 1 ? json({ session_id: "S1" }, 201) : json({}, 500);
    if (key === "POST /api/sessions/S1/load") return new Response("event: done\ndata: {}\n\n");
    throw new Error(`unexpected ${key}`);
  }));
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_002" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  await screen.findByText(/^done\b/);

  await user.selectOptions(screen.getByRole("combobox", { name: /case/i }), "case_002");
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  const alert = await screen.findByRole("alert");
  const retry = within(alert).getByRole("button", { name: /retry/i }) as HTMLButtonElement;
  await waitFor(() => expect(screen.getByRole("button", { name: /^load$/i })).toHaveProperty("disabled", false));
  await user.click(retry);
  expect(calls.filter((c) => c === "POST /api/sessions/S1/load")).toHaveLength(1);
});
