/**
 * Specification tests for ticket 09 UI: the hospital course is grouped under one subheading per problem, in the early
 * streamed view (one section_drafted per problem call, carrying `problem`) and in the final view (claims carry
 * `problem`). Test-imposed: a problem subheading is a heading element whose accessible name is the problem name.
 * fetch is stubbed per route as in App.ticket08.test.tsx.
 */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const TEMPLATE = {
  sections: [
    { section_id: "reason_for_admission", title: "Reason for admission", purpose: "why", optional: false },
    { section_id: "hospital_course", title: "Hospital course", purpose: "course", optional: false },
    { section_id: "follow_up", title: "Follow-up", purpose: "follow-up", optional: false },
  ],
};
const P = {
  s1: { text: "Patient admitted with community-acquired pneumonia.", document_id: "note_01",
        filename: "note_01.txt", page: 1, marker: "[N01:B02]" },
};
const REASON = "Admitted with pneumonia.";
const PNEU = "Switched to oral antibiotics once afebrile.";
const HTN = "Amlodipine continued.";
const NOT_DOCUMENTED = "Not documented in the supplied notes.";

const claim = (claim_id: string, section: string, text: string, problem: string | null) => ({
  claim_id, section, text, problem, evidence_span_ids: ["s1"], clinician_clarification_ids: [], support_status: "unverified",
});
const CLAIMS = [
  claim("C01", "reason_for_admission", REASON, null),
  claim("C02", "hospital_course", PNEU, "Pneumonia"),
  claim("C03", "hospital_course", HTN, "Hypertension"),
];
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

/** The text of the last heading before `el` in document order. */
function headingBefore(el: HTMLElement) {
  const before = screen.getAllByRole("heading").filter((h) => h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  return before[before.length - 1]?.textContent;
}

const follows = (a: HTMLElement, b: HTMLElement) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

async function start(draft: () => unknown) {
  const load = sseStream();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${(init?.method ?? "GET").toUpperCase()} ${new URL(String(input), "http://test").pathname}`;
    if (key === "GET /api/cases") return json({ cases: ["case_001"] });
    if (key === "GET /api/template") return json(TEMPLATE);
    if (key === "POST /api/sessions") return json({ session_id: "S1" }, 201);
    if (key === "POST /api/sessions/S1/load") return load.response();
    if (key === "GET /api/sessions/S1") {
      const d = draft();
      return json(d ? { ...SESSION, draft: d, load_running: false } : SESSION);
    }
    throw new Error(`unexpected request ${key}`);
  }));
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  load.send("extraction_done", { event_count: 3, warnings: [], conflict_count: 0 });
  return load;
}

const early = (c: typeof CLAIMS[number]) => ({ section: c.section, text: c.text, evidence_span_ids: c.evidence_span_ids });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("groups the hospital course under problem subheadings in the early view and the final view", async () => {
  let drafted = false;
  const DRAFT = { claims: CLAIMS, discrepancies: [], status: "draft", approved_at: null, reviewer: null };
  const load = await start(() => (drafted ? DRAFT : null));

  load.send("section_drafted", { section_id: "hospital_course", problem: "Pneumonia", claims: [early(CLAIMS[1])], warnings: [] });
  load.send("section_drafted", { section_id: "hospital_course", problem: "Elevated BP", claims: [], warnings: [] });
  load.send("section_drafted", { section_id: "hospital_course", problem: "Hypertension", claims: [early(CLAIMS[2])], warnings: [] });
  load.send("section_drafted", { section_id: "reason_for_admission", problem: null, claims: [early(CLAIMS[0])], warnings: [] });

  // early view: every non-empty problem group has its subheading and its claims; the empty group is not shown
  expect(headingBefore(await screen.findByText(PNEU))).toBe("Pneumonia");
  expect(headingBefore(await screen.findByText(HTN))).toBe("Hypertension");
  expect(headingBefore(await screen.findByText(REASON))).toBe("Reason for admission");
  expect(screen.getByRole("heading", { name: "Hospital course" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Elevated BP" })).toBeNull();
  expect(screen.queryByText(NOT_DOCUMENTED, { selector: "div" })).toBeNull(); // hospital course has claims; follow-up not yet arrived

  // final view: subheadings in claim order, each followed by its claims
  drafted = true;
  load.send("draft", { draft: DRAFT, warnings: [] });
  await screen.findByRole("option", { name: "C01" });
  const pneu = screen.getByRole("heading", { name: "Pneumonia" });
  const htn = screen.getByRole("heading", { name: "Hypertension" });
  expect(follows(screen.getByRole("heading", { name: "Hospital course" }), pneu)).toBe(true);
  expect(follows(pneu, htn)).toBe(true);
  expect(headingBefore(screen.getByText(PNEU))).toBe("Pneumonia");
  expect(headingBefore(screen.getByText(HTN))).toBe("Hypertension");
  expect(headingBefore(screen.getByText(REASON))).toBe("Reason for admission");
  expect(screen.getAllByText(PNEU)).toHaveLength(1);
  expect(screen.queryByRole("heading", { name: "Elevated BP" })).toBeNull();

  load.send("done", {});
  load.close();
  await waitFor(() => expect((screen.getByRole("button", { name: /^ask$/i }) as HTMLButtonElement).disabled).toBe(false));
});

it("shows 'Not documented' for the hospital course when no problem group has claims", async () => {
  const load = await start(() => null);
  load.send("section_drafted", { section_id: "hospital_course", problem: "Pneumonia", claims: [], warnings: [] });
  load.send("section_drafted", { section_id: "reason_for_admission", problem: null, claims: [early(CLAIMS[0])], warnings: [] });
  load.send("section_drafted", { section_id: "hospital_course", problem: "Other", claims: [], warnings: [] });

  await screen.findByText(REASON);
  const notDocumented = await screen.findByText(NOT_DOCUMENTED);
  expect(headingBefore(notDocumented)).toBe("Hospital course");
  expect(screen.queryByRole("heading", { name: "Pneumonia" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Other" })).toBeNull();
});
