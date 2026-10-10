/**
 * Specification tests for ticket 07 UI: the "Resolve conflicts" panel shown on conflicts_found.
 * fetch is stubbed per route; load and resolutions streams are fed by hand.
 * Controls by accessible name: radios /use this value/i (one per quote, in order) and /clarify/i (one per conflict),
 * the clarification text inputs (the only textboxes while paused; the last one belongs to the last conflict),
 * and the button /resolve and continue/i.
 */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const TEMPLATE = {
  sections: [
    { section_id: "reason_for_admission", title: "Reason for admission", purpose: "why", optional: false },
    { section_id: "hospital_course", title: "Hospital course", purpose: "course", optional: false },
  ],
};

const P = {
  s4: { text: "Current medications: Intravenous Antibiotic B. Medication A 10 mg daily.", document_id: "note_04",
        filename: "note_04.txt", page: 1, marker: "[N04:B07]" },
  s5: { text: "Medications: Medication A 5 mg given this shift. First dose of oral Antibiotic B given.",
        document_id: "note_05", filename: "note_05.txt", page: 1, marker: "[N05:B04]" },
  s2: { text: "Target SpO2 88-92% overnight.", document_id: "note_02", filename: "note_02.txt", page: 1, marker: "[N02:B03]" },
  s3: { text: "Target SpO2 92-96% per team.", document_id: "note_03", filename: "note_03.txt", page: 1, marker: "[N03:B02]" },
};
const quote = (id: keyof typeof P, q: string, date: string, hospital_day: number) =>
  ({ span_id: id, quote: q, document_id: P[id].document_id, filename: P[id].filename, date, hospital_day,
     marker: P[id].marker, text: P[id].text });

const D01 = { conflict_id: "D01", description: "Medication A dose differs between notes",
              quotes: [quote("s4", "Medication A 10 mg daily.", "2026-03-04", 3),
                       quote("s5", "Medication A 5 mg given this shift.", "2026-03-04", 3)] };
const D02 = { conflict_id: "D02", description: "Oxygen target differs",
              quotes: [quote("s2", "Target SpO2 88-92% overnight.", "2026-03-02", 1),
                       quote("s3", "Target SpO2 92-96% per team.", "2026-03-03", 2)] };

const PICKED = "Medication A dose differs between notes: Medication A 10 mg daily.";
const TYPED = "Target SpO2 92-96% throughout";

const SNAPSHOT = {
  session_id: "S1", case_id: "case_001", documents: [], passages: P, events: [], chat_thread_id: "t",
  load_running: false, paused: false, revisions: [], clarifications: [], pending: null,
  conflicts: [D01, D02],
  resolutions: [
    { conflict_id: "D01", text: PICKED, chosen_span_id: "s4", quotes: D01.quotes.map(({ span_id, quote }) => ({ span_id, quote, start: 0 })),
      provenance: "clinician-provided" },
    { conflict_id: "D02", text: TYPED, chosen_span_id: null, quotes: D02.quotes.map(({ span_id, quote }) => ({ span_id, quote, start: 0 })),
      provenance: "clinician-provided" },
  ],
  draft: {
    claims: [
      { claim_id: "C01", section: "reason_for_admission", text: "Admitted with pneumonia.", evidence_span_ids: ["s2"],
        clinician_clarification_ids: [], support_status: "unverified" },
      { claim_id: "C02", section: "hospital_course", text: "Medication A dosing documented.", evidence_span_ids: ["s4", "s5"],
        clinician_clarification_ids: ["D01"], support_status: "needs_review" },
    ],
    discrepancies: [
      { discrepancy_id: "D01", description: D01.description, source_span_ids: ["s4", "s5"], status: "clarified_pending_approval" },
      { discrepancy_id: "D02", description: D02.description, source_span_ids: ["s2", "s3"], status: "clarified_pending_approval" },
    ],
    status: "draft", approved_at: null, reviewer: null,
  },
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

function stubApi(load: ReturnType<typeof sseStream>, resolutions: () => Response) {
  const fetching = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${(init?.method ?? "GET").toUpperCase()} ${new URL(String(input), "http://test").pathname}`;
    if (key === "GET /api/cases") return json({ cases: ["case_001"] });
    if (key === "GET /api/template") return json(TEMPLATE);
    if (key === "POST /api/sessions") return json({ session_id: "S1" }, 201);
    if (key === "POST /api/sessions/S1/load") return load.response();
    if (key === "POST /api/sessions/S1/resolutions") return resolutions();
    if (key === "GET /api/sessions/S1") return json(SNAPSHOT);
    throw new Error(`unexpected request ${key}`);
  });
  vi.stubGlobal("fetch", fetching);
  return fetching;
}

const pageText = () => document.body.textContent ?? "";
const submitButton = () => screen.getByRole("button", { name: /resolve and continue/i }) as HTMLButtonElement;

async function pausedOn(conflicts: unknown[], resolutions: () => Response) {
  const load = sseStream();
  const fetching = stubApi(load, resolutions);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  load.send("extraction_done", { event_count: 9, warnings: [], conflict_count: conflicts.length });
  load.send("conflicts_found", { conflicts });
  load.close();
  await screen.findAllByText(/resolve conflicts/i);
  return { user, fetching };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows each conflict's passages and waits for every conflict to be resolved before submitting", async () => {
  const resume = sseStream();
  const { user, fetching } = await pausedOn([D01, D02], () => resume.response());

  await waitFor(() => expect(pageText()).toMatch(/Waiting for conflict resolution/));
  for (const c of [D01, D02]) {
    expect(pageText()).toContain(c.conflict_id);
    expect(pageText()).toContain(c.description);
    for (const q of c.quotes) {
      expect(pageText()).toContain(q.marker);
      expect(pageText()).toContain(q.filename);
      expect(pageText()).toContain(q.date);
      expect(pageText()).toContain(q.text);
    }
  }
  expect(pageText()).toMatch(/Day\s*3/i);
  expect(screen.getAllByRole("radio", { name: /use this value/i })).toHaveLength(4);
  expect(screen.getAllByRole("radio", { name: /clarify/i })).toHaveLength(2);

  expect(submitButton().disabled).toBe(true);
  await user.click(screen.getAllByRole("radio", { name: /use this value/i })[0]); // D01: [N04:B07]
  expect(submitButton().disabled).toBe(true);
  await user.click(screen.getAllByRole("radio", { name: /clarify/i })[1]); // D02: clarify
  const input = screen.getAllByRole("textbox").at(-1)!;
  await user.type(input, "   ");
  expect(submitButton().disabled).toBe(true); // blank clarification does not count
  await user.clear(input);
  await user.type(input, TYPED);
  expect(submitButton().disabled).toBe(false);

  await user.click(submitButton());
  await waitFor(() => expect(fetching.mock.calls.some(([u, i]) =>
    String(u).endsWith("/api/sessions/S1/resolutions") && i?.method === "POST")).toBe(true));
  const [, init] = fetching.mock.calls.find(([u]) => String(u).endsWith("/resolutions"))!;
  const sent = JSON.parse(String(init!.body)).resolutions
    .map((r: any) => ({ conflict_id: r.conflict_id, chosen_span_id: r.chosen_span_id ?? null, clarification: r.clarification ?? null }))
    .sort((a: any, b: any) => a.conflict_id.localeCompare(b.conflict_id));
  expect(sent).toEqual([
    { conflict_id: "D01", chosen_span_id: "s4", clarification: null },
    { conflict_id: "D02", chosen_span_id: null, clarification: TYPED },
  ]);

  resume.send("draft", { draft: SNAPSHOT.draft, warnings: [] });
  await screen.findByText("Medication A dosing documented.");
  expect((screen.getByRole("button", { name: /^ask$/i }) as HTMLButtonElement).disabled).toBe(true); // locked until done
  resume.send("done", {});
  resume.close();

  await waitFor(() => expect((screen.getByRole("button", { name: /^ask$/i }) as HTMLButtonElement).disabled).toBe(false));
  expect(pageText()).toContain(`Resolved (clinician-provided): ${PICKED}`);
  expect(pageText()).toContain(`Resolved (clinician-provided): ${TYPED}`);
  expect(screen.getByText(/clarified by clinician — pending approval/)).toBeTruthy();
  const line = screen.getByText(/Clinician-provided \(D01\)/);
  expect(line.textContent).toContain(PICKED);
});

it("keeps the panel and shows the error when the submit fails", async () => {
  const { user } = await pausedOn([D01], () => json({ detail: "not paused" }, 409));
  await user.click(screen.getAllByRole("radio", { name: /clarify/i })[0]);
  await user.type(screen.getAllByRole("textbox").at(-1)!, "Medication A 5 mg initially, 10 mg from Day 3");
  await user.click(submitButton());
  await waitFor(() => expect(pageText()).toMatch(/not paused/));
  expect(screen.getAllByText(/resolve conflicts/i).length).toBeGreaterThan(0);
  expect(submitButton()).toBeTruthy();
});
