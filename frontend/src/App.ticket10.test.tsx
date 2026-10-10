/**
 * Specification tests for ticket 10 UI: the progress log has an entry for `dedupe_applied` reading
 * "{count} duplicate claims removed", with one sub-line per removed claim (`section: text`). fetch is stubbed per route
 * as in App.ticket09.test.tsx.
 */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const TEMPLATE = {
  sections: [{ section_id: "reason_for_admission", title: "Reason for admission", purpose: "why", optional: false }],
};
const SESSION = {
  session_id: "S1", case_id: "case_001", documents: [], passages: {}, events: [], chat_thread_id: "t",
  load_running: true, paused: false, revisions: [], clarifications: [], pending: null, conflicts: [], resolutions: [],
  draft: null,
};
const CXR = "Chest X-ray showed right lower lobe consolidation.";
const MED = "Oral Antibiotic B.";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("logs dedupe_applied with the count and one line per removed claim", async () => {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c; } });
  const send = (name: string, data: unknown) =>
    ctrl.enqueue(new TextEncoder().encode(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`));
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${(init?.method ?? "GET").toUpperCase()} ${new URL(String(input), "http://test").pathname}`;
    if (key === "GET /api/cases") return json({ cases: ["case_001"] });
    if (key === "GET /api/template") return json(TEMPLATE);
    if (key === "POST /api/sessions") return json({ session_id: "S1" }, 201);
    if (key === "POST /api/sessions/S1/load") return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    if (key === "GET /api/sessions/S1") return json(SESSION);
    throw new Error(`unexpected request ${key}`);
  }));
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));

  send("extraction_done", { event_count: 3, warnings: [], conflict_count: 0 });
  send("dedupe_applied", {
    count: 2,
    removed: [
      { section: "hospital_course", problem: "Pneumonia", text: CXR },
      { section: "discharge_medications", problem: null, text: MED },
    ],
  });

  expect(await screen.findByText("2 duplicate claims removed")).toBeTruthy();
  expect(screen.getByText(`hospital_course: ${CXR}`)).toBeTruthy();
  expect(screen.getByText(`discharge_medications: ${MED}`)).toBeTruthy();
  expect(screen.getAllByText("dedupe_applied")).toHaveLength(1);
});
