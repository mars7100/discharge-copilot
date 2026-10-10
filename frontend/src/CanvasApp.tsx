import { useEffect, useRef, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { SseDecoder } from "./sse";
import "./CanvasBase.css";
import "./CanvasApp.css";

interface Passage { document_id: string; filename: string; page: number; marker: string; text: string }
interface DocumentInfo { document_id: string; filename: string; date: string | null; hospital_day: number | null; type: string | null; author_role: string | null }
interface Claim { claim_id?: string; section: string; text: string; problem?: string | null; evidence_span_ids: string[]; support_status?: string; clinician_clarification_ids?: string[] }
interface Revision { revision_id: string; target_claim_id: string; before: string; after: string; clinician_statement: string; status: string }
interface Clarification { clarification_id: string; statement: string; status?: string }
interface Pending { revision: Revision; clarification: Clarification }
interface Conflict { conflict_id: string; description: string; quotes: (Passage & { span_id: string; quote: string; date: string | null; hospital_day: number | null })[] }
interface Resolution { conflict_id: string; text: string; chosen_span_id?: string | null }
interface Snapshot {
    session_id: string; case_id: string; documents: DocumentInfo[]; passages: Record<string, Passage>;
    events: { event_id: string; statement: string; category: string; evidence: { span_id: string; quote: string }[] }[];
    draft: { claims: Claim[]; discrepancies: { discrepancy_id: string; description: string; status: string; source_span_ids: string[] }[]; status: string; reviewer: string | null; approved_at: string | null } | null;
    revisions: Revision[]; clarifications: Clarification[]; pending: Pending | null; resolutions?: Resolution[]; missing_notes?: string[];
}
interface Section { section_id: string; title: string; optional: boolean }
interface Pick { span: string | null; text: string }
interface Activity { name: string; data: Record<string, unknown> }
interface Turn { question: string; answer: string; cited: string[]; stage: string; stopped?: boolean; error?: string; complete?: boolean }
type Work = "queued" | "working" | "done" | "attention";
const POST = { method: "POST", headers: { "Content-Type": "application/json" } };

/** Fetch a response and preserve the server's error detail. */
async function response(path: string, init?: RequestInit): Promise<Response> {
    const result = await fetch(path, init);
    if (!result.ok) {
        const detail: unknown = (await result.json().catch(() => ({}))).detail;
        throw new Error(typeof detail === "string" ? detail : `${init?.method ?? "GET"} ${path}: ${result.status}`);
    }
    return result;
}

/** Read a JSON API response. */
async function json<T>(path: string, init?: RequestInit): Promise<T> {
    return (await response(path, init)).json();
}

/** Render the approved primary button animation. */
function Action({ children, disabled, onClick, type = "button" }: { children: ReactNode; disabled?: boolean; onClick?: () => void; type?: "button" | "submit" }): ReactElement {
    const arrow = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M4 12h16m-6-6 6 6-6 6" /></svg>;
    return <button type={type} className="cp-action" disabled={disabled} onClick={onClick}><span className="cp-arrow-in">{arrow}</span><span className="cp-action-text">{children}</span><span className="cp-arrow-out">{arrow}</span></button>;
}

/** Show six breathing layers only when real work is in flight. */
function Status({ status }: { status: Work }): ReactElement {
    return <span className={`cp-status ${status}`}><span className={`cp-status-mark ${status === "working" ? "breathing" : ""}`} aria-hidden="true">{status === "working" ? Array.from({ length: 6 }, (_, i) => <i key={i} style={{ animationDelay: `${i * .3}s` }} />) : status === "done" ? "✓" : status === "attention" ? "!" : "○"}</span>{{ queued: "Queued", working: "Working", done: "Complete", attention: "Needs attention" }[status]}</span>;
}

/** Orchestrate the session API in the blue canvas workspace. */
export default function CanvasApp(): ReactElement {
    const [cases, setCases] = useState<string[]>([]);
    const [caseId, setCaseId] = useState("");
    const [sid, setSid] = useState("");
    const [snap, setSnap] = useState<Snapshot | null>(null);
    const [template, setTemplate] = useState<Section[]>([]);
    const [activity, setActivity] = useState<Activity[]>([]);
    const [early, setEarly] = useState<Record<string, Claim[]>>({});
    const [conflicts, setConflicts] = useState<Conflict[]>([]);
    const [picks, setPicks] = useState<Record<string, Pick>>({});
    const [checkpoint, setCheckpoint] = useState(false);
    const [running, setRunning] = useState(false);
    const [ready, setReady] = useState(false);
    const [pendingOperation, setPendingOperation] = useState("");
    const [error, setError] = useState("");
    const [selected, setSelected] = useState("compare");
    const [sourcesOpen, setSourcesOpen] = useState(false);
    const [review, setReview] = useState(false);
    const [claimId, setClaimId] = useState("");
    const [statement, setStatement] = useState("");
    const [reviewer, setReviewer] = useState("");
    const [chatOpen, setChatOpen] = useState(false);
    const [question, setQuestion] = useState("");
    const [turns, setTurns] = useState<Turn[]>([]);
    const epoch = useRef(0);
    const lock = useRef(false);
    const controllers = useRef(new Set<AbortController>());
    const loadController = useRef<AbortController | null>(null);
    const askController = useRef<AbortController | null>(null);
    const inspector = useRef<HTMLElement | null>(null);
    const chatViewport = useRef<HTMLDivElement | null>(null);
    const snapshotQueue = useRef<Promise<void>>(Promise.resolve());
    const metadataReady = useRef(false);

    useEffect(() => {
        const controller = new AbortController();
        Promise.all([json<{ cases: string[] }>("/api/cases", { signal: controller.signal }), json<{ sections: Section[] }>("/api/template", { signal: controller.signal })])
            .then(([list, t]) => { setCases(list.cases); setCaseId(list.cases[0] ?? ""); setTemplate(t.sections); })
            .catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
        return () => { controller.abort(); epoch.current++; controllers.current.forEach(c => c.abort()); };
    }, []);

    useEffect(() => {
        const viewport = window.visualViewport;
        if (!chatOpen || !viewport) return;
        /** Keep the composer within the visible area above a mobile keyboard. */
        const position = (): void => {
            chatViewport.current?.style.setProperty("--ca-keyboard-offset", `${Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)}px`);
            chatViewport.current?.style.setProperty("--ca-visible-height", `${viewport.height}px`);
        };
        position();
        viewport.addEventListener("resize", position);
        viewport.addEventListener("scroll", position);
        return () => {
            viewport.removeEventListener("resize", position);
            viewport.removeEventListener("scroll", position);
            chatViewport.current?.style.removeProperty("--ca-keyboard-offset");
            chatViewport.current?.style.removeProperty("--ca-visible-height");
        };
    }, [chatOpen]);

    /** Reset the entire case view and invalidate every older async continuation. */
    function reset(): number {
        const version = ++epoch.current;
        controllers.current.forEach(c => c.abort()); controllers.current.clear();
        lock.current = false; snapshotQueue.current = Promise.resolve(); metadataReady.current = false;
        setSid(""); setSnap(null); setActivity([]); setEarly({}); setConflicts([]); setPicks({});
        setCheckpoint(false); setRunning(false); setReady(false); setPendingOperation(""); setError("");
        setSelected("compare"); setReview(false); setClaimId(""); setStatement(""); setReviewer("");
        setSourcesOpen(false);
        setChatOpen(false); setQuestion(""); setTurns([]);
        return version;
    }

    /** Track a request controller for case changes and unmount. */
    function controller(): AbortController {
        const c = new AbortController(); controllers.current.add(c); return c;
    }

    /** Serialize snapshots so an earlier fetch cannot overwrite a later draft. */
    function refresh(sessionId: string, version: number, signal: AbortSignal): Promise<void> {
        const next = snapshotQueue.current.catch(() => {}).then(async () => {
            if (epoch.current !== version || signal.aborted) return;
            const s = await json<Snapshot>(`/api/sessions/${sessionId}`, { signal });
            if (epoch.current !== version || signal.aborted) return;
            metadataReady.current = s.documents.length > 0;
            setSnap(s);
            setClaimId(id => s.draft?.claims.some(c => c.claim_id === id) ? id : s.draft?.claims.find(c => c.support_status === "needs_review")?.claim_id ?? s.draft?.claims[0]?.claim_id ?? "");
        });
        snapshotQueue.current = next;
        return next;
    }

    /** Consume actual SSE frames; cancel and release the reader on every exit. */
    async function stream(result: Response, signal: AbortSignal, receive: (name: string, data: Record<string, any>) => Promise<void> | void): Promise<void> {
        if (!result.body) throw new Error("The server returned no stream.");
        const reader = result.body.getReader();
        const decoder = new TextDecoder(); const sse = new SseDecoder();
        const cancel = (): void => { void reader.cancel().catch(() => {}); };
        signal.addEventListener("abort", cancel);
        try {
            while (!signal.aborted) {
                const chunk = await reader.read();
                if (signal.aborted) break;
                for (const frame of sse.push(chunk.done ? decoder.decode() : decoder.decode(chunk.value, { stream: true }))) {
                    if (signal.aborted) break;
                    await receive(frame.name, frame.data ? JSON.parse(frame.data) : {});
                }
                if (chunk.done) break;
            }
        } finally {
            signal.removeEventListener("abort", cancel);
            await reader.cancel().catch(() => {}); reader.releaseLock();
        }
    }

    /** Read load/resume events and unlock only after done and its final snapshot. */
    async function consumeLoad(result: Response, sessionId: string, version: number, c: AbortController): Promise<void> {
        let done = false; let paused = false; let failed = false;
        await stream(result, c.signal, async (name, data) => {
            if (epoch.current !== version) return;
            setActivity(a => [...a, { name, data }]);
            if (name === "error") { failed = true; setReady(false); setError(String(data.detail)); }
            if (name === "conflicts_found") { paused = true; setConflicts(data.conflicts); setSelected("compare"); setPicks({}); setCheckpoint(false); }
            if (name === "section_drafted") setEarly(e => ({ ...e, [data.section_id]: [...(data.problem ? e[data.section_id] ?? [] : []), ...data.claims.map((claim: Claim) => ({ ...claim, problem: data.problem }))] }));
            if (["note_extracted", "note_failed", "extraction_done", "conflicts_found", "section_drafted", "section_omitted", "draft", "done"].includes(name)) {
                const fetched = refresh(sessionId, version, c.signal);
                if (name === "done") {
                    await fetched;
                    if (epoch.current === version && !c.signal.aborted && !failed) { done = true; setReady(true); }
                } else void fetched.catch((e: Error) => { if (epoch.current === version && !c.signal.aborted) setError(e.message); });
            }
        });
        if (!c.signal.aborted && !done && !paused && !failed) throw new Error("Load stream ended before done. Reload the case to retry.");
    }

    /** Start a fresh server session and fetch ingested metadata while work runs. */
    async function load(): Promise<void> {
        if (lock.current || running || !caseId) return;
        const version = reset(); const c = controller(); loadController.current = c;
        lock.current = true; setRunning(true); setPendingOperation("Loading");
        let poll: ReturnType<typeof setInterval> | undefined;
        try {
            const created = await json<{ session_id: string }>("/api/sessions", { ...POST, body: JSON.stringify({ case_id: caseId }), signal: c.signal });
            if (epoch.current !== version || c.signal.aborted) return;
            setSid(created.session_id);
            const request = response(`/api/sessions/${created.session_id}/load`, { method: "POST", signal: c.signal });
            const fetchMetadata = (): void => { void refresh(created.session_id, version, c.signal).catch((e: Error) => { if (epoch.current === version && !c.signal.aborted) setError(e.message); }); };
            fetchMetadata(); poll = setInterval(() => { if (metadataReady.current) clearInterval(poll); else fetchMetadata(); }, 1000);
            await consumeLoad(await request, created.session_id, version, c);
        } catch (e) { if (epoch.current === version && !c.signal.aborted) setError((e as Error).message); }
        finally {
            clearInterval(poll); c.abort(); controllers.current.delete(c);
            if (epoch.current === version) { lock.current = false; setRunning(false); setPendingOperation(""); }
        }
    }

    /** Resume only after the clinician has reviewed the exact stored resolutions. */
    async function startDrafting(): Promise<void> {
        if (lock.current || !checkpoint || !validPicks) return;
        const version = epoch.current; const c = controller(); loadController.current = c;
        lock.current = true; setPendingOperation("Starting drafting"); setError("");
        try {
            const resolutions = conflicts.map(conflict => ({ conflict_id: conflict.conflict_id, chosen_span_id: picks[conflict.conflict_id].span, clarification: picks[conflict.conflict_id].span ? null : picks[conflict.conflict_id].text.trim() }));
            const result = await response(`/api/sessions/${sid}/resolutions`, { ...POST, body: JSON.stringify({ resolutions }), signal: c.signal });
            if (epoch.current !== version || c.signal.aborted) { await result.body?.cancel(); return; }
            setConflicts([]); setCheckpoint(false); setRunning(true); setReady(false); setSelected("writer");
            await consumeLoad(result, sid, version, c);
        } catch (e) { if (epoch.current === version && !c.signal.aborted) setError((e as Error).message); }
        finally { c.abort(); controllers.current.delete(c); if (epoch.current === version) { lock.current = false; setPendingOperation(""); setRunning(false); } }
    }

    /** Gate every review mutation, including export, against duplicate and stale calls. */
    async function mutate(path: string, body?: unknown): Promise<void> {
        if (lock.current || !ready || !snap?.draft) return;
        const version = epoch.current; const c = controller();
        lock.current = true; setPendingOperation(path === "corrections" ? "Proposing…" : "Saving…"); setError("");
        try {
            const result = await response(`/api/sessions/${sid}/${path}${path === "export" ? "?format=docx" : ""}`, { ...(path === "export" ? {} : POST), body: body === undefined ? undefined : JSON.stringify(body), signal: c.signal });
            if (path === "export") {
                const blob = await result.blob();
                if (epoch.current !== version || c.signal.aborted) return;
                const url = URL.createObjectURL(blob); const link = document.createElement("a");
                link.href = url; link.download = `discharge_summary_${snap.case_id}.docx`; link.click(); URL.revokeObjectURL(url);
            } else {
                const data = await result.json();
                if (epoch.current !== version || c.signal.aborted) return;
                if (path === "corrections") setSnap(s => s && ({ ...s, pending: data as Pending }));
                else { setSnap(data as Snapshot); setStatement(""); }
            }
        } catch (e) { if (epoch.current === version && !c.signal.aborted) setError((e as Error).message); }
        finally { controllers.current.delete(c); if (epoch.current === version) { lock.current = false; setPendingOperation(""); } }
    }

    /** Stream a case answer without manufacturing deltas or allowing cross-case updates. */
    async function ask(): Promise<void> {
        if (lock.current || !ready || !snap?.draft || !question.trim()) return;
        const version = epoch.current; const c = controller(); askController.current = c;
        const text = question.trim(); const index = turns.length;
        lock.current = true; setPendingOperation("Answering"); setQuestion("");
        setTurns(t => [...t, { question: text, answer: "", cited: [], stage: "Connecting" }]);
        const update = (patch: Partial<Turn>): void => { if (epoch.current === version) setTurns(t => t.map((turn, i) => i === index ? { ...turn, ...patch } : turn)); };
        let done = false; let answered = false;
        try {
            const result = await response(`/api/sessions/${sid}/ask/stream`, { ...POST, body: JSON.stringify({ question: text }), signal: c.signal });
            if (epoch.current !== version || c.signal.aborted) { await result.body?.cancel(); return; }
            await stream(result, c.signal, (name, data) => {
                if (epoch.current !== version || c.signal.aborted) return;
                if (name === "status") update({ stage: data.stage });
                if (name === "delta") setTurns(t => t.map((turn, i) => i === index ? { ...turn, answer: turn.answer + data.text } : turn));
                if (name === "answer") { answered = true; update({ answer: data.answer, cited: data.cited.filter((id: string) => !!snap.passages[id]) }); }
                if (name === "error") throw new Error(String(data.detail));
                if (name === "done") { if (!answered) throw new Error("Answer stream finished without an answer."); done = true; update({ complete: true, stage: "Complete" }); }
            });
            if (!done && !c.signal.aborted) throw new Error("Answer stream ended before done.");
        } catch (e) { if (!c.signal.aborted) update({ error: (e as Error).message, stage: "Failed" }); }
        finally {
            if (c.signal.aborted) update({ stopped: true, stage: "Stopped" });
            controllers.current.delete(c);
            if (epoch.current === version) { lock.current = false; setPendingOperation(""); askController.current = null; }
        }
    }

    /** Open a contextual source and move keyboard focus to its inspector. */
    function evidence(id: string): void {
        setSelected(`source:${id}`);
        inspector.current?.focus();
    }

    /** Render citations only for evidence present in this session. */
    function citations(ids: string[]): ReactNode {
        return ids.map(id => snap?.passages[id] && <button key={id} className="ca-citation" onClick={() => evidence(id)} aria-label={`Inspect ${snap.passages[id].marker}`}>{snap.passages[id].marker}</button>);
    }

    /** Render live or final claims with their actual evidence and clinician provenance. */
    function draftContents(): ReactNode {
        const claims = snap?.draft?.claims;
        return template.map(section => {
            const rows = claims ? claims.filter(c => c.section === section.section_id) : early[section.section_id];
            if (!rows || (!rows.length && section.optional)) return null;
            return <section className="ca-section" key={section.section_id}><h3>{section.title}</h3>{rows.length ? rows.map((claim, i) => <div key={claim.claim_id ?? i}>
                {claim.problem && claim.problem !== rows[i - 1]?.problem && <h4>{claim.problem}</h4>}
                <p>{claim.text} {citations(claim.evidence_span_ids)}</p>
                {claim.support_status && <small>{claim.support_status}{claim.clinician_clarification_ids?.length ? " · clinician-provided" : ""}</small>}
                {claim.clinician_clarification_ids?.map(id => { const text = snap?.clarifications.find(c => c.clarification_id === id)?.statement ?? snap?.resolutions?.find(r => r.conflict_id === id)?.text; return text && <p className="cp-callout" key={id}>Clinician-provided ({id}): "{text}"</p>; })}
            </div>) : <p>Not documented in the supplied notes.</p>}</section>;
        });
    }

    const validPicks = conflicts.length > 0 && conflicts.every(c => { const p = picks[c.conflict_id]; return p && (p.span ? c.quotes.some(q => q.span_id === p.span) : !!p.text.trim()); });
    const off = !ready || !!pendingOperation;
    const approved = snap?.draft?.status === "approved";
    const source = selected.startsWith("source:") ? snap?.passages[selected.slice(7)] : null;
    const documentInfo = snap?.documents.find(d => selected === d.document_id);
    const retrying = activity.some((a, i) => a.name === "note_retrying" && !activity.slice(i + 1).some(b => b.data.document_id === a.data.document_id && ["note_extracted", "note_failed"].includes(b.name)));
    const extracted = activity.some(a => a.name === "extraction_done");
    const notes = (snap?.documents ?? []).map(document => {
        const latest = [...activity].reverse().find(a => a.data.document_id === document.document_id && ["note_extracted", "note_failed", "note_retrying"].includes(a.name));
        const status: Work = latest?.name === "note_extracted" ? "done" : latest?.name === "note_failed" || snap?.missing_notes?.includes(document.document_id) ? "attention" : running && (!extracted || latest?.name === "note_retrying") ? "working" : "queued";
        return { document, latest, status };
    });
    const completedNotes = notes.filter(n => n.status === "done").length;
    const failedNotes = notes.filter(n => n.status === "attention").length;
    const retryingNotes = notes.filter(n => n.latest?.name === "note_retrying").length;
    const readingNotes = notes.some(n => n.status === "working");
    const composing = extracted && !conflicts.length && running;
    const state = conflicts.length ? "Waiting for conflict resolution" : running ? retrying ? "Retrying failed notes" : composing ? "Drafting" : "Reading source notes" : ready ? "Draft ready for review" : error ? "Needs attention" : "Select and load a case";

    return <div ref={chatViewport} className="cp-app ca-app">
        <header className="cp-header"><a className="cp-brand" href="/"><span className="cp-brand-mark">↔</span>discharge<span>copilot</span></a><span className="cp-demo">Connected case workspace</span></header>
        <main>
            <section className="cp-case"><div><span className="cp-eyebrow">DISCHARGE WORKSPACE</span><h1>{caseId || "Select a case"}</h1><p>Session {sid || "not started"}</p></div><div className="ca-case-controls"><label>Case<select aria-label="Case" value={caseId} onChange={e => { reset(); setCaseId(e.target.value); }}>{cases.map(id => <option key={id}>{id}</option>)}</select></label><Action disabled={!caseId || running || !!pendingOperation} onClick={() => void load()}>Load case</Action></div></section>
            <div className="cp-toolbar"><div className="cp-tabs"><button className={!review ? "active" : ""} onClick={() => setReview(false)}>Agent canvas</button><button className={review ? "active" : ""} disabled={!ready || !snap?.draft} onClick={() => setReview(true)}>Results review</button></div><div className="cp-controls"><span role="status">{state}</span>{running && <button onClick={() => { loadController.current?.abort(); setReady(false); setError("Stopped watching the load. Server work continues; reload the case to start again."); }}>Stop watching load</button>}</div></div>
            {error && <div role="alert" className="ca-error">{error}</div>}
            {ready && !!snap?.missing_notes?.length && <div role="alert" className="cp-callout">Draft is missing notes: {snap.missing_notes.join(", ")}</div>}
            {checkpoint ? <section className="cp-review-document" aria-label="Resolution checkpoint"><span className="cp-eyebrow">BEFORE DRAFTING</span><h2>Review resolutions</h2>{conflicts.map(c => { const p = picks[c.conflict_id]; const q = c.quotes.find(q => q.span_id === p.span); return <div className="ca-section" key={c.conflict_id}><h3>{c.conflict_id} · {c.description}</h3><p>Chosen: {q ? `${q.marker} "${q.quote}"` : `Clarification: ${p.text.trim()}`}</p><p>Stored as: {q ? `${c.description}: ${q.quote}` : p.text.trim()}</p></div>; })}<div className="cp-review-actions"><button className="cp-secondary" disabled={!!pendingOperation} onClick={() => setCheckpoint(false)}>Edit</button><Action disabled={!!pendingOperation || !validPicks} onClick={() => void startDrafting()}>Start drafting</Action></div></section> : <>
                {!review ? <section className="cp-canvas" aria-label="Connected agent canvas"><div className="cp-canvas-heading"><div><h2>Source notes. One discharge draft.</h2><p>Select a card to inspect real evidence and output.</p></div><span className="cp-live">{ready ? "RUN COMPLETE" : running ? "CONNECTED" : "WORKSPACE"}</span></div><div className="cp-stage-headings"><span>01 <strong>Read in parallel</strong></span><span>02 <strong>Reconcile</strong></span><span>03 <strong>Compose</strong></span></div><div className="cp-graph">
                    <svg className={`cp-wires ${extracted ? "connected" : ""}`} viewBox="0 0 1000 640" preserveAspectRatio="none" aria-hidden="true"><path d="M280 320 H380 M660 320 H730" /><circle cx="380" cy="320" r="5" /><circle cx="730" cy="320" r="5" /></svg>
                    <div className={`cp-note-column ca-source-folder ${sourcesOpen ? "open" : ""}`}>
                        <button type="button" className="ca-folder-toggle" aria-expanded={sourcesOpen} aria-controls="ca-source-notes" onClick={() => setSourcesOpen(o => !o)}>
                            <span className="ca-folder-art" aria-hidden="true"><span className="ca-folder-back" />{notes.slice(0, 5).map(({ document: d }, i) => <span className={`ca-folder-file ca-folder-file-${i}`} key={d.document_id}><span>{d.document_id}</span><i /><i /><i /></span>)}<span className="ca-folder-front"><span>{notes.length} notes</span></span><span className="ca-folder-counter">{notes.length}</span></span>
                            <strong>Source notes</strong><span>{completedNotes} of {notes.length} complete</span>
                            <progress aria-label="Source extraction progress" value={completedNotes} max={notes.length || 1} />
                            <Status status={readingNotes ? "working" : failedNotes || retryingNotes ? "attention" : notes.length && completedNotes === notes.length ? "done" : "queued"} />
                            <span className="ca-folder-hint">{sourcesOpen ? "Close source notes" : "Open source notes"}</span>
                        </button>
                        {!!(failedNotes || retryingNotes) && <p className="ca-folder-warning" role="status">{failedNotes} failed · {retryingNotes} retrying{!running && retryingNotes ? " · Processing stopped" : ""}</p>}
                        {!notes.length && <p className="ca-folder-empty">{running ? "Waiting for document metadata from ingestion." : "Load a case to see its supplied documents."}</p>}
                        <div id="ca-source-notes" className="ca-source-list" role="region" aria-label="Source note cards" hidden={!sourcesOpen}>{notes.map(({ document: d, latest, status }) => <button className={`cp-node cp-note ${selected === d.document_id ? "selected" : ""}`} aria-pressed={selected === d.document_id} key={d.document_id} onClick={() => { setSelected(d.document_id); inspector.current?.focus(); }}><div className="cp-node-top"><span className="cp-node-index">{d.document_id}</span><Status status={status} /></div><h3>{d.filename}</h3><p>{[d.type, d.author_role, d.date, d.hospital_day != null ? `Hospital day ${d.hospital_day}` : null].filter(Boolean).join(" · ")}</p><div className="cp-output"><span>Output</span><strong>{latest?.name === "note_extracted" ? `${latest.data.event_count} events extracted` : latest?.name === "note_failed" ? String(latest.data.detail) : latest?.name === "note_retrying" ? "Retrying extraction" : status === "attention" ? "Missing from draft" : status === "working" ? "Load in progress; individual start unknown" : "Awaiting extraction"}</strong></div><div className="cp-node-foot">Inspect source and events</div></button>)}</div>
                    </div>
                    <button className={`cp-node cp-compare ${selected === "compare" ? "selected" : ""}`} onClick={() => setSelected("compare")} aria-pressed={selected === "compare"}><div className="cp-node-top"><Status status={conflicts.length ? "attention" : extracted ? "done" : "queued"} /></div><span className="cp-eyebrow">COMPARISON AGENT</span><h3>Reconcile the notes.</h3><p>Inspect discrepancies and clinician resolutions.</p><div className="cp-output"><strong>{conflicts.length ? `${conflicts.length} decisions required` : extracted ? "Extraction complete" : "Waiting for extracted facts"}</strong></div></button>
                    <button className={`cp-node cp-writer ${selected === "writer" ? "selected" : ""}`} onClick={() => setSelected("writer")} aria-pressed={selected === "writer"}><div className="cp-node-top"><Status status={ready ? "done" : composing ? "working" : "queued"} /></div><span className="cp-eyebrow">DISCHARGE WRITER</span><h3>Compose the draft.</h3><p>Evidence-linked sections appear as they arrive.</p><div className="cp-output"><strong>{ready ? "Draft ready" : snap?.draft ? "Draft received; awaiting completion and retries" : composing ? "Drafting from resolved facts" : "Waiting for reconciliation"}</strong></div></button>
                </div><footer className="cp-canvas-footer">Evidence follows every connection. Human review required.</footer></section> : <section className="cp-review-document"><div className="cp-review-title"><div><span className="cp-eyebrow">RESULTS / DISCHARGE DRAFT</span><h2>Review before release.</h2></div><span className={`cp-approval ${approved ? "approved" : ""}`}>{approved ? `Approved by ${snap?.draft?.reviewer} at ${snap?.draft?.approved_at}` : "Awaiting approval"}</span></div>{draftContents()}
                    <h3>Correct a claim</h3>{snap?.pending ? <div className="cp-callout"><p>Before: <s>{snap.pending.revision.before}</s></p><p>After: {snap.pending.revision.after}</p><p>Clinician statement: {snap.pending.revision.clinician_statement}</p><div className="cp-review-actions"><Action disabled={off} onClick={() => void mutate(`corrections/${snap.pending!.revision.revision_id}/accept`)}>Accept</Action><button className="cp-secondary" disabled={off} onClick={() => void mutate(`corrections/${snap.pending!.revision.revision_id}/reject`)}>Reject</button></div></div> : <div className="ca-form"><label>Claim<select aria-label="Claim" disabled={off} value={claimId} onChange={e => setClaimId(e.target.value)}>{snap?.draft?.claims.map(c => <option key={c.claim_id} value={c.claim_id}>{c.claim_id}: {c.text}</option>)}</select></label><label>Clinician statement<textarea aria-label="Clinician statement" disabled={off} value={statement} onChange={e => setStatement(e.target.value)} /></label><Action disabled={off || !statement.trim() || !claimId} onClick={() => void mutate("corrections", { claim_id: claimId, statement })}>{pendingOperation === "Proposing…" ? "Proposing…" : "Propose correction"}</Action></div>}
                    <details><summary>Revision history ({snap?.revisions.length ?? 0})</summary>{snap?.revisions.map(r => <div className="ca-section" key={r.revision_id}><h4>{r.revision_id} · {r.target_claim_id} · {r.status}</h4><p>Before: {r.before}</p><p>After: {r.after}</p><p>Clinician statement: {r.clinician_statement}</p></div>)}</details>
                    <div className="ca-form"><label>Reviewer<input aria-label="Reviewer" disabled={off || approved} value={reviewer} onChange={e => setReviewer(e.target.value)} /></label>{snap?.pending && <p>Accept or reject the pending correction before approving.</p>}<div className="cp-review-actions"><Action disabled={off || approved || !!snap?.pending || !reviewer.trim()} onClick={() => void mutate("approve", { reviewer: reviewer.trim() })}>Approve draft</Action><button className="cp-secondary" disabled={off || !approved || !!snap?.pending} onClick={() => void mutate("export")}>Download Word document</button></div></div>
                </section>}
                <aside ref={inspector} tabIndex={-1} className="cp-inspector ca-inspector" aria-label="Contextual inspector"><div className="cp-inspector-heading"><span className="cp-eyebrow">INSPECTOR</span><span>Source evidence and output</span></div>
                    {source ? <><h2>Source evidence</h2><h4>{source.filename}</h4><p>Page {source.page} · {source.marker}</p><blockquote>{source.text}</blockquote></> : documentInfo ? <><h2>{documentInfo.filename}</h2><h4>Source passages</h4>{Object.entries(snap!.passages).filter(([, p]) => p.document_id === documentInfo.document_id).map(([id, p]) => <div className="cp-evidence" key={id}><span>Page {p.page} · {p.marker}</span><blockquote>{p.text}</blockquote></div>)}<h4>Extracted events</h4>{snap!.events.filter(e => e.evidence.some(ref => snap!.passages[ref.span_id]?.document_id === documentInfo.document_id)).map(e => <div className="cp-evidence" key={e.event_id}><span>{e.event_id} · {e.category}</span><p>{e.statement} {citations(e.evidence.map(r => r.span_id))}</p></div>)}{!extracted && <p>Parallel extraction is in progress. Individual start times are not reported.</p>}</> : selected === "compare" && conflicts.length ? <><h2>Resolve conflicts</h2>{conflicts.map(c => { const pick = picks[c.conflict_id]; return <fieldset className="cp-choice" key={c.conflict_id} disabled={!!pendingOperation}><legend>{c.conflict_id} · {c.description}</legend>{c.quotes.map(q => <div className="cp-evidence" key={q.span_id}><span>{q.filename} · {q.marker}{q.date && ` · ${q.date}`}{q.hospital_day != null && ` · Hospital day ${q.hospital_day}`}</span><blockquote>{q.text}</blockquote><label><input type="radio" name={c.conflict_id} checked={pick?.span === q.span_id} onChange={() => setPicks(p => ({ ...p, [c.conflict_id]: { span: q.span_id, text: pick?.text ?? "" } }))} />Use this value: {q.quote}</label></div>)}<label><input type="radio" name={c.conflict_id} checked={!!pick && pick.span === null} onChange={() => setPicks(p => ({ ...p, [c.conflict_id]: { span: null, text: pick?.text ?? "" } }))} />Clarify {c.conflict_id}</label><label htmlFor={`ca-${c.conflict_id}`}>Clinician clarification {c.conflict_id}</label><textarea id={`ca-${c.conflict_id}`} value={pick?.text ?? ""} onChange={e => setPicks(p => ({ ...p, [c.conflict_id]: { span: null, text: e.target.value } }))} /></fieldset>; })}<Action disabled={!validPicks || !!pendingOperation} onClick={() => setCheckpoint(true)}>Review resolutions</Action></> : selected === "writer" && !review ? <><h2>Live draft sections</h2>{draftContents()}<Action disabled={!ready || !snap?.draft} onClick={() => setReview(true)}>Review draft</Action></> : <><h2>Review summary</h2><h4>Discrepancies</h4>{snap?.draft?.discrepancies.length ? snap.draft.discrepancies.map(d => <div className="cp-evidence" key={d.discrepancy_id}><span>{d.discrepancy_id} · {d.status}</span><p>{d.description} {citations(d.source_span_ids)}</p></div>) : <p>{snap?.draft ? "None flagged." : "Awaiting comparison output."}</p>}<h4>Conflict resolutions</h4>{snap?.resolutions?.map(r => <div className="cp-callout" key={r.conflict_id}>Clinician-provided ({r.conflict_id}): "{r.text}"<p>{r.chosen_span_id ? "Clinician-selected source value" : "Typed clarification, not document evidence"} {r.chosen_span_id && citations([r.chosen_span_id])}</p></div>)}<h4>Clinician provenance</h4>{snap?.clarifications.map(c => <p key={c.clarification_id}>{c.clarification_id} · {c.status}: {c.statement}</p>)}<h4>Missing notes</h4><p>{snap?.missing_notes?.join(", ") || (ready ? "None reported." : "Awaiting completion.")}</p></>}
                    {(source || documentInfo || selected === "writer") && <button className="cp-secondary" onClick={() => setSelected("compare")}>Review summary / conflicts</button>}
                </aside>
            </>}
            <footer className="cp-page-footer"><span>Synthetic demonstration · Not for clinical use</span><span>{sid ? `Session ${sid}` : "No session loaded"}</span></footer>
        </main>
        <div className="ca-chat"><button className="ca-chat-toggle" aria-expanded={chatOpen} disabled={!ready || !snap?.draft} onClick={() => setChatOpen(o => !o)}>{chatOpen ? "Minimize case chat" : "Ask about this case"}</button>{chatOpen && <section className="ca-chat-panel" aria-label="Ask about this case"><h2>Ask about this case</h2><div className="ca-turns" aria-live="polite">{turns.map((turn, i) => <div className="ca-turn" key={i}><strong>{turn.question}</strong><p>{turn.answer} {citations(turn.cited)}</p><small>{turn.stopped ? "Stopped. Partial answer." : turn.error ? "Failed. Partial answer." : turn.stage}</small>{turn.error && <p role="alert">{turn.error}</p>}</div>)}</div><form onSubmit={e => { e.preventDefault(); void ask(); }}><label htmlFor="ca-question">Question</label><textarea id="ca-question" value={question} disabled={off} onChange={e => setQuestion(e.target.value)} /><div className="cp-review-actions"><Action type="submit" disabled={off || !question.trim()}>Ask</Action>{pendingOperation === "Answering" && <button className="cp-secondary" type="button" onClick={() => askController.current?.abort()}>Stop answer</button>}</div><p role="status">{pendingOperation === "Answering" ? "Answering your question…" : "Answers use this case's evidence."}</p></form></section>}</div>
    </div>;
}
