/** Throwaway comparison: ?mockup=canvas|board. All events and content are simulated. */
import { useEffect, useState } from "react";
import CanvasPrototype from "./CanvasPrototype";
import BoardPrototype from "./BoardPrototype";
import type { PrototypeTask, WorkStatus } from "./prototype-types";
import "./WorkspacePrototype.css";

const seeds = [
    ["admission", "Admission note", "Note reader", "Identifying the admission reason and initial treatment.", "Admitted with shortness of breath. Treatment started on hospital day 1."],
    ["consult", "Consultation", "Note reader", "Finding specialist recommendations and follow-up.", "Symptoms improved. Follow-up recommended within one week."],
    ["medications", "Medication notes", "Note reader", "Extracting medication changes across the stay.", "Two notes list different doses of Medication A: 5 mg and 10 mg."],
    ["compare", "Compare the evidence", "Evidence comparison", "Checking the extracted findings for conflicting values.", "Medication A dose differs between two sources. Your decision is required."],
    ["course", "Hospital course", "Section writer", "Combining the admission and treatment timeline.", "Admitted with shortness of breath; symptoms improved with treatment."],
    ["meds", "Discharge medications", "Section writer", "Drafting the medication plan using your selected source.", "Medication A: 10 mg daily, based on the discharge medication note."],
    ["followup", "Follow-up plan", "Section writer", "Organizing the documented next steps.", "Follow up within one week. Return precautions documented in source notes."],
];

export default function WorkspacePrototype() {
    const [variant, setVariant] = useState(new URLSearchParams(location.search).get("mockup") === "board" ? "board" : "canvas");
    const [tick, setTick] = useState(0);
    const [playing, setPlaying] = useState(true);
    const [selectedId, setSelectedId] = useState("admission");
    const [choice, setChoice] = useState("");
    const [resolved, setResolved] = useState(false);
    const [reviewing, setReviewing] = useState(false);
    const [evidence, setEvidence] = useState(false);
    const [editing, setEditing] = useState(false);
    const [text, setText] = useState("Medication A: 10 mg daily.");
    const [savedText, setSavedText] = useState("Medication A: 10 mg daily.");
    const [notice, setNotice] = useState("");
    const [approved, setApproved] = useState(false);
    const phase = tick < 4 ? "reading" : !resolved ? "conflict" : tick < 8 ? "drafting" : "ready";

    useEffect(() => {
        if (!playing || phase === "conflict" || phase === "ready") return;
        const timer = window.setInterval(() => setTick(value => Math.min(value + 1, 8)), 1500);
        return () => window.clearInterval(timer);
    }, [playing, phase]);

    function switchVariant(next: string): void {
        setVariant(next);
        const url = new URL(location.href);
        url.searchParams.set("mockup", next);
        history.replaceState(null, "", url);
    }

    useEffect(() => {
        function handleKey(event: KeyboardEvent): void {
            if ((event.target as HTMLElement).closest("input,textarea,select,[contenteditable]")) return;
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                event.preventDefault();
                switchVariant(variant === "canvas" ? "board" : "canvas");
            }
        }
        window.addEventListener("keydown", handleKey);
        return () => window.removeEventListener("keydown", handleKey);
    }, [variant]);

    function replay(): void {
        setTick(0); setResolved(false); setChoice(""); setPlaying(true); setReviewing(false);
        setSelectedId("admission"); setApproved(false); setNotice(""); setEvidence(false); setEditing(false);
        setText("Medication A: 10 mg daily."); setSavedText("Medication A: 10 mg daily.");
    }

    const tasks: PrototypeTask[] = seeds.map(([id, label, role, detail, output], index) => {
        let status: WorkStatus;
        if (index < 3) status = tick >= index + 1 ? "done" : "working";
        else if (index === 3) status = resolved ? "done" : tick >= 4 ? "attention" : tick >= 3 ? "working" : "queued";
        else status = !resolved ? "queued" : tick >= index + 1 ? "done" : "working";
        if (id === "compare" && resolved) output = "Dose conflict resolved by reviewer. Drafting can continue.";
        if (id === "meds" && resolved) output = `Medication A: ${choice} daily, based on the reviewer-selected source.`;
        return { id, label, role, detail, output, status };
    });
    const selected = tasks.find(task => task.id === selectedId)!;
    const completed = tasks.filter(task => task.status === "done").length;
    const Variant = variant === "canvas" ? CanvasPrototype : BoardPrototype;

    return <div className="wp-shell">
        <aside className="wp-rail">
            <a className="wp-brand" href="?mockup=canvas" aria-label="Discharge Copilot prototype"><span>✳</span></a>
            <div className="wp-rail-item wp-rail-active" title="Case workspace">▤</div>
            <div className="wp-rail-line" />
            <span className="wp-avatar" title="Demo reviewer">JD</span>
        </aside>
        <div className="wp-page">
            <header className="wp-topbar"><div><strong>Discharge<span>Copilot</span></strong><span className="wp-separator">/</span><span>Case workspace</span></div><span className="wp-demo-label">Design prototype · Simulated data</span></header>
            <main className="wp-main">
                <div className="wp-heading">
                    <div><div className="wp-eyebrow">CASE 001 <span>·</span> SYNTHETIC DEMO</div><h1>{reviewing ? "A clearer picture. Ready to review." : "From scattered notes to a clear plan."}</h1><p>{reviewing ? "Review the draft, inspect its sources, and make it yours." : "Watch the work happen. Step in when your judgment is needed."}</p></div>
                    <button className="wp-secondary" onClick={replay}>↻ Replay demo</button>
                </div>
                <nav className="wp-steps" aria-label="Workflow progress">
                    {["Read notes", "Resolve conflicts", "Build draft", "Review & export"].map((label, index) => <div key={label} className={index === (reviewing || phase === "ready" ? 3 : phase === "drafting" ? 2 : phase === "conflict" ? 1 : 0) ? "wp-step wp-step-current" : "wp-step"}><span>{index + 1}</span>{label}</div>)}
                </nav>
                {!reviewing ? <>
                    <div className="wp-workspace">
                        <section className="wp-work-panel" aria-label="Live agent activity">
                            <div className="wp-panel-heading"><div><span className={`wp-live-dot ${phase === "conflict" ? "wp-amber" : ""}`} /><strong>{phase === "conflict" ? "Your input is needed" : phase === "ready" ? "Draft complete" : playing ? "Live workspace" : "Workspace paused"}</strong><span className="wp-subtle">{completed} / 7 tasks complete</span></div><button className="wp-text-button" disabled={phase === "conflict" || phase === "ready"} onClick={() => setPlaying(!playing)}>{playing ? "Pause" : "Resume"}</button></div>
                            <Variant tasks={tasks} phase={phase} selectedId={selectedId} onSelect={setSelectedId} />
                        </section>
                        <aside className="wp-inspector">
                            <div className="wp-eyebrow">{phase === "conflict" ? "REVIEWER HANDOFF" : "TASK INSPECTOR"}</div>
                            {phase === "conflict" ? <>
                                <div className="wp-inspector-icon wp-conflict-icon">!</div><h2>One dose. Two sources.</h2><p>The notes disagree about Medication A. Select the source to use for this simulated draft.</p>
                                {[{ value: "5 mg", source: "Admission note · Day 1", quote: "Continue Medication A 5 mg daily." }, { value: "10 mg", source: "Discharge note · Day 4", quote: "Medication A increased to 10 mg daily." }].map(option => <label className={`wp-choice ${choice === option.value ? "wp-choice-selected" : ""}`} key={option.value}><div><input type="radio" name="dose" value={option.value} checked={choice === option.value} onChange={() => setChoice(option.value)} /><strong>Use {option.value}</strong></div><small>{option.source}</small><p>“{option.quote}”</p></label>)}
                                <button className="wp-primary wp-full" disabled={!choice} onClick={() => { setResolved(true); setPlaying(true); setSelectedId("course"); setSavedText(`Medication A: ${choice} daily.`); setText(`Medication A: ${choice} daily.`); }}>Confirm & continue <span>→</span></button><small className="wp-footnote">Simulated choice, not a clinical recommendation.</small>
                            </> : <>
                                <div className="wp-inspector-icon">✳</div><span className="wp-subtle">{selected.role}</span><h2>{selected.label}</h2><p>{selected.detail}</p>
                                <div className={`wp-task-state wp-state-${selected.status}`}>{selected.status === "done" ? "✓ Complete" : selected.status === "working" ? "◉ Processing" : "Waiting for earlier work"}</div>
                                <div className="wp-output"><div className="wp-eyebrow">{selected.status === "done" ? "TASK OUTPUT" : "WHAT HAPPENS HERE"}</div><p>{selected.status === "done" ? selected.output : selected.status === "working" ? "This task is processing. Its result will appear here when complete." : "This task starts after the evidence has been compared and any conflicts resolved."}</p></div>
                                <div className="wp-source-tag">▤ {selected.id === "consult" ? "Consultation note" : selected.id === "medications" || selected.id === "meds" ? "Medication notes" : "Case 001 source notes"}</div>
                                {phase === "ready" && <button className="wp-primary wp-full" onClick={() => setReviewing(true)}>Open draft for review <span>→</span></button>}
                            </>}
                        </aside>
                    </div>
                    <div className="wp-preview"><div><span className="wp-preview-icon">▤</span><div><strong>{phase === "ready" ? "Your draft is ready" : "The draft is taking shape"}</strong><p>{tasks.filter(task => ["course", "meds", "followup"].includes(task.id) && task.status === "done").map(task => task.label).join(" · ") || "Sections appear here as the writing tasks finish."}</p></div></div>{phase === "ready" ? <button className="wp-primary" onClick={() => setReviewing(true)}>Review draft →</button> : <span className="wp-subtle">{phase === "conflict" ? "Waiting for your decision" : "Preparing document"}</span>}</div>
                </> : <div className="wp-review-layout">
                    <article className="wp-document"><div className="wp-document-top"><span className="wp-eyebrow">DISCHARGE SUMMARY</span><span className={`wp-task-state ${approved ? "wp-state-done" : ""}`}>{approved ? "✓ Approved · demo" : "Draft · pending review"}</span></div><h2>Case 001</h2><p className="wp-subtle">Synthetic hospitalization · 4 hospital days</p><h3>Hospital course</h3><p>Admitted with shortness of breath. Symptoms improved with treatment during the hospitalization. <button className="wp-citation" onClick={() => { setEvidence(true); setEditing(false); }}>Source 1</button></p><h3>Discharge medications</h3><div className="wp-claim"><p>{savedText}</p><div><button className="wp-text-button" onClick={() => { setEvidence(true); setEditing(false); }}>View sources</button><button className="wp-text-button" onClick={() => { setEditing(true); setEvidence(false); setText(savedText); }}>Edit sentence</button></div></div><h3>Follow-up</h3><p>Follow up within one week. See source notes for documented return precautions. <button className="wp-citation" onClick={() => { setEvidence(true); setEditing(false); }}>Source 3</button></p><div className="wp-document-note">This is simulated prototype content. Source links demonstrate the interaction only.</div></article>
                    <aside className="wp-inspector"><div className="wp-eyebrow">{editing ? "CORRECT A SENTENCE" : evidence ? "SOURCE EVIDENCE" : "REVIEW WORKSPACE"}</div><h2>{editing ? "Make the change clear." : evidence ? "Read it in context." : "The final word is yours."}</h2>{editing ? <><label htmlFor="wp-correction">Corrected sentence</label><textarea id="wp-correction" value={text} onChange={event => setText(event.target.value)} /><div className="wp-output"><small>ORIGINAL</small><p>{savedText}</p><small>PROPOSED</small><p>{text || "Enter a corrected sentence."}</p></div><button className="wp-primary wp-full" disabled={!text.trim()} onClick={() => { setSavedText(text.trim()); setEditing(false); setApproved(false); setNotice("Correction applied. Draft is pending review."); }}>Apply correction</button><button className="wp-text-button" onClick={() => setEditing(false)}>Discard change</button></> : evidence ? <><div className="wp-source-tag">▤ Illustrative source excerpt</div><div className="wp-output"><p>“{choice === "10 mg" ? "Medication A increased to 10 mg daily." : "Continue Medication A 5 mg daily."} Symptoms improved during admission. Follow up within one week.”</p></div><p>This excerpt is simulated to demonstrate contextual evidence review.</p><button className="wp-text-button" onClick={() => setEvidence(false)}>Back to review</button></> : <><p>Inspect the evidence beside a sentence or edit it directly. You resolved the medication conflict using the {choice} source.</p><div className="wp-output"><div className="wp-eyebrow">REVIEW SUMMARY</div><p>3 sections drafted<br />1 conflict resolved<br />Synthetic content only</p></div><button className="wp-primary wp-full" onClick={() => { setApproved(true); setNotice("Demo draft approved. Export is ready."); }} disabled={approved}>Approve demo draft</button>{approved && <button className="wp-secondary wp-full" onClick={() => { const blob = new Blob([`# Synthetic prototype discharge summary\n\nNOT A CLINICAL DOCUMENT\n\n${savedText}\n\nFollow up within one week.`], { type: "text/markdown" }); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "prototype-discharge-summary.md"; link.click(); URL.revokeObjectURL(url); setNotice("Demo Markdown download started."); }}>Download demo Markdown</button>}<button className="wp-text-button" onClick={() => setReviewing(false)}>← View agent activity</button></>}{notice && <p className="wp-notice" role="status">{notice}</p>}</aside>
                </div>}
                <footer className="wp-footer">Synthetic data only. Not a clinical tool. <span>No model calls · Replayable simulation</span></footer>
            </main>
        </div>
        <div className="wp-switcher" aria-label="Mockup comparison"><span>COMPARE DESIGNS</span><button aria-label="Previous design" onClick={() => switchVariant(variant === "canvas" ? "board" : "canvas")}>←</button><button aria-pressed={variant === "canvas"} onClick={() => switchVariant("canvas")}>01 · Agent canvas</button><button aria-pressed={variant === "board"} onClick={() => switchVariant("board")}>02 · Live board</button><button aria-label="Next design" onClick={() => switchVariant(variant === "canvas" ? "board" : "canvas")}>→</button></div>
    </div>;
}
