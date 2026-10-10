import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Popover, Select, Spinner, Textarea, TextInput } from "flowbite-react";
import { SseDecoder } from "./sse";

interface Passage { text: string; filename: string; page: number; marker: string }
interface Claim {
  claim_id: string; section: string; text: string; evidence_span_ids: string[]
  support_status: string; clinician_clarification_ids: string[]
}
interface Section { section_id: string; title: string; optional: boolean }
interface Discrepancy { discrepancy_id: string; description: string; source_span_ids: string[]; status: string }
interface Revision { revision_id: string; target_claim_id: string; before: string; after: string; clinician_statement: string; status: string }
interface Clarification { clarification_id: string; statement: string }
interface Pending { revision: Revision; clarification: Clarification }
interface Snap {
  case_id: string; passages: Record<string, Passage>; revisions?: Revision[]; clarifications: Clarification[]
  pending: Pending | null
  draft: { claims: Claim[]; discrepancies: Discrepancy[]; status: string; approved_at: string | null; reviewer: string | null }
}
interface Turn { q: string; a?: string; cited: string[]; failed?: string }
interface Entry { name: string; seconds: string; details: string[] }

const WARNING = "SYNTHETIC DEMONSTRATION — NOT FOR CLINICAL USE";
const JSON_POST = { method: "POST", headers: { "Content-Type": "application/json" } };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    const detail = (await r.json().catch(() => null))?.detail; // a 422 detail is a list, not a message
    throw new Error(typeof detail === "string" ? detail : `${init?.method ?? "GET"} ${path}: ${r.status}`);
  }
  return r.json();
}

function describe(name: string, d: any): string[] {
  const warnings = (d.warnings ?? []).map(String);
  if (name === "note_extracted") return [`${d.document_id}: ${d.event_count} events`, ...warnings];
  if (name === "note_failed") return [`${d.document_id}: failed — ${d.detail}`];
  if (name === "extraction_done") return [`${d.event_count} events`, ...warnings];
  if (name === "draft") return [`${d.draft?.claims?.length ?? 0} claims`, ...warnings];
  if (name === "error") return [String(d.detail)];
  return [];
}

function Marker({ p }: { p: Passage }) {
  return (
    <Popover
      trigger="click"
      content={
        <div className="max-w-sm space-y-1 p-3 text-sm">
          <div className="font-semibold">{p.filename}</div>
          <div>Page {p.page} · {p.marker}</div>
          <div>{p.text}</div>
        </div>
      }
    >
      <button type="button" className="ml-1 text-xs text-blue-700 hover:underline">{p.marker}</button>
    </Popover>
  );
}

export default function App() {
  function review(snap: Snap) { // called, not a component: a nested component would remount (and drop focus) on every render
    const { draft, passages, pending } = snap;
    const off = !ready;
    const approved = draft.status === "approved";
    return (
      <>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Discrepancies</h2>
          {draft.discrepancies.length === 0 && <div className="italic">None flagged.</div>}
          {draft.discrepancies.map((d) => (
            <div key={d.discrepancy_id} className="space-y-1 rounded border p-2 text-sm">
              <div><b>{d.discrepancy_id}</b> ({d.status})</div>
              <div>{d.description}</div>
              <div className="flex flex-wrap gap-2">
                {d.source_span_ids.map((id) => passages[id] && (
                  <div key={id} className="flex-1 rounded bg-gray-50 p-2">
                    <span className="font-mono text-xs">{passages[id].marker} {passages[id].filename}</span>
                    <div>{passages[id].text}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Ask about the notes</h2>
          {turns.map((t, i) => (
            <div key={i} className="text-sm">
              <div className="font-semibold">{t.q}</div>
              {t.failed ? <div className="text-red-700">Question failed: {t.failed}</div> : (
                <div>{t.a}{t.cited.map((id) => passages[id] && <Marker key={id} p={passages[id]} />)}</div>
              )}
            </div>
          ))}
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask(); }}>
            <TextInput aria-label="Question" className="flex-1" disabled={off} value={question} onChange={(e) => setQuestion(e.target.value)} />
            <Button type="submit" disabled={off}>Ask</Button>
          </form>
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Correct a claim</h2>
          {pending ? (
            <div className="space-y-1 rounded border p-2 text-sm">
              <div>{pending.revision.target_claim_id}</div>
              <div>Before: <s>{pending.revision.before}</s></div>
              <div>After: <span>{pending.revision.after}</span></div>
              <div>Clinician statement: {pending.revision.clinician_statement}</div>
              <div className="flex gap-2">
                <Button size="xs" disabled={off} onClick={() => act<Snap>(`corrections/${pending.revision.revision_id}/accept`, undefined, apply)}>Accept</Button>
                <Button size="xs" color="light" disabled={off} onClick={() => act<Snap>(`corrections/${pending.revision.revision_id}/reject`, undefined, apply)}>Reject</Button>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <Select aria-label="Claim" disabled={off} value={claimId} onChange={(e) => setClaimId(e.target.value)}>
                {draft.claims.map((c) => <option key={c.claim_id} value={c.claim_id}>{c.claim_id}</option>)}
              </Select>
              <TextInput aria-label="Clinician statement" disabled={off} value={statement} onChange={(e) => setStatement(e.target.value)} />
              <Textarea aria-label="Corrected text" disabled={off} ref={area} />
              <Button disabled={off}
                onClick={() => act<Pending>("corrections", { claim_id: claimId, after: area.current!.value, statement }, (p) => setSnap({ ...snap, pending: p }))}>
                Propose correction
              </Button>
            </div>
          )}
          {snap.revisions?.map((r) => <div key={r.revision_id} className="text-sm">{r.revision_id} → {r.target_claim_id}: {r.status}</div>)}
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Approve and export</h2>
          {pending && <div className="text-sm">Accept or reject the pending correction before approving.</div>}
          <div className="flex gap-2">
            <TextInput aria-label="Reviewer" className="flex-1" disabled={off || approved} value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            <Button disabled={off || approved || !!pending} onClick={() => act<Snap>("approve", { reviewer }, apply)}>Approve</Button>
            <Button color="light" disabled={off || !approved} onClick={exportMarkdown}>Export Markdown</Button>
          </div>
          {fail && <div className="text-sm text-red-700">{fail}</div>}
        </section>
      </>
    );
  }

  const [cases, setCases] = useState<string[]>([]);
  const [caseId, setCaseId] = useState("");
  const [running, setRunning] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [snap, setSnap] = useState<Snap | null>(null);
  const [template, setTemplate] = useState<Section[]>([]);
  const [ready, setReady] = useState(false); // true only after `done` of the current load: the editing lock
  const [fail, setFail] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [claimId, setClaimId] = useState("");
  const area = useRef<HTMLTextAreaElement>(null); // uncontrolled: the claim text is its value, not a text node
  const [statement, setStatement] = useState("");
  const [reviewer, setReviewer] = useState("Simulated resident (demo)");
  const session = useRef("");
  const templateFetch = useRef<Promise<Section[]> | null>(null);

  useEffect(() => {
    api<{ cases: string[] }>("/api/cases")
      .then((r) => { setCases(r.cases); setCaseId(r.cases[0] ?? ""); })
      .catch((e) => setError(String(e.message)));
  }, []);

  function apply(s: Snap) {
    const first = s.draft.claims.find((c) => c.support_status === "needs_review") ?? s.draft.claims[0];
    setSnap(s);
    setClaimId(first?.claim_id ?? "");
    setStatement("");
  }

  useEffect(() => {
    if (area.current) area.current.value = snap?.draft.claims.find((c) => c.claim_id === claimId)?.text ?? "";
  }, [claimId, snap]);

  async function showDraft(sid: string) {
    templateFetch.current ??= api<{ sections: Section[] }>("/api/template").then((t) => t.sections);
    const [s, sections] = await Promise.all([api<Snap>(`/api/sessions/${sid}`), templateFetch.current]);
    setTemplate(sections);
    apply(s);
  }

  /** Runs a review operation; `then` gets the result, a failure shows under the controls. */
  async function act<T>(path: string, body: unknown, then: (r: T) => void) {
    setFail(null);
    try {
      then(await api<T>(`/api/sessions/${session.current}/${path}`, { ...JSON_POST, body: body === undefined ? undefined : JSON.stringify(body) }));
    } catch (e) {
      setFail(String((e as Error).message));
    }
  }

  async function ask() {
    const q = question.trim();
    setQuestion("");
    try {
      const r = await api<{ answer: string; cited: string[] }>(`/api/sessions/${session.current}/ask`, { ...JSON_POST, body: JSON.stringify({ question: q }) });
      setTurns((t) => [...t, { q, a: r.answer, cited: r.cited }]);
    } catch (e) {
      setTurns((t) => [...t, { q, cited: [], failed: String((e as Error).message) }]);
    }
  }

  async function exportMarkdown() {
    setFail(null);
    try {
      const r = await fetch(`/api/sessions/${session.current}/export`);
      if (!r.ok) throw new Error(`export failed: ${r.status}`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await r.blob());
      a.download = `discharge_summary_${snap!.case_id}.md`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setFail(String((e as Error).message));
    }
  }

  async function run(sid?: string) {
    setRunning(true);
    setError(null);
    setEntries([]);
    setSnap(null);
    setReady(false);
    setTurns([]);
    setFail(null);
    const t0 = Date.now();
    try {
      if (!sid) {
        session.current = ""; // a failed create must not leave Retry pointing at the previous case
        sid = (await api<{ session_id: string }>("/api/sessions", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId }),
        })).session_id;
      }
      session.current = sid;
      const r = await fetch(`/api/sessions/${sid}/load`, { method: "POST" });
      if (!r.ok || !r.body) throw new Error(`load failed: ${r.status}`);
      const reader = r.body.getReader();
      const text = new TextDecoder();
      const sse = new SseDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const f of sse.push(text.decode(value, { stream: true }))) {
          const d = f.data ? JSON.parse(f.data) : {};
          setEntries((es) => [...es, { name: f.name, seconds: ((Date.now() - t0) / 1000).toFixed(1), details: describe(f.name, d) }]);
          if (f.name === "error") setError(String(d.detail));
          if (f.name === "done") setReady(true);
          if (f.name === "draft") showDraft(sid).catch((e) => setError(String(e.message)));
        }
      }
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setRunning(false);
    }
  }

  const step = entries.some((e) => e.name === "draft") ? null : entries.some((e) => e.name === "extraction_done") ? "Drafting" : "Extracting";

  return (
    <main className="mx-auto max-w-3xl space-y-4 p-4">
      <div className="bg-red-700 p-2 text-center font-bold text-white">{WARNING}</div>
      <div className="flex gap-2">
        <Select aria-label="Case" value={caseId} disabled={running} onChange={(e) => setCaseId(e.target.value)}>
          {cases.map((c) => <option key={c} value={c}>{c}</option>)}
        </Select>
        <Button disabled={running || !caseId} onClick={() => run()}>Load</Button>
      </div>
      {error && (
        <Alert color="failure">
          <div className="flex items-center justify-between gap-2">
            <span>{error}</span>
            <Button size="xs" disabled={running || !session.current} onClick={() => run(session.current)}>Retry</Button>
          </div>
        </Alert>
      )}
      {running && step && <div className="flex items-center gap-2"><Spinner size="sm" /><span>{step}…</span></div>}
      <ol className="space-y-1 text-sm">
        {entries.map((e, i) => (
          <li key={i} className="flex flex-wrap gap-2">
            <span className="font-mono font-semibold">{e.name}</span>
            <span className="text-gray-500">{e.seconds}s</span>
            {e.details.map((d, j) => <span key={j}>{d}</span>)}
          </li>
        ))}
      </ol>
      {snap && (
        <div className="font-semibold">
          {snap.draft.status === "approved"
            ? `Approved by ${snap.draft.reviewer} at ${(snap.draft.approved_at ?? "").replace("T", " ").slice(0, 16)}`
            : "Draft — pending review"}
        </div>
      )}
      {snap && template.map((sec) => {
        const claims = snap.draft.claims.filter((c) => c.section === sec.section_id);
        if (!claims.length && sec.optional) return null;
        return (
          <section key={sec.section_id}>
            <h2 className="text-lg font-semibold">{sec.title}</h2>
            {claims.length ? claims.map((c) => (
              <div key={c.claim_id}>
                <span>{c.text}</span>
                {c.evidence_span_ids.map((id) => snap.passages[id] && <Marker key={id} p={snap.passages[id]} />)}
                {c.support_status === "needs_review" && (c.clinician_clarification_ids.length
                  ? <Badge color="success" className="ml-2 inline-flex">clarified by clinician — pending approval</Badge>
                  : <Badge color="warning" className="ml-2 inline-flex">needs review</Badge>)}
                {c.clinician_clarification_ids.map((id) => {
                  const k = snap.clarifications.find((x) => x.clarification_id === id);
                  return k && <div key={id} className="ml-4 text-sm italic">Clinician-provided ({id}): "{k.statement}"</div>;
                })}
              </div>
            )) : <div className="italic">Not documented in the supplied notes.</div>}
          </section>
        );
      })}
      {snap && review(snap)}
    </main>
  );
}
