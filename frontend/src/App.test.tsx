/**
 * Specification tests for ticket 03b UI, through the rendered page.
 * fetch is stubbed per route; the load stream is a ReadableStream the test feeds by hand,
 * so an event can be asserted visible while the stream is still open.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const CASES = ["case_001", "case_002", "case_003"];

// Template order: reason, diagnoses (optional, empty), course, condition (required, empty), follow-up (optional).
const TEMPLATE = {
  sections: [
    { section_id: "reason_for_admission", title: "Reason for admission", purpose: "why", optional: false },
    { section_id: "discharge_diagnoses", title: "Discharge diagnoses", purpose: "dx", optional: true },
    { section_id: "hospital_course", title: "Hospital course", purpose: "course", optional: false },
    { section_id: "condition_at_discharge", title: "Condition at discharge", purpose: "cond", optional: false },
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
               support_status = "unverified") =>
  ({ claim_id, section, text, evidence_span_ids, clinician_clarification_ids: [], support_status });

// Claims deliberately out of template order.
const DRAFT = {
  claims: [
    claim("c3", "follow_up", "Follow up with PCP in one week.", ["s3"], "needs_review"),
    claim("c2", "hospital_course", "Treated with IV antibiotics.", ["s1", "s2"]),
    claim("c1", "reason_for_admission", "Admitted for pneumonia.", ["s1"]),
  ],
  discrepancies: [], status: "draft", approved_at: null, reviewer: null,
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** A load stream the test writes to; it stays open until close(). */
function loadStream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c; } });
  const enc = new TextEncoder();
  const raw = (text: string) => ctrl.enqueue(enc.encode(text));
  return {
    response: () => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    raw,
    send: (name: string, data: unknown) => raw(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`),
    close: () => ctrl.close(),
  };
}
type Stream = ReturnType<typeof loadStream>;

/**
 * Stubs fetch. Each POST /api/sessions mints the next id (S1, S2, ...); each POST .../load
 * answers with the next entry of `loads` (a stream, or a Response for a failed request).
 */
function stubApi(loads: (Stream | Response)[]) {
  let sessions = 0;
  const fetching = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input instanceof Request ? input.url : input), "http://test").pathname;
    const key = `${(init?.method ?? "GET").toUpperCase()} ${path}`;
    if (key === "GET /api/cases") return json({ cases: CASES });
    if (key === "GET /api/template") return json(TEMPLATE);
    if (key === "POST /api/sessions") return json({ session_id: `S${++sessions}` }, 201);
    let m = key.match(/^POST \/api\/sessions\/(\w+)\/load$/);
    if (m) {
      const next = loads.shift();
      if (!next) throw new Error(`unexpected load of ${m[1]}`);
      return next instanceof Response ? next : next.response();
    }
    m = key.match(/^GET \/api\/sessions\/(\w+)$/);
    if (m) return json({ session_id: m[1], case_id: "case_001", documents: [], passages: PASSAGES, events: [],
                         draft: DRAFT, chat_thread_id: "t", load_running: false });
    throw new Error(`unexpected request ${key}`);
  });
  vi.stubGlobal("fetch", fetching);
  return fetching;
}

/** "METHOD /path" of every request, in order. */
const requests = (fetching: ReturnType<typeof stubApi>) =>
  fetching.mock.calls.map(([input, init]) =>
    `${(init?.method ?? "GET").toUpperCase()} ${new URL(String(input), "http://test").pathname}`);

async function startLoad(caseId = "case_001") {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: caseId });
  await user.selectOptions(screen.getByRole("combobox"), caseId);
  await user.click(screen.getByRole("button", { name: /load/i }));
  return user;
}

function expectInOrder(...els: Element[]) {
  for (let i = 1; i < els.length; i++)
    expect(els[i - 1].compareDocumentPosition(els[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}

const pageText = () => document.body.textContent ?? "";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("discharge copilot UI", () => {
  it("always shows the synthetic-data warning", () => {
    stubApi([]);
    render(<App />);
    expect(screen.getByText("SYNTHETIC DEMONSTRATION — NOT FOR CLINICAL USE")).toBeTruthy();
  });

  it("lists cases; Load creates a session for the picked case, then starts its load", async () => {
    const stream = loadStream();
    const fetching = stubApi([stream]);
    await startLoad("case_002");

    for (const c of CASES) expect(screen.getByRole("option", { name: c })).toBeTruthy();
    await waitFor(() => expect(requests(fetching)).toContain("POST /api/sessions/S1/load"));
    const reqs = requests(fetching);
    expect(reqs.indexOf("POST /api/sessions")).toBeLessThan(reqs.indexOf("POST /api/sessions/S1/load"));
    const createCall = fetching.mock.calls[reqs.indexOf("POST /api/sessions")];
    expect(JSON.parse(String(createCall[1]?.body))).toEqual({ case_id: "case_002" });
  });

  it("disables picker and Load during a load; afterwards Load creates a new session", async () => {
    const first = loadStream();
    const second = loadStream();
    const fetching = stubApi([first, second]);
    const user = await startLoad("case_001");

    await waitFor(() => expect((screen.getByRole("button", { name: /load/i }) as HTMLButtonElement).disabled).toBe(true));
    expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(true);

    first.send("extraction_done", { event_count: 1, warnings: [] });
    first.send("draft", { draft: DRAFT, warnings: [] });
    first.send("done", {});
    first.close();
    await waitFor(() => expect((screen.getByRole("button", { name: /load/i }) as HTMLButtonElement).disabled).toBe(false));
    expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(false);
    await screen.findByText("Treated with IV antibiotics.");

    await user.selectOptions(screen.getByRole("combobox"), "case_003");
    await user.click(screen.getByRole("button", { name: /load/i }));
    await waitFor(() => expect(requests(fetching)).toContain("POST /api/sessions/S2/load"));
    const creates = fetching.mock.calls.filter((_, i) => requests(fetching)[i] === "POST /api/sessions");
    expect(creates.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([{ case_id: "case_001" }, { case_id: "case_003" }]);

    second.send("extraction_done", { event_count: 1, warnings: [] });
    second.send("draft", { draft: DRAFT, warnings: [] });
    await waitFor(() => expect(requests(fetching)).toContain("GET /api/sessions/S2"));
    expect(requests(fetching).filter((r) => r === "GET /api/template")).toHaveLength(1); // fetched once
  });

  it("renders each progress event as it arrives, while the stream is still open", async () => {
    vi.useFakeTimers({ toFake: ["Date", "performance"] });
    const stream = loadStream();
    stubApi([stream]);
    await startLoad();

    expect(await screen.findByText(/Extracting/)).toBeTruthy();
    vi.advanceTimersByTime(3000);
    stream.send("extraction_done", { event_count: 37, warnings: ["dropped event e9: bad quote"] });

    expect(await screen.findByText(/extraction_done/)).toBeTruthy(); // stream still open
    expect(pageText()).toMatch(/(?<!\d)37\s*events?|events?\W*37(?!\d)/i);
    expect(screen.getByText(/dropped event e9: bad quote/)).toBeTruthy();
    expect(pageText()).toMatch(/(?<![\d.])3(\.0+)?\s?s/); // elapsed seconds since Load
    expect(await screen.findByText(/Drafting/)).toBeTruthy();
    expect(screen.queryByText(/Extracting/)).toBeNull();

    stream.send("draft", { draft: DRAFT, warnings: ["claim c9 dropped"] });
    expect(await screen.findByText(/^draft\b/)).toBeTruthy();
    expect(pageText()).toMatch(/(?<!\d)3\s*claims?|claims?\W*3(?!\d)/i);
    expect(screen.getByText(/claim c9 dropped/)).toBeTruthy();

    stream.send("section_drafted", { section_id: "hospital_course" }); // unknown event: appended by name
    expect(await screen.findByText(/section_drafted/)).toBeTruthy();

    stream.send("done", {});
    expect(await screen.findByText(/^done\b/)).toBeTruthy();
    stream.close();
    await waitFor(() => expect(screen.queryByText(/Drafting/)).toBeNull());
  });

  it("parses an SSE block split across chunks", async () => {
    const stream = loadStream();
    stubApi([stream]);
    await startLoad();

    stream.raw('event: extraction_done\ndata: {"event_count": 4');
    stream.raw(', "warnings": ["split-warning"]}\n');
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/split-warning/)).toBeNull(); // block not complete yet
    stream.raw("\n");
    expect(await screen.findByText(/split-warning/)).toBeTruthy();
    expect(screen.getAllByText(/extraction_done/)).toHaveLength(1);
  });

  it("renders the draft by section in template order with citation markers", async () => {
    const stream = loadStream();
    stubApi([stream]);
    await startLoad();
    stream.send("extraction_done", { event_count: 1, warnings: [] });
    stream.send("draft", { draft: DRAFT, warnings: [] });

    const course = await screen.findByText("Treated with IV antibiotics.");
    const markers = await screen.findAllByRole("button", { name: "[N01:B03]" });
    expect(markers).toHaveLength(2); // cited by c1 and c2
    const courseMarkers = [markers[1], screen.getByRole("button", { name: "[N04:B07]" })];

    expectInOrder(
      screen.getByText("Reason for admission"), screen.getByText("Admitted for pneumonia."),
      screen.getByText("Hospital course"), course, ...courseMarkers,
      screen.getByText("Condition at discharge"), screen.getByText("Not documented in the supplied notes."),
      screen.getByText("Follow-up"), screen.getByText("Follow up with PCP in one week."), // needs_review: plain
      screen.getByRole("button", { name: "[N09:B01]" }),
    );
    expect(screen.getAllByText("Not documented in the supplied notes.")).toHaveLength(1);
    expect(screen.queryByText("Discharge diagnoses")).toBeNull(); // empty optional section omitted
  });

  it("opens a marker's passage in a popover; Esc and outside click close it", async () => {
    const stream = loadStream();
    stubApi([stream]);
    const user = await startLoad();
    stream.send("draft", { draft: DRAFT, warnings: [] });
    const [marker] = await screen.findAllByRole("button", { name: "[N01:B03]" });

    await user.click(marker);
    const popover = await screen.findByRole("dialog");
    within(popover).getByText(/N01_admission_note\.pdf/);
    within(popover).getByText(/Patient admitted with community-acquired pneumonia; started ceftriaxone\./);
    within(popover).getByText(/\[N01:B03\]/);
    expect(popover.textContent).toMatch(/\b7\b/); // page

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(marker);
    await screen.findByRole("dialog");
    await user.click(screen.getByText("Hospital course"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("an error event shows an Alert; Retry reloads the same session and restarts the timeline", async () => {
    const first = loadStream();
    const retry = loadStream();
    const fetching = stubApi([first, retry]);
    const user = await startLoad();

    first.send("extraction_done", { event_count: 2, warnings: [] });
    first.send("error", { detail: "RuntimeError: boom" });
    first.close();
    const alert = await screen.findByRole("alert");
    within(alert).getByText(/RuntimeError: boom/);

    await user.click(within(alert).getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(requests(fetching).filter((r) => r === "POST /api/sessions/S1/load")).toHaveLength(2));
    expect(requests(fetching).filter((r) => r === "POST /api/sessions")).toHaveLength(1); // same session

    retry.send("extraction_done", { event_count: 2, warnings: [] });
    await screen.findByText(/extraction_done/);
    expect(screen.getAllByText(/extraction_done/)).toHaveLength(1); // previous attempt's entries cleared
  });

  it("a failed load request shows an Alert with Retry", async () => {
    const retry = loadStream();
    const fetching = stubApi([json({ detail: "unknown session" }, 404), retry]);
    const user = await startLoad();

    const alert = await screen.findByRole("alert");
    await user.click(within(alert).getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(requests(fetching).filter((r) => r === "POST /api/sessions/S1/load")).toHaveLength(2));
  });
});
