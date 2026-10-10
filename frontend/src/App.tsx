import { useEffect, useRef, useState } from "react";
import { Alert, Button, Popover, Select, Spinner } from "flowbite-react";
import { SseDecoder } from "./sse";

interface Passage { text: string; filename: string; page: number; marker: string }
interface Claim { claim_id: string; section: string; text: string; evidence_span_ids: string[] }
interface Section { section_id: string; title: string; optional: boolean }
interface Loaded { claims: Claim[]; passages: Record<string, Passage> }
interface Entry { name: string; seconds: string; details: string[] }

const WARNING = "SYNTHETIC DEMONSTRATION — NOT FOR CLINICAL USE";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) throw new Error(`${init?.method ?? "GET"} ${path}: ${r.status}`);
  return r.json();
}

function describe(name: string, d: any): string[] {
  const warnings = (d.warnings ?? []).map(String);
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
  const [cases, setCases] = useState<string[]>([]);
  const [caseId, setCaseId] = useState("");
  const [running, setRunning] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Loaded | null>(null);
  const [template, setTemplate] = useState<Section[]>([]);
  const session = useRef("");
  const templateFetch = useRef<Promise<Section[]> | null>(null);

  useEffect(() => {
    api<{ cases: string[] }>("/api/cases")
      .then((r) => { setCases(r.cases); setCaseId(r.cases[0] ?? ""); })
      .catch((e) => setError(String(e.message)));
  }, []);

  async function showDraft(sid: string) {
    templateFetch.current ??= api<{ sections: Section[] }>("/api/template").then((t) => t.sections);
    const [s, sections] = await Promise.all([
      api<{ draft: { claims: Claim[] }; passages: Record<string, Passage> }>(`/api/sessions/${sid}`),
      templateFetch.current,
    ]);
    setTemplate(sections);
    setDraft({ claims: s.draft.claims, passages: s.passages });
  }

  async function run(sid?: string) {
    setRunning(true);
    setError(null);
    setEntries([]);
    setDraft(null);
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
      {draft && template.map((sec) => {
        const claims = draft.claims.filter((c) => c.section === sec.section_id);
        if (!claims.length && sec.optional) return null;
        return (
          <section key={sec.section_id}>
            <h2 className="text-lg font-semibold">{sec.title}</h2>
            {claims.length ? claims.map((c) => (
              <div key={c.claim_id}>
                <span>{c.text}</span>
                {c.evidence_span_ids.map((id) => draft.passages[id] && <Marker key={id} p={draft.passages[id]} />)}
              </div>
            )) : <div className="italic">Not documented in the supplied notes.</div>}
          </section>
        );
      })}
    </main>
  );
}
