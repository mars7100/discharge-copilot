/**
 * Specification tests for ticket 11 UI (failed-note background retry): the note_retrying log entry and the final-failure
 * wording, the "Retrying failed notes" step label, the missing-note alert after `done`, and a later `draft` refreshing
 * the final view. fetch is stubbed per route as in App.ticket09.test.tsx; GET /api/sessions/S1 returns the current
 * snapshot, which carries `missing_notes`.
 * Test-imposed: the missing-note alert is an element with role "alert" (flowbite Alert) whose text names each note.
 */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const TEMPLATE = {
  sections: [{ section_id: "hospital_course", title: "Hospital course", purpose: "course", optional: false }],
};
const P = { s1: { text: "Patient admitted.", document_id: "note_01", filename: "note_01.txt", page: 1, marker: "[N01:B02]" } };
const FIRST = "Started IV antibiotics.";
const RETRIED = "Acute kidney injury resolved with fluids.";
const claim = (claim_id: string, text: string) => ({
  claim_id, section: "hospital_course", text, problem: "Pneumonia", evidence_span_ids: ["s1"],
  clinician_clarification_ids: [], support_status: "unverified",
});
const snapshot = (claims: unknown[], missing_notes: string[]) => ({
  session_id: "S1", case_id: "case_001", documents: [], passages: P, events: [], chat_thread_id: "t", load_running: true,
  paused: false, revisions: [], clarifications: [], pending: null, conflicts: [], resolutions: [], missing_notes,
  draft: { claims, discrepancies: [], status: "draft", approved_at: null, reviewer: null },
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let current: unknown = null;

async function start() {
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
    if (key === "GET /api/sessions/S1") return json(current);
    throw new Error(`unexpected request ${key}`);
  }));
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  return { send, close: () => ctrl.close() };
}

/** First pass: note_02 and note_05 fail, the rest extract, then the first draft. */
async function firstPass(send: (name: string, data: unknown) => void, missing: string[]) {
  current = snapshot([claim("C01", FIRST)], missing);
  send("note_failed", { document_id: "note_02", detail: "ExtractionError: boom" });
  send("note_failed", { document_id: "note_05", detail: "ExtractionError: boom" });
  send("note_extracted", { document_id: "note_01", event_count: 2, warnings: [] });
  send("extraction_done", { event_count: 2, warnings: [], conflict_count: 0 });
  send("dedupe_applied", { count: 0, removed: [] });
  send("draft", { draft: (current as any).draft, warnings: [] });
  expect(await screen.findByText(FIRST)).toBeTruthy();
}

const pageText = () => document.body.textContent ?? "";
const missingAlerts = () => screen.queryAllByRole("alert").filter((a) => /note_0[25]/.test(a.textContent ?? ""));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  current = null;
});

it("logs note_retrying, the final-failure wording, and shows the step label until every retry settles", async () => {
  const { send, close } = await start();
  await firstPass(send, ["note_05"]);
  expect(screen.queryByText(/Retrying failed notes/)).toBeNull();

  send("note_retrying", { document_id: "note_02" });
  send("note_retrying", { document_id: "note_05" });
  await waitFor(() => expect(pageText()).toMatch(/note_05: retrying/));
  expect(pageText()).toMatch(/note_02: retrying/);
  expect(screen.getByText(/Retrying failed notes/)).toBeTruthy();

  send("note_extracted", { document_id: "note_02", event_count: 1, warnings: [] });
  await waitFor(() => expect(pageText()).toMatch(/note_02: 1 events/));
  expect(screen.getByText(/Retrying failed notes/)).toBeTruthy(); // note_05 is still unsettled

  send("note_failed", { document_id: "note_05", detail: "ExtractionError: boom again" });
  await waitFor(() => expect(pageText()).toMatch(/note_05: failed after retries — draft is missing this note/));
  expect(pageText()).toMatch(/note_02: failed — ExtractionError: boom/); // a first-pass failure keeps the 06 wording
  await waitFor(() => expect(screen.queryByText(/Retrying failed notes/)).toBeNull());
  send("done", {});
  close();
});

it("shows a missing-note alert naming each missing note only once done arrives", async () => {
  const { send, close } = await start();
  await firstPass(send, ["note_02", "note_05"]);
  send("note_retrying", { document_id: "note_02" });
  send("note_retrying", { document_id: "note_05" });
  send("note_failed", { document_id: "note_02", detail: "ExtractionError: boom again" });
  send("note_failed", { document_id: "note_05", detail: "ExtractionError: boom again" });
  send("draft", { draft: (current as any).draft, warnings: ["note_02: extraction failed after retries — the draft is missing this note"] });
  await waitFor(() => expect(pageText()).toMatch(/note_05: failed after retries/));
  expect(missingAlerts()).toHaveLength(0);

  send("done", {});
  await waitFor(() => expect(missingAlerts()).toHaveLength(1));
  expect(missingAlerts()[0].textContent).toMatch(/note_02/);
  expect(missingAlerts()[0].textContent).toMatch(/note_05/);
  expect(screen.queryByText(/Retrying failed notes/)).toBeNull();
  close();
});

it("a later draft event refreshes the final view, and no missing-note alert shows when the retry succeeded", async () => {
  const { send, close } = await start();
  await firstPass(send, []);
  send("note_retrying", { document_id: "note_02" });
  send("note_extracted", { document_id: "note_02", event_count: 1, warnings: [] });
  current = snapshot([claim("C01", FIRST), claim("C02", RETRIED)], []);
  send("section_drafted", { section_id: "hospital_course", problem: "Pneumonia", warnings: [],
                            claims: [{ section: "hospital_course", text: RETRIED, evidence_span_ids: ["s1"] }] });
  send("dedupe_applied", { count: 0, removed: [] });
  send("draft", { draft: (current as any).draft, warnings: [] });

  expect(await screen.findByText(RETRIED)).toBeTruthy();
  expect(screen.getByText(FIRST)).toBeTruthy();
  send("done", {});
  await waitFor(() => expect(screen.getByRole("button", { name: /^approve$/i }).hasAttribute("disabled")).toBe(false));
  expect(missingAlerts()).toHaveLength(0);
  close();
});
