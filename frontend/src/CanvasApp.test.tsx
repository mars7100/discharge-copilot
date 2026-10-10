import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import CanvasApp from "./CanvasApp";

const passage = { document_id: "N1", filename: "note.txt", page: 2, marker: "[N1:B1]", text: "Exact original source passage." };
const claim = { claim_id: "C1", section: "course", text: "Original draft claim.", evidence_span_ids: ["s1"], support_status: "needs_review", clinician_clarification_ids: [] as string[] };
const draft = { claims: [claim], discrepancies: [{ discrepancy_id: "D1", description: "Two values differ.", status: "open", source_span_ids: ["s1"] }], status: "draft", reviewer: null as string | null, approved_at: null as string | null };
const revision = { revision_id: "R1", target_claim_id: "C1", before: claim.text, after: "Server proposed wording.", clinician_statement: "Clinician statement.", status: "pending" };
const clarification = { clarification_id: "K1", statement: revision.clinician_statement, status: "pending" };
const conflicts = [
    { conflict_id: "D1", description: "Two values differ.", quotes: [
        { ...passage, span_id: "s1", quote: "Value one", date: "2026-01-01", hospital_day: 1 },
        { ...passage, span_id: "s2", quote: "Value two", marker: "[N1:B2]", date: null, hospital_day: null },
    ] },
    { conflict_id: "D2", description: "Another discrepancy.", quotes: [
        { ...passage, span_id: "s1", quote: "Value one", date: null, hospital_day: null },
        { ...passage, span_id: "s2", quote: "Value two", date: null, hospital_day: null },
    ] },
];

/** Encode a JSON mock response. */
function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Provide a manually controlled real ReadableStream for incremental assertions. */
function events(): { response: Response; raw: (text: string) => void; send: (name: string, data: unknown) => void; close: () => void; canceled: ReturnType<typeof vi.fn> } {
    let ctrl!: ReadableStreamDefaultController<Uint8Array>;
    const canceled = vi.fn();
    const body = new ReadableStream<Uint8Array>({ start(c) { ctrl = c; }, cancel: canceled });
    const raw = (text: string): void => ctrl.enqueue(new TextEncoder().encode(text));
    return { response: new Response(body), raw, send: (name, data) => raw(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`), close: () => ctrl.close(), canceled };
}

/** Create the current server snapshot without inventing frontend business behavior. */
function snapshot() {
    return {
        session_id: "S1", case_id: "case_one", documents: [{ document_id: "N1", filename: "note.txt", date: null, hospital_day: null, type: "Note", author_role: null }],
        passages: { s1: passage, s2: { ...passage, marker: "[N1:B2]" } },
        events: [{ event_id: "E1", category: "status", statement: "Extracted source event.", evidence: [{ span_id: "s1", quote: "Exact original" }] }],
        draft: null as typeof draft | null, revisions: [] as typeof revision[], clarifications: [] as typeof clarification[],
        pending: null as { revision: typeof revision; clarification: typeof clarification } | null,
        resolutions: [] as { conflict_id: string; text: string; chosen_span_id: string | null }[], missing_notes: [] as string[],
    };
}

/** Stub only existing routes and the agreed streamed ask contract. */
function server() {
    const load = events(); const resume = events();
    const state = snapshot();
    const asks: ReturnType<typeof events>[] = [];
    let snapshotResponse: (() => Response | Promise<Response>) | undefined;
    let proposalResponse: (() => Response | Promise<Response>) | undefined;
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const path = String(input); const key = `${init?.method ?? "GET"} ${path}`;
        if (key === "GET /api/cases") return json({ cases: ["case_one", "case_two"] });
        if (key === "GET /api/template") return json({ sections: [{ section_id: "course", title: "Hospital course", optional: false }] });
        if (key === "POST /api/sessions") return json({ session_id: "S1" });
        if (key === "POST /api/sessions/S1/load") return load.response;
        if (key === "GET /api/sessions/S1") return snapshotResponse ? snapshotResponse() : json(state);
        if (key === "POST /api/sessions/S1/resolutions") {
            const body = JSON.parse(String(init?.body));
            state.resolutions = body.resolutions.map((r: { conflict_id: string; chosen_span_id: string | null; clarification: string | null }) => ({ conflict_id: r.conflict_id, chosen_span_id: r.chosen_span_id, text: r.clarification ?? "Two values differ.: Value one" }));
            return resume.response;
        }
        if (key === "POST /api/sessions/S1/ask/stream") { const ask = events(); asks.push(ask); return ask.response; }
        if (key === "POST /api/sessions/S1/corrections") {
            if (proposalResponse) return proposalResponse();
            const n = state.revisions.length + 1;
            state.pending = { revision: { ...revision, revision_id: `R${n}` }, clarification: { ...clarification, clarification_id: `K${n}` } }; return json(state.pending);
        }
        if (/^POST \/api\/sessions\/S1\/corrections\/R\d+\/(accept|reject)$/.test(key)) {
            const accepted = path.endsWith("accept"); const status = accepted ? "accepted" : "rejected";
            const pending = state.pending!;
            state.pending = null; state.revisions.push({ ...pending.revision, status }); state.clarifications.push({ ...pending.clarification, status });
            if (accepted) state.draft = { ...draft, claims: [{ ...claim, text: pending.revision.after, clinician_clarification_ids: [pending.clarification.clarification_id] }] };
            return json(state);
        }
        if (key === "POST /api/sessions/S1/approve") {
            state.draft = { ...state.draft!, status: "approved", reviewer: JSON.parse(String(init?.body)).reviewer, approved_at: "2026-01-01T12:00:00" }; return json(state);
        }
        if (key === "GET /api/sessions/S1/export?format=docx") return new Response(new Uint8Array([80, 75, 3, 4]), {
            headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
        });
        throw new Error(`Unexpected request ${key}`);
    });
    vi.stubGlobal("fetch", fetcher);
    return { load, resume, state, asks, fetcher,
        snapshotResponse: (handler: () => Response | Promise<Response>): void => { snapshotResponse = handler; },
        proposalResponse: (handler: () => Response | Promise<Response>): void => { proposalResponse = handler; },
    };
}

/** Find an accessible button and its enabled state. */
function button(name: string | RegExp): HTMLButtonElement {
    return screen.getByRole("button", { name }) as HTMLButtonElement;
}

/** Render and start loading the chosen case. */
async function start(s: ReturnType<typeof server>): Promise<void> {
    render(<CanvasApp />);
    await screen.findByRole("option", { name: "case_one" });
    fireEvent.click(button("Load case"));
    await waitFor(() => expect(s.fetcher.mock.calls.some(([p]) => String(p).endsWith("/load"))).toBe(true));
    fireEvent.click(button(/Source notes/));
}

/** Complete the load and open results review. */
async function ready(s: ReturnType<typeof server>): Promise<void> {
    await start(s); s.state.draft = structuredClone(draft);
    s.load.send("extraction_done", { event_count: 1, warnings: [] }); s.load.send("draft", { draft: s.state.draft, warnings: [] });
    s.load.send("done", {}); s.load.close();
    await waitFor(() => expect(button("Ask about this case").disabled).toBe(false));
    fireEvent.click(button("Results review"));
}

/** Submit a chat question and wait for its streaming response. */
async function question(s: ReturnType<typeof server>, text: string): Promise<ReturnType<typeof events>> {
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: text } });
    const n = s.asks.length;
    fireEvent.click(button(/^Ask$/));
    await waitFor(() => expect(s.asks.length).toBe(n + 1));
    return s.asks[n];
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test("source folder counts real outcomes, exposes every selectable note, and leaves conflict and writer cards separate", async () => {
    const s = server();
    s.state.documents = Array.from({ length: 7 }, (_, i) => ({ ...s.state.documents[0], document_id: `N${i + 1}`, filename: `note-${i + 1}.txt` }));
    await start(s);
    const folder = button(/Source notes/);
    expect(folder.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("region", { name: "Source note cards" }).querySelectorAll("button")).toHaveLength(7);
    expect(folder.textContent).toContain("0 of 7 complete");
    expect(folder.querySelectorAll(".breathing i")).toHaveLength(6);
    s.load.send("note_extracted", { document_id: "N1", event_count: 1 });
    s.load.send("note_failed", { document_id: "N2", detail: "Exact extraction failure" });
    s.load.send("note_retrying", { document_id: "N3" });
    await screen.findByText("1 failed · 1 retrying");
    expect(folder.textContent).toContain("1 of 7 complete");
    expect((screen.getByRole("progressbar", { name: "Source extraction progress" }) as HTMLProgressElement).value).toBe(1);
    fireEvent.click(button(/note-1.txt/));
    expect(screen.getByLabelText("Contextual inspector").textContent).toContain(passage.text);
    expect(screen.getByLabelText("Contextual inspector").textContent).toContain("Extracted source event.");
    fireEvent.click(button(/note-7.txt/));
    expect(within(screen.getByLabelText("Contextual inspector")).getByRole("heading", { name: "note-7.txt" })).toBeTruthy();
    fireEvent.click(button(/note-2.txt/));
    expect(button(/note-2.txt/).textContent).toContain("Exact extraction failure");
    s.load.send("extraction_done", {}); s.load.send("conflicts_found", { conflicts }); s.load.close();
    await screen.findByRole("heading", { name: "Resolve conflicts" });
    await waitFor(() => expect(button("Load case").disabled).toBe(false));
    folder.focus();
    await userEvent.keyboard("{Enter}");
    expect(folder.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: /note-7.txt/ })).toBeNull();
    expect(folder.querySelector(".breathing")).toBeNull();
    expect(screen.getByText("1 failed · 1 retrying · Processing stopped")).toBeTruthy();
    expect(button(/Reconcile the notes/).textContent).toContain("2 decisions required");
    expect(button(/Compose the draft/).closest(".ca-source-folder")).toBeNull();
    await userEvent.keyboard(" ");
    expect(folder.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("region", { name: "Source note cards" }).querySelectorAll("button")).toHaveLength(7);
    expect(screen.getByRole("heading", { name: "Resolve conflicts" })).toBeTruthy();
});

test("chat follows visual viewport resize and scroll and removes listeners when minimized", async () => {
    const viewport = Object.assign(new EventTarget(), { height: 600, offsetTop: 0 });
    vi.stubGlobal("visualViewport", viewport);
    const remove = vi.spyOn(viewport, "removeEventListener");
    const s = server(); await ready(s);
    fireEvent.click(button("Ask about this case"));
    const root = document.querySelector<HTMLElement>(".ca-app")!;
    expect(root.style.getPropertyValue("--ca-visible-height")).toBe("600px");
    viewport.height = 350; viewport.offsetTop = 30;
    act(() => viewport.dispatchEvent(new Event("resize")));
    expect(root.style.getPropertyValue("--ca-keyboard-offset")).toBe(`${Math.max(0, window.innerHeight - 380)}px`);
    viewport.offsetTop = 60;
    act(() => viewport.dispatchEvent(new Event("scroll")));
    expect(root.style.getPropertyValue("--ca-keyboard-offset")).toBe(`${Math.max(0, window.innerHeight - 410)}px`);
    fireEvent.click(button("Minimize case chat"));
    expect(remove).toHaveBeenCalledWith("resize", expect.any(Function));
    expect(remove).toHaveBeenCalledWith("scroll", expect.any(Function));
    expect(root.style.getPropertyValue("--ca-keyboard-offset")).toBe("");
});

test("conflict checkpoint stores exact chosen/trimmed text, Edit preserves inputs, and only Start drafting posts once", async () => {
    const s = server(); await start(s);
    s.load.send("extraction_done", { event_count: 1 }); s.load.send("conflicts_found", { conflicts }); s.load.close();
    await screen.findByRole("heading", { name: "Resolve conflicts" });
    await waitFor(() => expect(button("Load case").disabled).toBe(false));
    expect(button("Review resolutions").disabled).toBe(true);
    fireEvent.click(screen.getAllByRole("radio", { name: "Use this value: Value one" })[0]);
    fireEvent.change(screen.getByLabelText("Clinician clarification D2"), { target: { value: "   " } });
    expect(button("Review resolutions").disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Clinician clarification D2"), { target: { value: "  Exact clinician plan.\n " } });
    fireEvent.click(button("Review resolutions"));
    expect(screen.getByText("Stored as: Two values differ.: Value one")).toBeTruthy();
    expect(screen.getByText("Stored as: Exact clinician plan.")).toBeTruthy();
    expect(s.fetcher.mock.calls.filter(([p]) => String(p).endsWith("/resolutions"))).toHaveLength(0);
    fireEvent.click(button("Edit"));
    expect((screen.getByLabelText("Clinician clarification D2") as HTMLTextAreaElement).value).toBe("  Exact clinician plan.\n ");
    expect((screen.getAllByRole("radio", { name: "Use this value: Value one" })[0] as HTMLInputElement).checked).toBe(true);
    fireEvent.click(button("Review resolutions")); fireEvent.click(button("Start drafting"));
    fireEvent.click(button("Start drafting"));
    await waitFor(() => expect(s.fetcher.mock.calls.filter(([p]) => String(p).endsWith("/resolutions"))).toHaveLength(1));
    const posted = s.fetcher.mock.calls.find(([p]) => String(p).endsWith("/resolutions"))!;
    expect(JSON.parse(String(posted[1]?.body))).toEqual({ resolutions: [
        { conflict_id: "D1", chosen_span_id: "s1", clarification: null },
        { conflict_id: "D2", chosen_span_id: null, clarification: "Exact clinician plan." },
    ] });
    s.state.draft = structuredClone(draft); s.resume.send("draft", { draft });
    await screen.findByText(claim.text);
    expect(button("Ask about this case").disabled).toBe(true);
    s.resume.send("done", {}); s.resume.close();
    await waitFor(() => expect(button("Results review").disabled).toBe(false));
    fireEvent.click(button("Results review"));
    expect(document.body.textContent).toContain('Clinician-provided (D2): "Exact clinician plan."');
});

test("ingestion metadata and live sections expose sources without a raw activity log", async () => {
    const s = server(); await start(s);
    const note = await screen.findByRole("button", { name: /note.txt/ });
    expect(note.textContent).toContain("individual start unknown");
    expect(note.querySelectorAll(".breathing i")).toHaveLength(6);
    fireEvent.click(note);
    expect(screen.getAllByText(passage.text)).toHaveLength(2);
    expect(screen.getByText(/Extracted source event/)).toBeTruthy();
    s.load.send("note_extracted", { document_id: "N1", event_count: 1, warnings: ["Exact validation warning"] });
    s.load.send("extraction_done", { event_count: 1 });
    s.load.send("section_drafted", { section_id: "course", problem: "Documented problem", claims: [claim], warnings: [] });
    fireEvent.click(button(/Compose the draft/));
    await screen.findByText(claim.text);
    expect(screen.getByRole("heading", { name: "Documented problem" })).toBeTruthy();
    fireEvent.click(button("Inspect [N1:B1]"));
    expect(within(screen.getByLabelText("Contextual inspector")).getByText(passage.text)).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText("Contextual inspector"));
    expect(screen.queryByText(/Actual activity log/)).toBeNull();
    expect(document.body.textContent).not.toContain("note_started");
    fireEvent.click(button("Stop watching load"));
    await waitFor(() => expect(s.load.canceled).toHaveBeenCalled());
    expect(screen.getByRole("alert").textContent).toContain("Server work continues");
});

test("chat waits for done AND its snapshot, including note retries and missing notes", async () => {
    const s = server(); await start(s); s.state.draft = structuredClone(draft);
    s.load.send("draft", { draft }); s.load.send("note_retrying", { document_id: "N2" });
    await screen.findByText("Retrying failed notes");
    expect(button("Ask about this case").disabled).toBe(true);
    s.load.send("note_failed", { document_id: "N2", detail: "Retry failed" });
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Reading source notes"));
    await waitFor(() => expect(s.fetcher.mock.calls.filter(([p]) => String(p) === "/api/sessions/S1").length).toBeGreaterThanOrEqual(3));
    let release!: (r: Response) => void;
    s.snapshotResponse(() => new Promise<Response>(resolve => { release = resolve; }));
    s.state.missing_notes = ["N2"]; s.load.send("done", {}); s.load.close();
    await waitFor(() => expect(release).toBeTypeOf("function"));
    expect(button("Ask about this case").disabled).toBe(true);
    expect(screen.queryByRole("alert")).toBeNull();
    await act(async () => { release(json(s.state)); });
    await waitFor(() => expect(button("Ask about this case").disabled).toBe(false));
    expect(screen.getByRole("alert").textContent).toContain("N2");
});

test("corrections use server Before/After, reject preserves claim, accept invalidates approval, export is server DOCX", async () => {
    const s = server(); await ready(s);
    expect(button("Propose correction").disabled).toBe(true);
    expect(button("Download Word document").disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: "Reviewer name" } });
    fireEvent.click(button("Approve draft"));
    await waitFor(() => expect(button("Download Word document").disabled).toBe(false));
    const createObjectURL = vi.fn((_blob: Blob) => "blob:test"); Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const downloads: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement): void {
        downloads.push(this.download);
    });
    fireEvent.click(button("Download Word document"));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(createObjectURL.mock.calls[0][0].type).toBe("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    expect(downloads).toEqual(["discharge_summary_case_one.docx"]);
    expect(s.fetcher.mock.calls.some(([p, init]) => String(p).endsWith("/export?format=docx") && !init?.method)).toBe(true);
    fireEvent.change(screen.getByLabelText("Clinician statement"), { target: { value: revision.clinician_statement } });
    fireEvent.click(button("Propose correction"));
    await screen.findByRole("button", { name: "Accept" });
    expect(document.querySelector("s")?.textContent).toBe(claim.text);
    expect(screen.getByText(`After: ${revision.after}`)).toBeTruthy();
    expect(button("Download Word document").disabled).toBe(true);
    fireEvent.click(button("Reject"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Reject" })).toBeNull());
    expect(s.state.draft?.claims[0].text).toBe(claim.text);
    expect(s.state.revisions[0].status).toBe("rejected");
    fireEvent.change(screen.getByLabelText("Clinician statement"), { target: { value: revision.clinician_statement } });
    fireEvent.click(button("Propose correction")); await screen.findByRole("button", { name: "Accept" });
    fireEvent.click(button("Accept"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Accept" })).toBeNull());
    expect(button("Download Word document").disabled).toBe(true);
    expect(button("Approve draft").disabled).toBe(false);
    expect(document.body.textContent).toContain('Clinician-provided (K2): "Clinician statement."');
    expect(s.fetcher.mock.calls.filter(([p]) => String(p).endsWith("/corrections")).map(([, i]) => JSON.parse(String(i?.body)))).toEqual([
        { claim_id: "C1", statement: revision.clinician_statement }, { claim_id: "C1", statement: revision.clinician_statement },
    ]);
});

test("real chat deltas render before answer, cites open inspector, minimize preserves history, stop cleans reader, errors preserve partial", async () => {
    const s = server(); await ready(s); fireEvent.click(button("Ask about this case"));
    const first = await question(s, "First question?");
    first.send("status", { stage: "retrieving" }); first.send("delta", { text: "Incremental " });
    await screen.findByText("Incremental");
    expect(screen.queryByText("Complete")).toBeNull();
    first.send("delta", { text: "answer." });
    await screen.findByText("Incremental answer.");
    first.send("answer", { intent: "question", answer: "Final supported answer.", cited: ["s1", "unknown"] }); first.send("done", {}); first.close();
    await screen.findByText("Final supported answer.");
    await waitFor(() => expect(button(/^Ask$/).disabled).toBe(true));
    const panel = screen.getByRole("region", { name: "Ask about this case" });
    fireEvent.click(within(panel).getByRole("button", { name: "Inspect [N1:B1]" }));
    expect(within(screen.getByLabelText("Contextual inspector")).getByText(passage.text)).toBeTruthy();
    fireEvent.click(button("Minimize case chat")); expect(screen.queryByText("First question?")).toBeNull();
    fireEvent.click(button("Ask about this case")); expect(screen.getByText("First question?")).toBeTruthy();
    const second = await question(s, "Stop this?"); second.send("delta", { text: "Partial output" });
    await screen.findByText("Partial output"); fireEvent.click(button("Stop answer"));
    await screen.findByText("Stopped. Partial answer.");
    expect(second.canceled).toHaveBeenCalledOnce();
    const third = await question(s, "Failure?"); third.send("delta", { text: "Before failure" }); third.send("error", { detail: "Model unavailable" });
    await screen.findByText("Model unavailable"); expect(screen.getByText("Before failure")).toBeTruthy();
    expect(screen.getByText("Final supported answer.")).toBeTruthy();
    expect(third.canceled).toHaveBeenCalledOnce();
    expect(s.fetcher.mock.calls.some(([p]) => String(p).endsWith("/ask"))).toBe(false);
});

test("pending proposal prevents duplicate calls; switching case aborts it and stale success cannot update next case", async () => {
    const s = server(); await ready(s);
    let release!: (r: Response) => void;
    s.proposalResponse(() => new Promise<Response>(resolve => { release = resolve; }));
    fireEvent.change(screen.getByLabelText("Clinician statement"), { target: { value: "A statement" } });
    const propose = button("Propose correction"); fireEvent.click(propose); fireEvent.click(propose);
    await waitFor(() => expect(s.fetcher.mock.calls.filter(([p]) => String(p).endsWith("/corrections"))).toHaveLength(1));
    expect(button("Proposing…").disabled).toBe(true);
    const call = s.fetcher.mock.calls.find(([p]) => String(p).endsWith("/corrections"))!;
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: "case_two" } });
    expect(call[1]?.signal?.aborted).toBe(true);
    await act(async () => { release(json({ revision, clarification })); });
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
    expect(screen.getByRole("heading", { name: "case_two" })).toBeTruthy();
    expect(button("Ask about this case").disabled).toBe(true);
    expect(document.body.textContent).not.toContain(claim.text);
    expect(document.body.textContent).toContain("Session not started");
});

test("case switch clears history and rejects stale snapshots while canceling an active answer", async () => {
    const s = server(); await ready(s); fireEvent.click(button("Ask about this case"));
    const answer = await question(s, "Old case question"); answer.send("delta", { text: "Old case output" });
    await screen.findByText("Old case output");
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: "case_two" } });
    await waitFor(() => expect(answer.canceled).toHaveBeenCalledOnce());
    expect(screen.queryByText("Old case output")).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Question" })).toBeNull();
    expect(button("Ask about this case").disabled).toBe(true);
});

test("late final snapshot from a canceled load cannot unlock or populate the selected next case", async () => {
    const s = server(); await start(s);
    await screen.findByRole("button", { name: /note.txt/ });
    let release!: (r: Response) => void;
    s.snapshotResponse(() => new Promise<Response>(resolve => { release = resolve; }));
    s.state.draft = structuredClone(draft); s.load.send("done", {}); s.load.close();
    await waitFor(() => expect(release).toBeTypeOf("function"));
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: "case_two" } });
    await act(async () => { release(json(s.state)); });
    expect(button("Ask about this case").disabled).toBe(true);
    expect(button("Results review").disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /note.txt/ })).toBeNull();
    expect(document.body.textContent).not.toContain(claim.text);
});

test("incomplete streams surface without falsely enabling readiness", async () => {
    const s = server(); await start(s); s.state.draft = structuredClone(draft);
    s.load.send("draft", { draft }); s.load.close();
    await screen.findByText("Load stream ended before done. Reload the case to retry.");
    expect(button("Ask about this case").disabled).toBe(true);
});

test("server load errors keep review locked even if a done frame follows", async () => {
    const s = server(); await start(s); s.state.draft = structuredClone(draft);
    s.load.send("error", { detail: "Extraction failed" }); s.load.send("done", {}); s.load.close();
    await screen.findByText("Extraction failed");
    await waitFor(() => expect(button("Load case").disabled).toBe(false));
    expect(button("Ask about this case").disabled).toBe(true);
    expect(button("Results review").disabled).toBe(true);
});

test("final draft uses template order, problem groups, required empty sections, and omits empty optional sections", async () => {
    const s = server();
    const original = s.fetcher.getMockImplementation()!;
    s.fetcher.mockImplementation(async (input, init) => String(input) === "/api/template" ? json({ sections: [
        { section_id: "reason", title: "Reason for admission", optional: false },
        { section_id: "course", title: "Hospital course", optional: false },
        { section_id: "condition", title: "Condition at discharge", optional: false },
        { section_id: "procedures", title: "Procedures", optional: true },
    ] }) : original(input, init));
    await start(s);
    s.state.draft = { ...structuredClone(draft), claims: [
        { ...claim, claim_id: "C2", text: "Problem one claim.", problem: "Pneumonia" },
        { ...claim, claim_id: "C3", text: "Problem two claim.", problem: "Hypertension" },
        { ...claim, section: "reason", text: "Admission claim." },
    ] as typeof claim[] };
    s.load.send("draft", { draft: s.state.draft }); s.load.send("done", {}); s.load.close();
    await waitFor(() => expect(button("Results review").disabled).toBe(false));
    fireEvent.click(button("Results review"));
    const sections = document.querySelectorAll(".cp-review-document .ca-section");
    expect(Array.from(sections).map(section => section.querySelector("h3")?.textContent))
        .toEqual(["Reason for admission", "Hospital course", "Condition at discharge"]);
    const course = within(sections[1] as HTMLElement);
    expect(course.getAllByRole("heading").map(heading => heading.textContent))
        .toEqual(["Hospital course", "Pneumonia", "Hypertension"]);
    expect(sections[2].textContent).toContain("Not documented in the supplied notes.");
    expect(screen.queryByRole("heading", { name: "Procedures" })).toBeNull();
});

test("synthetic warning remains visible and split SSE frames wait for their delimiter", async () => {
    const s = server(); await start(s);
    expect(screen.getByText("Synthetic demonstration · Not for clinical use")).toBeTruthy();
    s.load.raw('event: conflicts_found\ndata: {"conflicts":');
    s.load.raw(`${JSON.stringify(conflicts)} }\n`);
    await act(async () => {});
    expect(screen.queryByRole("heading", { name: "Resolve conflicts" })).toBeNull();
    s.load.raw("\n"); s.load.close();
    await screen.findByRole("heading", { name: "Resolve conflicts" });
    expect(button("Ask about this case").disabled).toBe(true);
});

test("failed correction keeps the selected claim and statement and formats validation errors", async () => {
    const s = server(); await ready(s);
    s.proposalResponse(() => json({ detail: [{ type: "invalid", loc: ["body", "statement"] }] }, 422));
    fireEvent.change(screen.getByLabelText("Clinician statement"), { target: { value: "Keep this statement" } });
    fireEvent.click(button("Propose correction"));
    expect((await screen.findByRole("alert")).textContent).toContain("corrections: 422");
    expect(document.body.textContent).not.toContain("[object Object]");
    expect((screen.getByLabelText("Clinician statement") as HTMLTextAreaElement).value).toBe("Keep this statement");
    expect((screen.getByLabelText("Claim") as HTMLSelectElement).value).toBe("C1");
    expect(button("Propose correction").disabled).toBe(false);
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
});

test("failed resolution submission preserves the checkpoint and editable choices", async () => {
    const s = server();
    const original = s.fetcher.getMockImplementation()!;
    s.fetcher.mockImplementation(async (input, init) => String(input).endsWith("/resolutions")
        ? json({ detail: "Chosen source is invalid" }, 422) : original(input, init));
    await start(s); s.load.send("conflicts_found", { conflicts: [conflicts[0]] }); s.load.close();
    await screen.findByRole("heading", { name: "Resolve conflicts" });
    await waitFor(() => expect(button("Load case").disabled).toBe(false));
    fireEvent.click(screen.getByRole("radio", { name: "Use this value: Value one" }));
    fireEvent.click(button("Review resolutions")); fireEvent.click(button("Start drafting"));
    await screen.findByText("Chosen source is invalid");
    expect(screen.getByRole("heading", { name: "Review resolutions" })).toBeTruthy();
    expect(button("Ask about this case").disabled).toBe(true);
    fireEvent.click(button("Edit"));
    expect((screen.getByRole("radio", { name: "Use this value: Value one" }) as HTMLInputElement).checked).toBe(true);
});

test("failed new session creation cannot reload the previous case session", async () => {
    const s = server(); await ready(s);
    const original = s.fetcher.getMockImplementation()!;
    s.fetcher.mockImplementation(async (input, init) => String(input) === "/api/sessions"
        ? json({ detail: "Session creation failed" }, 500) : original(input, init));
    fireEvent.change(screen.getByLabelText("Case"), { target: { value: "case_two" } });
    fireEvent.click(button("Load case"));
    await screen.findByText("Session creation failed");
    await waitFor(() => expect(button("Load case").disabled).toBe(false));
    fireEvent.click(button("Load case"));
    await waitFor(() => expect(s.fetcher.mock.calls.filter(([p]) => String(p) === "/api/sessions")).toHaveLength(3));
    expect(s.fetcher.mock.calls.filter(([p]) => String(p).endsWith("/load"))).toHaveLength(1);
    expect(button("Ask about this case").disabled).toBe(true);
});
