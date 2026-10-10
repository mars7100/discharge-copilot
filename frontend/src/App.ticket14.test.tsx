/**
 * Specification tests for ticket 14: the client-side review summary between the "Resolve conflicts" panel and resuming the load.
 * fetch is stubbed per route (as in ticket 07); load and resolutions streams are fed by hand.
 * Controls by accessible name: panel radios /use this value/i and /clarify/i, the panel button /review resolutions/i,
 * the summary heading "Review resolutions", and the summary buttons /^edit$/i and /start drafting/i.
 */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

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
const REPICKED = "Medication A dose differs between notes: Medication A 5 mg given this shift.";
const TYPED = "Target SpO2 92-96% throughout";
const PADDED = `   ${TYPED}  `;

const SNAPSHOT = {
  session_id: "S1", case_id: "case_001", documents: [], passages: P, events: [], chat_thread_id: "t",
  load_running: false, paused: false, revisions: [], clarifications: [], pending: null, conflicts: [D01, D02],
  resolutions: [{ conflict_id: "D01", text: PICKED }, { conflict_id: "D02", text: TYPED }],
  draft: {
    claims: [{ claim_id: "C01", section: "hospital_course", text: "Medication A dosing documented.", evidence_span_ids: ["s4"],
               clinician_clarification_ids: ["D01"], support_status: "needs_review" }],
    discrepancies: [], status: "draft", approved_at: null, reviewer: null,
  },
};
const TEMPLATE = { sections: [{ section_id: "hospital_course", title: "Hospital course", purpose: "course", optional: false }] };

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

function stubApi(load: ReturnType<typeof sseStream>, resolutions: () => Response | Promise<Response>) {
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
const button = (name: RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;
const reviewButton = () => button(/review resolutions/i);
const summaryHeading = () => screen.queryByRole("heading", { name: /review resolutions/i });
const resolutionPosts = (f: ReturnType<typeof stubApi>) =>
  f.mock.calls.filter(([u, i]) => String(u).endsWith("/api/sessions/S1/resolutions") && i?.method === "POST");

/** Loads, pauses on D01 + D02, picks the first D01 quote and clarifies D02 with padded text. */
async function answered(resolutions: () => Response | Promise<Response> = () => json({ detail: "unused" }, 500)) {
  const load = sseStream();
  const fetching = stubApi(load, resolutions);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  load.send("extraction_done", { event_count: 9, warnings: [], conflict_count: 2 });
  load.send("conflicts_found", { conflicts: [D01, D02] });
  load.close();
  await screen.findAllByText(/resolve conflicts/i);
  await user.click(screen.getAllByRole("radio", { name: /use this value/i })[0]); // D01: [N04:B07]
  await user.click(screen.getAllByRole("radio", { name: /clarify/i })[1]); // D02: clarify
  await user.type(screen.getAllByRole("textbox").at(-1)!, PADDED);
  return { user, fetching };
}

async function reviewing(resolutions?: () => Response | Promise<Response>) {
  const ctx = await answered(resolutions);
  await ctx.user.click(reviewButton());
  await waitFor(() => expect(summaryHeading()).toBeTruthy());
  return ctx;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("the panel button sends no request and replaces the panel with a summary, one row per conflict in panel order", async () => {
  const { user, fetching } = await answered();
  expect(reviewButton().disabled).toBe(false);
  await user.click(reviewButton());

  await waitFor(() => expect(summaryHeading()).toBeTruthy());
  expect(resolutionPosts(fetching)).toHaveLength(0);
  expect(screen.queryAllByRole("radio")).toHaveLength(0); // the panel is not shown
  expect(screen.queryByRole("heading", { name: /resolve conflicts/i })).toBeNull();
  expect(pageText()).toMatch(/Waiting for conflict resolution/);

  const text = pageText();
  const at = (s: string) => { const i = text.indexOf(s); expect(i, s).toBeGreaterThanOrEqual(0); return i; };
  expect(at("D01")).toBeLessThan(at(D01.description));
  expect(at(D01.description)).toBeLessThan(at("D02"));
  expect(at("D02")).toBeLessThan(at(D02.description));
});

it("a pick row shows the chosen quote's marker and quote, and stores '{description}: {quote}'", async () => {
  await reviewing();
  expect(pageText()).toContain("[N04:B07]");
  expect(pageText()).toContain("Medication A 10 mg daily.");
  expect(pageText()).toContain(PICKED);
  expect(pageText()).not.toContain("[N05:B04]"); // only the chosen quote
});

it("a clarification row shows the trimmed text as both the choice and the stored text", async () => {
  await reviewing();
  expect(pageText()).toMatch(/Clarification/);
  expect(pageText().split(TYPED).length - 1).toBeGreaterThanOrEqual(2);
  expect(pageText()).not.toContain(PADDED);
});

it("Edit returns to the panel with picks and clarifications kept; resubmitting shows the updated summary", async () => {
  const { user, fetching } = await reviewing();
  await user.click(button(/^edit$/i));

  await screen.findByRole("heading", { name: /resolve conflicts/i });
  expect(summaryHeading()).toBeNull();
  const picks = screen.getAllByRole("radio", { name: /use this value/i }) as HTMLInputElement[];
  expect(picks.map((r) => r.checked)).toEqual([true, false, false, false]);
  expect((screen.getAllByRole("radio", { name: /clarify/i }) as HTMLInputElement[]).map((r) => r.checked)).toEqual([false, true]);
  expect((screen.getAllByRole("textbox").at(-1) as HTMLInputElement).value.trim()).toBe(TYPED);
  expect(reviewButton().disabled).toBe(false);

  await user.click(picks[1]); // D01: [N05:B04]
  await user.click(reviewButton());
  await waitFor(() => expect(summaryHeading()).toBeTruthy());
  expect(pageText()).toContain("[N05:B04]");
  expect(pageText()).toContain(REPICKED);
  expect(pageText()).not.toContain(PICKED);
  expect(pageText().split(TYPED).length - 1).toBeGreaterThanOrEqual(2);
  expect(resolutionPosts(fetching)).toHaveLength(0);
});

it("Start drafting posts today's body, is disabled in flight, then streams to done and unlocks", async () => {
  const resume = sseStream();
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  const { user, fetching } = await reviewing(async () => { await gate; return resume.response(); });

  await user.click(button(/start drafting/i));
  await waitFor(() => expect(resolutionPosts(fetching)).toHaveLength(1));
  const [, init] = resolutionPosts(fetching)[0];
  expect(new Headers(init!.headers).get("Content-Type")).toMatch(/application\/json/);
  expect(JSON.parse(String(init!.body))).toEqual({
    resolutions: [
      { conflict_id: "D01", chosen_span_id: "s4", clarification: null },
      { conflict_id: "D02", chosen_span_id: null, clarification: TYPED },
    ],
  });
  expect(button(/start drafting/i).disabled).toBe(true);

  release();
  await waitFor(() => expect(summaryHeading()).toBeNull());
  resume.send("draft", { draft: SNAPSHOT.draft, warnings: [] });
  await screen.findByText("Medication A dosing documented.");
  expect(button(/^ask$/i).disabled).toBe(true); // locked until done
  resume.send("done", {});
  resume.close();
  await waitFor(() => expect(button(/^ask$/i).disabled).toBe(false));
  expect(resolutionPosts(fetching)).toHaveLength(1);
});

it("a 422 on Start drafting keeps the summary and shows the detail; Edit then works", async () => {
  const { user, fetching } = await reviewing(() => json({ detail: "chosen span s4 is not a quote of D01" }, 422));

  await user.click(button(/start drafting/i));
  await waitFor(() => expect(pageText()).toContain("chosen span s4 is not a quote of D01"));
  expect(resolutionPosts(fetching)).toHaveLength(1);
  expect(summaryHeading()).toBeTruthy();
  expect(pageText()).toContain(PICKED);
  expect(button(/start drafting/i).disabled).toBe(false);
  expect(button(/^edit$/i).disabled).toBe(false);

  await user.click(button(/^edit$/i));
  await screen.findByRole("heading", { name: /resolve conflicts/i });
  expect((screen.getAllByRole("radio", { name: /use this value/i })[0] as HTMLInputElement).checked).toBe(true);
  expect((screen.getAllByRole("textbox").at(-1) as HTMLInputElement).value.trim()).toBe(TYPED);
});

it("ask, corrections, approve and export stay locked while the summary is shown", async () => {
  await reviewing();
  const locked = (name: RegExp) => {
    const b = screen.queryByRole("button", { name }) as HTMLButtonElement | null;
    expect(b === null || b.disabled, String(name)).toBe(true);
  };
  locked(/^ask$/i);
  locked(/propose correction/i);
  locked(/^accept$/i);
  locked(/^reject$/i);
  locked(/^approve$/i);
  locked(/export markdown/i);
});
