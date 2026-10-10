/**
 * Specification tests for ticket 13 UI (model-proposed corrections), through the rendered page.
 * fetch is stubbed per route; `propose` decides each POST .../corrections response (the model's proposal or an error).
 * Controls by accessible name: claim select /claim/i, statement input /clinician statement/i, Propose correction,
 * Accept, Reject. The in-flight label is "Proposing…".
 */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

const TEMPLATE = { sections: [
  { section_id: "reason_for_admission", title: "Reason for admission", purpose: "why", optional: false },
  { section_id: "follow_up", title: "Follow-up", purpose: "fu", optional: true },
] };
const PASSAGES = {
  s1: { text: "Admitted with pneumonia.", document_id: "N01", filename: "N01.txt", page: 1, marker: "[N01:B01]" },
  s2: { text: "Follow up with primary care in one week.", document_id: "N02", filename: "N02.txt", page: 1, marker: "[N02:B01]" },
};
const claim = (claim_id: string, section: string, text: string, ids: string[], support_status = "unverified") =>
  ({ claim_id, section, text, evidence_span_ids: ids, clinician_clarification_ids: [], support_status });

const BEFORE = "Follow up with PCP in one week.";
const PROPOSED = "Follow up with the primary care clinic within 7 days of discharge.";
const STATEMENT = "Primary care clinic within 7 days.";
const DRAFT = { claims: [claim("c1", "reason_for_admission", "Admitted for pneumonia.", ["s1"]),
                         claim("c2", "follow_up", BEFORE, ["s2"], "needs_review")],
                discrepancies: [], status: "draft", approved_at: null, reviewer: null };
const REVISION = { revision_id: "R01", target_claim_id: "c2", before: BEFORE, after: PROPOSED, clinician_statement: STATEMENT,
                   clarification_id: "K01", source_span_ids: ["s2"], status: "pending" };
const CLARIFICATION = { clarification_id: "K01", statement: STATEMENT, target_claim_id: "c2", status: "pending" };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const proposal = () => json({ revision: REVISION, clarification: CLARIFICATION }, 201);

function stubApi(propose: () => Response | Promise<Response> = proposal) {
  const enc = new TextEncoder();
  const sse = ["extraction_done", { event_count: 2, warnings: [] }, "draft", { draft: DRAFT, warnings: [] }, "done", {}];
  const stream = () => new Response(new ReadableStream<Uint8Array>({ start(c) {
    for (let i = 0; i < sse.length; i += 2) c.enqueue(enc.encode(`event: ${sse[i]}\ndata: ${JSON.stringify(sse[i + 1])}\n\n`));
    c.close();
  } }), { status: 200, headers: { "Content-Type": "text/event-stream" } });
  const fetching = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${(init?.method ?? "GET").toUpperCase()} ${new URL(String(input), "http://test").pathname}`;
    if (key === "GET /api/cases") return json({ cases: ["case_001"] });
    if (key === "GET /api/template") return json(TEMPLATE);
    if (key === "POST /api/sessions") return json({ session_id: "S1" }, 201);
    if (key === "POST /api/sessions/S1/load") return stream();
    if (key === "GET /api/sessions/S1")
      return json({ session_id: "S1", case_id: "case_001", documents: [], passages: PASSAGES, events: [], chat_thread_id: "t",
                    load_running: false, draft: DRAFT, revisions: [], clarifications: [], pending: null });
    if (key === "POST /api/sessions/S1/corrections") return propose();
    throw new Error(`unexpected request ${key}`);
  });
  vi.stubGlobal("fetch", fetching);
  return fetching;
}

const button = (name: RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;
const statement = () => screen.getByRole("textbox", { name: /clinician statement/i }) as HTMLInputElement;
const claimSelect = () => screen.getByRole("combobox", { name: /claim/i }) as HTMLSelectElement;
const SHOWN = { ignore: "textarea, script, style" };

async function loadReady() {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  await waitFor(() => expect(statement().disabled).toBe(false));
  return user;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("has a statement input and no corrected-text field; Propose is disabled until a statement is typed", async () => {
  stubApi();
  const user = await loadReady();
  expect(screen.queryByRole("textbox", { name: /corrected/i })).toBeNull();
  expect(document.querySelector("textarea")).toBeNull();
  expect(button(/propose correction/i).disabled).toBe(true);
  await user.type(statement(), "   ");
  expect(button(/propose correction/i).disabled).toBe(true);
  await user.clear(statement());
  await user.type(statement(), STATEMENT);
  expect(button(/propose correction/i).disabled).toBe(false);
});

it("proposing sends the claim and statement only, shows Proposing… in flight, then the proposed After with Accept/Reject", async () => {
  let answer!: (r: Response) => void;
  const fetching = stubApi(() => new Promise<Response>((r) => { answer = r; }));
  const user = await loadReady();
  await user.type(statement(), STATEMENT);
  await user.click(button(/propose correction/i));

  const inFlight = await screen.findByRole("button", { name: /proposing…/i }) as HTMLButtonElement;
  expect(inFlight.disabled).toBe(true);
  const call = fetching.mock.calls.find(([u, i]) => String(u).endsWith("/corrections") && i?.method === "POST")!;
  expect(JSON.parse(String(call[1]!.body))).toEqual({ claim_id: "c2", statement: STATEMENT });

  answer(proposal());
  await screen.findByRole("button", { name: /^accept$/i });
  expect(button(/^reject$/i)).toBeTruthy();
  expect(screen.getByText(PROPOSED, SHOWN)).toBeTruthy();
  const struck = screen.getAllByText(BEFORE, SHOWN).filter((el) => el.closest("s, del, strike, .line-through"));
  expect(struck).toHaveLength(1);
  expect(screen.getByText(new RegExp(STATEMENT))).toBeTruthy();
});

it("an error shows its detail and keeps the claim and statement", async () => {
  stubApi(() => json({ detail: "the statement did not change the claim" }, 422));
  const user = await loadReady();
  await user.selectOptions(claimSelect(), "c1");
  await user.type(statement(), STATEMENT);
  await user.click(button(/propose correction/i));

  expect(await screen.findByText(/the statement did not change the claim/)).toBeTruthy();
  expect(statement().value).toBe(STATEMENT);
  expect(claimSelect().value).toBe("c1");
  expect(button(/propose correction/i).disabled).toBe(false);
  expect(screen.queryByRole("button", { name: /^accept$/i })).toBeNull();
});
