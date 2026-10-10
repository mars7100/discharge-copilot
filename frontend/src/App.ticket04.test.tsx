/**
 * Specification tests for ticket 04 UI (review features + editing lock), through the rendered page.
 * fetch is stubbed per route against a small in-memory server; the load stream is fed by hand.
 * Controls are found by accessible name: question input /question/i, Ask, claim select /claim/i,
 * statement input /statement/i, Propose, Accept, Reject, reviewer input /reviewer/i, Approve, Export;
 * the case picker is the combobox named /case/i.
 * Ticket 13: there is no corrected-text field; the server stub's proposal (REVISION) stands in for the model's text,
 * and Propose stays disabled until a statement is typed.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const TEMPLATE = {
  sections: [
    { section_id: "reason_for_admission", title: "Reason for admission", purpose: "why", optional: false },
    { section_id: "hospital_course", title: "Hospital course", purpose: "course", optional: false },
    { section_id: "follow_up", title: "Follow-up", purpose: "fu", optional: true },
  ],
};

const PASSAGES = {
  s1: { text: "Patient admitted with community-acquired pneumonia; started ceftriaxone.", document_id: "N01",
        filename: "N01_admission_note.pdf", page: 7, marker: "[N01:B03]" },
  s2: { text: "Afebrile, switched to oral antibiotics.", document_id: "N04",
        filename: "N04_progress_note.pdf", page: 1, marker: "[N04:B07]" },
  s3: { text: "Follow up with primary care in one week.", document_id: "N09",
        filename: "N09_discharge_note.pdf", page: 2, marker: "[N09:B01]" },
};

const claim = (claim_id: string, section: string, text: string, evidence_span_ids: string[],
               support_status = "unverified", clinician_clarification_ids: string[] = []) =>
  ({ claim_id, section, text, evidence_span_ids, clinician_clarification_ids, support_status });

const FOLLOW_UP = "Follow up with PCP in one week.";
const AFTER = "Follow up with PCP in two weeks.";
const STATEMENT = "Clinic said two weeks.";
const REVIEWER = "Simulated resident (demo)";

const DRAFT = {
  claims: [
    claim("c1", "reason_for_admission", "Admitted for pneumonia.", ["s1"]),
    claim("c2", "hospital_course", "Treated with IV antibiotics.", ["s2"]),
    claim("c3", "follow_up", FOLLOW_UP, ["s3"], "needs_review"),
  ],
  discrepancies: [{ discrepancy_id: "D01", description: "Antibiotic route differs between notes.",
                    source_span_ids: ["s1", "s2"], status: "open" }],
  status: "draft", approved_at: null, reviewer: null,
};

const REVISION = { revision_id: "R01", target_claim_id: "c3", before: FOLLOW_UP, after: AFTER,
                   clinician_statement: STATEMENT, clarification_id: "K01", source_span_ids: ["s3"], status: "pending" };
const CLARIFICATION = { clarification_id: "K01", statement: STATEMENT, target_claim_id: "c3", status: "pending" };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function loadStream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c; } });
  const enc = new TextEncoder();
  return {
    response: () => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    send: (name: string, data: unknown) => ctrl.enqueue(enc.encode(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`)),
    close: () => ctrl.close(),
  };
}

/** In-memory server for session S1. `ask` decides each ask response. */
function stubApi(stream: ReturnType<typeof loadStream>, ask: (q: string) => Response = () => json({})) {
  const server: any = { draft: structuredClone(DRAFT), revisions: [], clarifications: [], pending: null };
  const snapshot = () => json({ session_id: "S1", case_id: "case_001", documents: [], passages: PASSAGES, events: [],
                                chat_thread_id: "t", load_running: false, ...structuredClone(server) });
  const fetching = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input instanceof Request ? input.url : input), "http://test").pathname;
    const key = `${(init?.method ?? "GET").toUpperCase()} ${path}`;
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (key === "GET /api/cases") return json({ cases: ["case_001"] });
    if (key === "GET /api/template") return json(TEMPLATE);
    if (key === "POST /api/sessions") return json({ session_id: "S1" }, 201);
    if (key === "POST /api/sessions/S1/load") return stream.response();
    if (key === "GET /api/sessions/S1") return snapshot();
    if (key === "POST /api/sessions/S1/ask") return ask(body.question);
    if (key === "POST /api/sessions/S1/corrections") {
      server.pending = { revision: REVISION, clarification: CLARIFICATION };
      return json({ revision: REVISION, clarification: CLARIFICATION }, 201);
    }
    let m = key.match(/^POST \/api\/sessions\/S1\/corrections\/R01\/(accept|reject)$/);
    if (m) {
      const status = m[1] === "accept" ? "accepted" : "rejected";
      server.revisions.push({ ...REVISION, status });
      server.clarifications.push({ ...CLARIFICATION, status });
      server.pending = null;
      if (status === "accepted")
        server.draft.claims[2] = claim("c3", "follow_up", AFTER, ["s3"], "needs_review", ["K01"]);
      return snapshot();
    }
    if (key === "POST /api/sessions/S1/approve") {
      Object.assign(server.draft, { status: "approved", reviewer: body.reviewer, approved_at: "2026-10-10T14:05:00" });
      return snapshot();
    }
    if (key === "GET /api/sessions/S1/export")
      return new Response("# Discharge summary\n", { status: 200, headers: { "Content-Type": "text/markdown" } });
    throw new Error(`unexpected request ${key}`);
  });
  vi.stubGlobal("fetch", fetching);
  return fetching;
}

const requests = (fetching: ReturnType<typeof stubApi>) =>
  fetching.mock.calls.map(([input, init]) =>
    `${(init?.method ?? "GET").toUpperCase()} ${new URL(String(input), "http://test").pathname}`);

const bodyOf = (fetching: ReturnType<typeof stubApi>, req: string) =>
  JSON.parse(String(fetching.mock.calls[requests(fetching).indexOf(req)][1]?.body));

async function startLoad() {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  return user;
}

/** Load through `done`, so the page is ready. */
async function loadReady(stream: ReturnType<typeof loadStream>) {
  const user = await startLoad();
  stream.send("extraction_done", { event_count: 3, warnings: [] });
  stream.send("draft", { draft: DRAFT, warnings: [] });
  stream.send("done", {});
  stream.close();
  await screen.findByText("Treated with IV antibiotics.");
  await waitFor(() => expect(button(/^ask$/i).disabled).toBe(false));
  return user;
}

const button = (name: RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;
const textbox = (name: RegExp) => screen.getByRole("textbox", { name }) as HTMLInputElement;
const pageText = () => document.body.textContent ?? "";
// Rendered text only: the corrected-text textarea may hold the same string as its value.
const SHOWN = { ignore: "textarea, script, style" };

async function proposeCorrection(user: ReturnType<typeof userEvent.setup>) {
  await user.type(textbox(/statement/i), STATEMENT);
  await user.click(button(/propose/i));
  await screen.findByRole("button", { name: /^accept$/i });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ticket 04 review features", () => {
  it("locks review controls after the draft event until done", async () => {
    const stream = loadStream();
    stubApi(stream);
    const user = await startLoad();
    stream.send("extraction_done", { event_count: 3, warnings: [] });
    stream.send("draft", { draft: DRAFT, warnings: [] });
    await screen.findByText("Treated with IV antibiotics.");

    const controls = () => [textbox(/question/i), button(/^ask$/i), screen.getByRole("combobox", { name: /claim/i }),
                            textbox(/statement/i), button(/propose/i), textbox(/reviewer/i),
                            button(/^approve$/i), button(/export/i)] as (HTMLInputElement | HTMLButtonElement)[];
    await waitFor(() => expect(controls().map((c) => c.disabled)).toEqual(Array(8).fill(true)));

    stream.send("done", {});
    stream.close();
    await waitFor(() => expect(textbox(/statement/i).disabled).toBe(false));
    await user.type(textbox(/statement/i), STATEMENT); // ticket 13: Propose needs a statement
    await waitFor(() => expect(controls().slice(0, 7).map((c) => c.disabled)).toEqual(Array(7).fill(false)));
    expect(button(/export/i).disabled).toBe(true); // not approved yet
  });

  it("shows an orange needs-review badge, the status line, and the discrepancy list", async () => {
    const stream = loadStream();
    stubApi(stream);
    await loadReady(stream);

    const row = screen.getByText(FOLLOW_UP, SHOWN).parentElement!;
    expect(within(row).getByText(/^needs review$/i)).toBeTruthy();
    expect(screen.getAllByText(/^needs review$/i)).toHaveLength(1); // only the needs_review claim
    expect(screen.queryByText(/clarified by clinician/i)).toBeNull();
    expect(screen.getByText(/Draft — pending review/)).toBeTruthy();

    expect(screen.getByText(/D01/)).toBeTruthy();
    expect(screen.getByText(/Antibiotic route differs between notes\./)).toBeTruthy();
    expect(pageText()).toMatch(/\bopen\b/);
    for (const p of [PASSAGES.s1, PASSAGES.s2]) {
      expect(screen.getByText(new RegExp(p.text.replace(/[.;]/g, "\\$&")))).toBeTruthy(); // shown inline, not in a popover
      expect(screen.getAllByText(new RegExp(p.filename.replace(".", "\\."))).length).toBeGreaterThan(0);
      expect(screen.getAllByText(new RegExp(p.marker.replace(/[[\]]/g, "\\$&"))).length)
        .toBeGreaterThanOrEqual(2); // claim marker + discrepancy passage
    }
  });

  it("ask shows the question, the answer and its citation markers", async () => {
    const stream = loadStream();
    const fetching = stubApi(stream, () => json({ intent: "question", answer: "It was switched to oral.", cited: ["s2"] }));
    const user = await loadReady(stream);
    const before = screen.getAllByRole("button", { name: "[N04:B07]" }).length;

    await user.type(textbox(/question/i), "When did antibiotics change?");
    await user.click(button(/^ask$/i));

    expect(await screen.findByText("It was switched to oral.")).toBeTruthy();
    expect(screen.getByText("When did antibiotics change?")).toBeTruthy();
    expect(bodyOf(fetching, "POST /api/sessions/S1/ask")).toEqual({ question: "When did antibiotics change?" });
    const markers = screen.getAllByRole("button", { name: "[N04:B07]" });
    expect(markers).toHaveLength(before + 1);
    await user.click(markers[markers.length - 1]);
    within(await screen.findByRole("dialog")).getByText(/N04_progress_note\.pdf/);
  });

  it("a failed ask shows 'Question failed' and keeps earlier history", async () => {
    const stream = loadStream();
    let n = 0;
    stubApi(stream, () => (++n === 1 ? json({ intent: "question", answer: "First answer.", cited: [] })
                                     : json({ detail: "RuntimeError: boom" }, 502)));
    const user = await loadReady(stream);

    await user.type(textbox(/question/i), "First question?");
    await user.click(button(/^ask$/i));
    await screen.findByText("First answer.");
    await user.clear(textbox(/question/i));
    await user.type(textbox(/question/i), "Second question?");
    await user.click(button(/^ask$/i));

    expect(await screen.findByText(/Question failed: RuntimeError: boom/)).toBeTruthy();
    expect(screen.getByText("First answer.")).toBeTruthy();
    expect(screen.getByText("First question?")).toBeTruthy();
  });

  it("propose shows the pending diff and hides the form; Approve is disabled meanwhile", async () => {
    const stream = loadStream();
    const fetching = stubApi(stream);
    const user = await loadReady(stream);

    expect((screen.getByRole("combobox", { name: /claim/i }) as HTMLSelectElement).value).toBe("c3"); // first needs_review
    expect(textbox(/reviewer/i).value).toBe(REVIEWER);
    await proposeCorrection(user);

    expect(bodyOf(fetching, "POST /api/sessions/S1/corrections")).toEqual({ claim_id: "c3", statement: STATEMENT });
    const struck = screen.getAllByText(FOLLOW_UP, SHOWN).filter((el) =>
      el.closest("s, del, strike, .line-through") || getComputedStyle(el).textDecoration.includes("line-through"));
    expect(struck).toHaveLength(1); // Before
    expect(screen.getByText(AFTER, SHOWN)).toBeTruthy();
    expect(screen.getByText(new RegExp(STATEMENT))).toBeTruthy();
    expect(button(/^reject$/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /propose/i })).toBeNull(); // form hidden
    expect(screen.queryByRole("textbox", { name: /corrected/i })).toBeNull();
    expect(button(/^approve$/i).disabled).toBe(true);
    expect(screen.getByText("Accept or reject the pending correction before approving.")).toBeTruthy();
  });

  it("accept updates the claim text and shows the green badge and clinician-provided line", async () => {
    const stream = loadStream();
    stubApi(stream);
    const user = await loadReady(stream);
    await proposeCorrection(user);
    await user.click(button(/^accept$/i));

    await waitFor(() => expect(screen.queryByRole("button", { name: /^accept$/i })).toBeNull());
    expect(screen.queryByText(FOLLOW_UP, SHOWN)).toBeNull();
    const row = screen.getByText(AFTER, SHOWN).parentElement!;
    expect(within(row).getByText(/clarified by clinician — pending approval/)).toBeTruthy();
    expect(screen.queryByText(/^needs review$/i)).toBeNull();
    expect(screen.getByText(`Clinician-provided (K01): "${STATEMENT}"`)).toBeTruthy();
    expect(screen.getByText(/R01 → c3: accepted/)).toBeTruthy();
    expect(button(/propose/i)).toBeTruthy(); // form back
    expect(button(/^approve$/i).disabled).toBe(false);
  });

  it("reject leaves the claim text unchanged", async () => {
    const stream = loadStream();
    stubApi(stream);
    const user = await loadReady(stream);
    await proposeCorrection(user);
    await user.click(button(/^reject$/i));

    await waitFor(() => expect(screen.queryByRole("button", { name: /^reject$/i })).toBeNull());
    expect(screen.getByText(FOLLOW_UP, SHOWN)).toBeTruthy();
    expect(screen.queryByText(AFTER, SHOWN)).toBeNull();
    expect(screen.queryByText(/clarified by clinician/i)).toBeNull();
    expect(screen.getByText(/R01 → c3: rejected/)).toBeTruthy();
  });

  it("Export is disabled until approved, then downloads the export endpoint's Markdown", async () => {
    const stream = loadStream();
    const fetching = stubApi(stream);
    const user = await loadReady(stream);
    const createObjectURL = vi.fn(() => "blob:export");
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push(this.download);
    });

    expect(button(/export/i).disabled).toBe(true);
    await user.click(button(/^approve$/i));
    expect(await screen.findByText(/Approved by Simulated resident \(demo\) at 2026-10-10 14:05/)).toBeTruthy();
    expect(bodyOf(fetching, "POST /api/sessions/S1/approve")).toEqual({ reviewer: REVIEWER });

    await waitFor(() => expect(button(/export/i).disabled).toBe(false));
    await user.click(button(/export/i));
    await waitFor(() => expect(downloads).toEqual(["discharge_summary_case_001.md"]));
    expect(requests(fetching)).toContain("GET /api/sessions/S1/export");
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
  });
});
