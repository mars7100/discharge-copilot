/**
 * Specification tests for ticket 08 UI: sections stream in (section_drafted / section_omitted) before the final draft.
 * fetch is stubbed per route; the load stream is fed by hand. GET /api/sessions/S1 returns the session without a draft
 * until the `draft` event has been sent (passages are available from the start, for the early citation markers).
 */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const TEMPLATE = {
  sections: [
    { section_id: "reason_for_admission", title: "Reason for admission", purpose: "why", optional: false },
    { section_id: "discharge_diagnoses", title: "Discharge diagnoses", purpose: "diagnoses", optional: true },
    { section_id: "hospital_course", title: "Hospital course", purpose: "course", optional: false },
    { section_id: "procedures", title: "Procedures", purpose: "procedures", optional: true },
  ],
};

const P = {
  s1: { text: "Patient admitted with community-acquired pneumonia.", document_id: "note_01",
        filename: "note_01.txt", page: 1, marker: "[N01:B02]" },
  s2: { text: "Afebrile, switched to oral antibiotics.", document_id: "note_04",
        filename: "note_04.txt", page: 1, marker: "[N04:B03]" },
};
const REASON = "Admitted with community-acquired pneumonia.";
const COURSE = "Switched to oral antibiotics once afebrile.";

const CLAIMS = [
  { claim_id: "C01", section: "reason_for_admission", text: REASON, evidence_span_ids: ["s1"],
    clinician_clarification_ids: [], support_status: "unverified" },
  { claim_id: "C02", section: "hospital_course", text: COURSE, evidence_span_ids: ["s2"],
    clinician_clarification_ids: [], support_status: "needs_review" },
];
const DRAFT = { claims: CLAIMS, discrepancies: [], status: "draft", approved_at: null, reviewer: null };
const SESSION = {
  session_id: "S1", case_id: "case_001", documents: [], passages: P, events: [], chat_thread_id: "t",
  load_running: true, paused: false, revisions: [], clarifications: [], pending: null, conflicts: [], resolutions: [],
  draft: null as unknown,
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function sseStream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c; } });
  const enc = new TextEncoder();
  return {
    response: () => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    send: (name: string, data: unknown) => ctrl.enqueue(enc.encode(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`)),
    close: () => ctrl.close(),
  };
}

const pageText = () => document.body.textContent ?? "";
const early = ({ section, text, evidence_span_ids }: typeof CLAIMS[number]) => ({ section, text, evidence_span_ids });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("renders streamed sections early, without claim IDs or controls, then the full draft; editing locked until done", async () => {
  const load = sseStream();
  let drafted = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${(init?.method ?? "GET").toUpperCase()} ${new URL(String(input), "http://test").pathname}`;
    if (key === "GET /api/cases") return json({ cases: ["case_001"] });
    if (key === "GET /api/template") return json(TEMPLATE);
    if (key === "POST /api/sessions") return json({ session_id: "S1" }, 201);
    if (key === "POST /api/sessions/S1/load") return load.response();
    if (key === "GET /api/sessions/S1") return json(drafted ? { ...SESSION, draft: DRAFT, load_running: false } : SESSION);
    throw new Error(`unexpected request ${key}`);
  }));
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));

  load.send("extraction_done", { event_count: 2, warnings: [], conflict_count: 0 });
  // completion order differs from template order
  load.send("section_drafted", { section_id: "hospital_course", claims: [early(CLAIMS[1])], warnings: [] });
  load.send("section_omitted", { section_id: "procedures" });
  load.send("section_drafted", { section_id: "reason_for_admission", claims: [early(CLAIMS[0])], warnings: [] });

  const reason = await screen.findByText(REASON);
  const course = await screen.findByText(COURSE);
  expect(reason.compareDocumentPosition(course) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // template order
  expect(screen.getByText("Reason for admission")).toBeTruthy();
  expect(screen.getByText("Hospital course")).toBeTruthy();
  expect(screen.queryByText("Procedures")).toBeNull(); // omitted section stays hidden
  expect(screen.queryByText("Discharge diagnoses")).toBeNull(); // not arrived yet

  // progress log: one entry per section event
  expect(screen.getAllByText("section_drafted")).toHaveLength(2);
  expect(screen.getAllByText("section_omitted")).toHaveLength(1);

  // no claim IDs, badges or claim controls yet
  expect(pageText()).not.toMatch(/\bC0[12]\b/);
  expect(screen.queryByText(/needs review/i)).toBeNull();
  expect(screen.queryByRole("combobox", { name: "Claim" })).toBeNull();
  for (const b of screen.queryAllByRole("button", { name: /^(ask|approve|propose correction)$/i }))
    expect((b as HTMLButtonElement).disabled).toBe(true);

  // citation markers work early
  await user.click(screen.getByRole("button", { name: "[N04:B03]" }));
  const popover = await screen.findByRole("dialog");
  within(popover).getByText(/Afebrile, switched to oral antibiotics\./);
  await user.keyboard("{Escape}");

  // final snapshot replaces the early view with the full render
  drafted = true;
  load.send("draft", { draft: DRAFT, warnings: [] });
  await screen.findByRole("option", { name: "C01" });
  expect(screen.getByRole("option", { name: "C02" })).toBeTruthy();
  expect(screen.getByText(/needs review/i)).toBeTruthy();
  expect(screen.getAllByText(REASON)).toHaveLength(1);
  expect(screen.getAllByText(COURSE)).toHaveLength(1);
  expect((screen.getByRole("button", { name: /^ask$/i }) as HTMLButtonElement).disabled).toBe(true); // locked until done

  load.send("done", {});
  load.close();
  await waitFor(() => expect((screen.getByRole("button", { name: /^ask$/i }) as HTMLButtonElement).disabled).toBe(false));
});
