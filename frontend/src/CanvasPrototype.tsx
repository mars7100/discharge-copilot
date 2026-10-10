import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import type { WorkStatus } from "./prototype-types";
import "./CanvasPrototype.css";

type Phase = "reading" | "conflict" | "drafting" | "ready";
const notes = [
    { id: "admission", label: "Admission note", date: "Oct 08 · 09:20", title: "The starting point", detail: "Community-acquired pneumonia. Oxygen started at 2 L/min. Home medication list recorded.", output: "3 problems identified" },
    { id: "progress", label: "Progress note", date: "Oct 09 · 14:45", title: "What changed", detail: "Breathing improved. Off supplemental oxygen. Plan documents amoxicillin 500 mg three times daily.", output: "4 updates extracted" },
    { id: "medication", label: "Medication orders", date: "Oct 10 · 08:10", title: "The discharge plan", detail: "Final signed order: amoxicillin 1 g three times daily for 5 days. Follow up with primary care in one week.", output: "2 orders verified" },
];
const statusLabels: Record<WorkStatus, string> = { queued: "Queued", working: "Working", done: "Complete", attention: "Needs decision" };

/** Draw a native, decorative icon. */
function Icon({ kind = "note" }: { kind?: "note" | "compare" | "write" | "arrow" | "check" }): ReactElement {
    const paths = { note: "M7 3h7l4 4v14H7z M14 3v5h4 M10 12h5 M10 16h5", compare: "M4 7h15m-4-4 4 4-4 4 M20 17H5m4-4-4 4 4 4", write: "m5 16-1 4 4-1L20 7l-3-3Z M14 7l3 3", arrow: "M4 12h16m-6-6 6 6-6 6", check: "m5 12 4 4L19 6" };
    return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[kind]} /></svg>;
}

/** Render the adapted six-layer loader only for running work. */
function Status({ status, paused }: { status: WorkStatus; paused: boolean }): ReactElement {
    return <span className={`cp-status ${status}`}><span className={`cp-status-mark ${status === "working" && !paused ? "breathing" : ""}`} aria-hidden="true">
        {status === "working" ? Array.from({ length: 6 }, (_, i) => <i key={i} style={{ animationDelay: `${i * .3}s` }} />) : status === "done" ? <Icon kind="check" /> : status === "attention" ? "!" : <span className="cp-queue-dot" />}
    </span>{status === "working" && paused ? "Paused" : statusLabels[status]}</span>;
}

/** Render an arrow button with a keyboard-accessible hover treatment. */
function Action({ children, onClick, disabled = false }: { children: string; onClick: () => void; disabled?: boolean }): ReactElement {
    return <button className="cp-action" onClick={onClick} disabled={disabled}><span className="cp-arrow-in"><Icon kind="arrow" /></span><span className="cp-action-text">{children}</span><span className="cp-arrow-out"><Icon kind="arrow" /></span></button>;
}

/** Run the standalone, entirely local discharge-workflow demonstration. */
export default function CanvasPrototype(): ReactElement {
    const [phase, setPhase] = useState<Phase>("reading");
    const [paused, setPaused] = useState(false);
    const [selected, setSelected] = useState("progress");
    const [choice, setChoice] = useState("");
    const [review, setReview] = useState(false);
    const [approved, setApproved] = useState(false);
    const [draft, setDraft] = useState("");
    const [notice, setNotice] = useState("");
    useEffect(() => {
        if (paused || (phase !== "reading" && phase !== "drafting")) return;
        const timer = window.setTimeout(() => {
            if (phase === "reading") { setPhase("conflict"); setSelected("compare"); }
            else { setPhase("ready"); setSelected("writer"); }
        }, 4500);
        return () => window.clearTimeout(timer);
    }, [phase, paused]);
    const noteStatus: WorkStatus = phase === "reading" ? "working" : "done";
    const compareStatus: WorkStatus = phase === "reading" ? "queued" : phase === "conflict" ? "attention" : "done";
    const writerStatus: WorkStatus = phase === "drafting" ? "working" : phase === "ready" ? "done" : "queued";
    const currentNote = notes.find(note => note.id === selected);

    /** Resolve the explicit medication gate and start the writer. */
    function resolve(): void {
        if (!choice) return;
        setDraft(`Admitted with community-acquired pneumonia. Improved with antibiotic treatment and weaned off oxygen.\n\nDischarge medication: amoxicillin ${choice} three times daily for 5 days.\n\nFollow up with primary care in one week. Seek urgent care for worsening breathlessness or fever.`);
        setPhase("drafting"); setSelected("writer"); setPaused(false);
    }

    /** Reset all local simulation and review state. */
    function replay(): void {
        setPhase("reading"); setPaused(false); setSelected("progress"); setChoice("");
        setReview(false); setApproved(false); setDraft(""); setNotice("");
    }

    /** Download the approved local draft as a clearly marked demo. */
    function exportDemo(): void {
        if (!approved) return;
        const url = URL.createObjectURL(new Blob([`SIMULATED DEMO · NOT A CLINICAL RECORD\n\n${draft}`], { type: "text/plain" }));
        const link = document.createElement("a"); link.href = url; link.download = "discharge-demo.txt"; link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice("Demo exported as discharge-demo.txt");
    }

    return <div className="cp-app">
        <header className="cp-header"><a className="cp-brand" href="?mockup=canvas"><span className="cp-brand-mark"><Icon kind="compare" /></span>discharge<span>copilot</span></a><span className="cp-demo">Interactive prototype <span>· Simulated data</span></span><a className="cp-app-link" href="/">Open app <Icon kind="arrow" /></a></header>
        <main>
            <section className="cp-case"><div><div className="cp-eyebrow">DISCHARGE WORKSPACE / CASE 024</div><h1>Alex Morgan <span>Ready for the next step.</span></h1><p>68 years · Community-acquired pneumonia · Admitted Oct 08</p></div><div className="cp-case-meta"><span className="cp-avatar">AM</span><div><strong>General medicine</strong><span>Discharge · Oct 10, 2026</span></div></div></section>
            <div className="cp-toolbar"><div className="cp-tabs"><button className={!review ? "active" : ""} onClick={() => setReview(false)}>Agent canvas</button><button className={review ? "active" : ""} disabled={phase !== "ready"} onClick={() => setReview(true)}>Results review{phase === "ready" && <span className="cp-tab-dot" />}</button></div><div className="cp-controls"><span className="cp-run-state" role="status">{paused ? "Simulation paused" : phase === "conflict" ? "Waiting for your decision" : phase === "ready" ? "Draft ready for review" : "Simulation running"}</span><button onClick={() => setPaused(!paused)} disabled={phase === "conflict" || phase === "ready"}>{paused ? "Resume" : "Pause"}</button><button onClick={replay}>Replay</button></div></div>
            {!review ? <div className="cp-workspace">
                <section className={`cp-canvas ${paused ? "is-paused" : ""}`} aria-label="Connected agent canvas">
                    <div className="cp-canvas-heading"><div><h2>Three notes. One discharge draft.</h2><p>Select an agent to inspect its evidence and output.</p></div><span className="cp-live"><span />{phase === "ready" ? "RUN COMPLETE" : "LOCAL REPLAY"}</span></div>
                    <div className="cp-stage-headings"><span>01 <strong>Read in parallel</strong></span><span>02 <strong>Reconcile</strong></span><span>03 <strong>Compose</strong></span></div>
                    <div className="cp-graph">
                        <svg className={`cp-wires ${phase !== "reading" ? "connected" : ""}`} viewBox="0 0 1000 640" preserveAspectRatio="none" aria-hidden="true"><path d="M280 105 C350 105 310 320 380 320 M280 320 H380 M280 535 C350 535 310 320 380 320 M660 320 H730" /><circle cx="380" cy="320" r="5" /><circle cx="730" cy="320" r="5" /></svg>
                        <div className="cp-note-column">{notes.map((note, index) => <button key={note.id} className={`cp-node cp-note ${selected === note.id ? "selected" : ""}`} onClick={() => setSelected(note.id)} aria-pressed={selected === note.id}>
                            <div className="cp-node-top"><span className="cp-node-icon"><Icon /></span><span className="cp-node-index">NOTE 0{index + 1}</span><Status status={noteStatus} paused={paused} /></div><h3>{note.label}</h3><p>{note.title}</p><div className="cp-output"><span>{phase === "reading" ? "Reading source" : "Output"}</span><strong>{phase === "reading" ? "Extracting clinical facts…" : note.output}</strong></div><div className="cp-node-foot">{note.date}<span>Inspect source</span></div>
                        </button>)}</div>
                        <button className={`cp-node cp-compare ${selected === "compare" ? "selected" : ""}`} onClick={() => setSelected("compare")} aria-pressed={selected === "compare"}><div className="cp-node-top"><span className="cp-node-icon"><Icon kind="compare" /></span><Status status={compareStatus} paused={paused} /></div><span className="cp-eyebrow">COMPARISON AGENT</span><h3>Make the notes<br />agree.</h3><p>Check the timeline, reconcile medications, flag differences.</p><div className="cp-output"><span>{phase === "conflict" ? "Decision required" : "Output"}</span><strong>{phase === "reading" ? "Waiting for all 3 notes" : phase === "conflict" ? "1 medication conflict" : "Medication conflict resolved"}</strong></div><div className="cp-node-foot">3 sources<span>{phase === "conflict" ? "Resolve in inspector" : "Evidence linked"}</span></div></button>
                        <button className={`cp-node cp-writer ${selected === "writer" ? "selected" : ""}`} onClick={() => setSelected("writer")} aria-pressed={selected === "writer"}><div className="cp-node-top"><span className="cp-node-icon"><Icon kind="write" /></span><Status status={writerStatus} paused={paused} /></div><span className="cp-eyebrow">DISCHARGE WRITER</span><h3>A clear plan<br />to go home.</h3><p>Compose the hospital course, medications, and follow-up.</p><div className="cp-output"><span>Output</span><strong>{phase === "ready" ? "Discharge draft · v1" : phase === "drafting" ? "Writing from resolved facts…" : "Waiting for reconciliation"}</strong></div><div className="cp-node-foot">Human review required<span>{phase === "ready" ? "Ready" : "Not released"}</span></div></button>
                    </div>
                    <footer className="cp-canvas-footer"><span><span className="cp-legend-dot" /> Evidence follows every connection</span><span>{phase === "reading" ? "0" : phase === "conflict" ? "3" : phase === "drafting" ? "4" : "5"} / 5 agents complete</span></footer>
                </section>
                <aside className="cp-inspector" aria-label="Contextual inspector"><div className="cp-inspector-heading"><span className="cp-eyebrow">INSPECTOR</span><span>Selected agent</span></div>
                    {currentNote ? <><span className="cp-large-icon"><Icon /></span><h2>{currentNote.label}</h2><Status status={noteStatus} paused={paused} /><h4>Source excerpt</h4><blockquote>{currentNote.detail}</blockquote><div className="cp-source-label">{currentNote.date} · Signed note</div><h4>Agent output</h4><p>{phase === "reading" ? "Reading the note and extracting facts. All three readers run in parallel." : currentNote.output + ". Source evidence is available to the comparison agent."}</p><button className="cp-secondary" onClick={() => setSelected("compare")}>Inspect comparison <Icon kind="arrow" /></button></> : selected === "compare" ? <><span className="cp-large-icon"><Icon kind="compare" /></span><h2>Medication reconciliation</h2><Status status={compareStatus} paused={paused} /><h4>{phase === "conflict" ? "Two sources disagree" : phase === "reading" ? "Awaiting extracted facts" : "Decision recorded"}</h4><p>The progress note and final order list different amoxicillin doses.</p><div className="cp-evidence"><span>PROGRESS NOTE · OCT 09</span><strong>500 mg · three times daily</strong></div><div className="cp-evidence"><span>FINAL ORDER · OCT 10</span><strong>1 g · three times daily</strong></div>{phase === "conflict" ? <fieldset className="cp-choice"><legend>Choose the dose for this demo</legend>{["1 g", "500 mg"].map(dose => <label key={dose}><input type="radio" name="dose" checked={choice === dose} onChange={() => setChoice(dose)} /><span>{dose}<small>{dose === "1 g" ? "Use the final signed order" : "Use the progress note"}</small></span></label>)}<Action disabled={!choice} onClick={resolve}>Resolve & continue</Action></fieldset> : <p className="cp-callout">{phase === "reading" ? "The comparison starts after all readers finish." : `Resolved by you: ${choice}. The writer uses this decision.`}</p>}</> : <><span className="cp-large-icon"><Icon kind="write" /></span><h2>Discharge writer</h2><Status status={writerStatus} paused={paused} /><h4>Draft contents</h4><ul className="cp-contents"><li>Hospital course</li><li>Reconciled medication plan</li><li>Follow-up & return precautions</li></ul><h4>Evidence basis</h4><p>Three source notes and {choice ? `your ${choice} medication decision` : "a pending medication decision"}.</p><div className="cp-callout">{phase === "ready" ? "Draft complete. Review and correct before approving." : "The writer waits for your conflict decision before drafting."}</div><Action disabled={phase !== "ready"} onClick={() => setReview(true)}>Review draft</Action></>}
                    <div className="cp-inspector-bottom">Local simulation. No patient data is sent.</div>
                </aside>
            </div> : <section className="cp-review"><div className="cp-review-document"><div className="cp-review-title"><div><span className="cp-eyebrow">RESULTS / DISCHARGE DRAFT</span><h2>Review before release.</h2></div><span className={`cp-approval ${approved ? "approved" : ""}`}>{approved ? "Approved by you" : "Awaiting approval"}</span></div><label htmlFor="cp-draft">Discharge summary <span>Editable · changes require fresh approval</span></label><textarea id="cp-draft" value={draft} onChange={event => { setDraft(event.target.value); setApproved(false); setNotice("Correction saved locally. Approval required."); }} /><div className="cp-review-actions"><Action disabled={approved || !draft.trim()} onClick={() => { setApproved(true); setNotice("Draft approved for demo export."); }}>Approve draft</Action><button className="cp-secondary" disabled={!approved} onClick={exportDemo}>Export demo <Icon kind="arrow" /></button></div><p role="status" className="cp-notice">{notice || "Review the evidence and correct the draft as needed."}</p></div><aside className="cp-review-evidence"><span className="cp-eyebrow">LINKED EVIDENCE</span><h2>Where the facts came from</h2>{notes.map(note => <div className="cp-evidence" key={note.id}><span>{note.label} · {note.date}</span><p>{note.detail}</p></div>)}<div className="cp-callout"><strong>Your resolution</strong><p>Amoxicillin {choice} three times daily. Recorded before drafting.</p></div><button className="cp-secondary" onClick={() => { setReview(false); setSelected("compare"); }}>Return to agent canvas</button></aside></section>}
            <footer className="cp-page-footer"><span>Discharge copilot · Design preview</span><span>Simulated case · No backend connection</span></footer>
        </main>
    </div>;
}
