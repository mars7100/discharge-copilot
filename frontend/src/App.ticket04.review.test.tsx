/** Regressions for defects found in review of ticket 04 (not part of the protected spec tests). */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const DRAFT = { claims: [], discrepancies: [], status: "draft", approved_at: null, reviewer: null };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("a 422 with a validation-error list does not show [object Object]", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${input}`;
    if (key === "GET /api/cases") return json({ cases: ["case_001"] });
    if (key === "GET /api/template") return json({ sections: [] });
    if (key === "POST /api/sessions") return json({ session_id: "S1" }, 201);
    if (key === "POST /api/sessions/S1/load") return new Response(`event: draft\ndata: {}\n\nevent: done\ndata: {}\n\n`);
    if (key === "GET /api/sessions/S1") return json({ case_id: "case_001", passages: {}, revisions: [], clarifications: [], pending: null, draft: DRAFT });
    if (key === "POST /api/sessions/S1/approve") return json({ detail: [{ type: "string_pattern_mismatch", loc: ["body", "reviewer"] }] }, 422);
    throw new Error(`unexpected ${key}`);
  }));
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  const approve = await screen.findByRole("button", { name: /approve/i });
  await vi.waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
  await user.clear(screen.getByRole("textbox", { name: /reviewer/i }));
  await user.click(approve);
  expect(await screen.findByText(/approve: 422/)).toBeTruthy();
  expect(screen.queryByText(/object Object/)).toBeNull();
});
