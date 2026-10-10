/**
 * Specification tests for ticket 06 UI: per-note progress lines (note_extracted / note_failed) render as they stream.
 * fetch is stubbed per route; the load stream stays open while lines are asserted.
 */
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";

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

function stubApi(stream: ReturnType<typeof loadStream>) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${(init?.method ?? "GET").toUpperCase()} ${new URL(String(input), "http://test").pathname}`;
    if (key === "GET /api/cases") return json({ cases: ["case_001"] });
    if (key === "POST /api/sessions") return json({ session_id: "S1" }, 201);
    if (key === "POST /api/sessions/S1/load") return stream.response();
    throw new Error(`unexpected request ${key}`);
  }));
}

const pageText = () => document.body.textContent ?? "";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("renders each note's result as it streams, still Extracting until extraction_done", async () => {
  const stream = loadStream();
  stubApi(stream);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("option", { name: "case_001" });
  await user.click(screen.getByRole("button", { name: /^load$/i }));
  expect(await screen.findByText(/Extracting/)).toBeTruthy();

  stream.send("note_extracted", { document_id: "note_02", event_count: 4, warnings: ["note_02 warning: dropped event"] });
  await waitFor(() => expect(pageText()).toMatch(/note_02: 4 events/));
  expect(pageText()).toMatch(/note_02 warning: dropped event/);
  expect(pageText()).not.toMatch(/note_05/);
  expect(screen.getByText(/Extracting/)).toBeTruthy();

  stream.send("note_failed", { document_id: "note_05", detail: "ExtractionError: boom" });
  await waitFor(() => expect(pageText()).toMatch(/note_05: failed — ExtractionError: boom/));
  expect(pageText().indexOf("note_02: 4 events")).toBeLessThan(pageText().indexOf("note_05: failed")); // arrival order
  expect(screen.getByText(/Extracting/)).toBeTruthy();
  expect(screen.queryByText(/Drafting/)).toBeNull();

  stream.send("extraction_done", { event_count: 4, warnings: ["note_05: failed — ExtractionError: boom"], conflict_count: 1 });
  expect(await screen.findByText(/Drafting/)).toBeTruthy();
  expect(screen.queryByText(/Extracting/)).toBeNull();
  stream.close();
});
