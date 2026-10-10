import type { PrototypeTask, PrototypeVariantProps, WorkStatus } from "./prototype-types";
import "./BoardPrototype.css";

const stages = [
    { title: "Reading notes", subtitle: "Source material, read in parallel", ids: ["admission", "consult", "medications"] },
    { title: "Comparing findings", subtitle: "Cross-check the clinical picture", ids: ["compare"] },
    { title: "Drafting sections", subtitle: "Turn reviewed findings into a discharge draft", ids: ["course", "meds", "followup"] },
];

const statusLabels: Record<WorkStatus, string> = {
    queued: "Queued",
    working: "Working",
    done: "Complete",
    attention: "Needs review",
};

/** Render a decorative, dependency-free workflow icon. */
function TaskIcon({ comparison = false }: { comparison?: boolean }): React.JSX.Element {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {comparison ? (
                <>
                    <path d="M8 4H4v16h4M16 4h4v16h-4M8 8h8M8 16h8M10 6 8 8l2 2M14 14l2 2-2 2" />
                </>
            ) : (
                <>
                    <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8Z" />
                    <path d="M14 3v5h5M9 12h6M9 16h4" />
                </>
            )}
        </svg>
    );
}

/** Display one selectable task using only its supplied workflow state. */
function TaskCard({ task, selected, comparison, onSelect }: {
    task: PrototypeTask;
    selected: boolean;
    comparison: boolean;
    onSelect: (id: string) => void;
}): React.JSX.Element {
    return (
        <button
            type="button"
            className={`bp-card bp-card--${task.status}${selected ? " bp-card--selected" : ""}`}
            aria-pressed={selected}
            onClick={() => onSelect(task.id)}
        >
            <span className="bp-card-top">
                <span className="bp-role">{task.role}</span>
                <span className={`bp-status bp-status--${task.status}`}>
                    <span className="bp-status-mark" aria-hidden="true">
                        {task.status === "done" ? "✓" : task.status === "attention" ? "!" : ""}
                    </span>
                    {statusLabels[task.status]}
                </span>
            </span>
            <span className="bp-card-main">
                <span className="bp-icon"><TaskIcon comparison={comparison} /></span>
                <span className="bp-card-copy">
                    <span className="bp-task-label">{task.label}</span>
                    <span className="bp-detail">{task.detail}</span>
                </span>
            </span>
            <span className={`bp-card-bottom${task.status === "done" ? " bp-card-bottom--output" : ""}`}>
                {task.status === "done" ? (
                    <>
                        <span className="bp-output-label">Ready to use</span>
                        <span className="bp-output">{task.output}</span>
                    </>
                ) : (
                    <span className="bp-task-footer">
                        <span>
                            {task.status === "working" ? "In progress" : task.status === "attention" ? "Review findings" : "Waiting to start"}
                            {task.status === "working" && <span className="bp-activity" aria-hidden="true"><i /><i /><i /></span>}
                        </span>
                        <span className="bp-open">View task <span aria-hidden="true">↗</span></span>
                    </span>
                )}
            </span>
        </button>
    );
}

/** Render the simulated discharge workflow as grouped, parallel task cards. */
export default function BoardPrototype({ tasks, selectedId, onSelect }: PrototypeVariantProps): React.JSX.Element {
    const boardTasks = tasks.filter((task) => stages.some((stage) => stage.ids.includes(task.id)));
    const completed = boardTasks.filter((task) => task.status === "done").length;
    const working = boardTasks.filter((task) => task.status === "working").length;

    return (
        <section className="bp-board" aria-label="Discharge preparation work board">
            <div className="bp-board-summary" aria-live="polite">
                <span className="bp-summary-label"><span className="bp-summary-dot" aria-hidden="true" />Workflow overview</span>
                <span className="bp-summary-counts">
                    {working > 0 && <span>{working} working in parallel</span>}
                    <span className="bp-summary-complete">{completed} / {boardTasks.length} complete</span>
                </span>
            </div>
            <div className="bp-stages">
                {stages.map((stage, index) => {
                    const stageTasks = stage.ids.flatMap((id) => tasks.filter((task) => task.id === id));
                    const done = stageTasks.filter((task) => task.status === "done").length;
                    return (
                        <section className={`bp-stage bp-stage--${index + 1}`} key={stage.title} aria-label={stage.title}>
                            <div className="bp-stage-heading">
                                <span className="bp-stage-number">0{index + 1}</span>
                                <div className="bp-stage-titles">
                                    <h2>{stage.title}</h2>
                                    <p>{stage.subtitle}</p>
                                </div>
                                <span className="bp-stage-count" aria-label={`${done} of ${stageTasks.length} complete`}>{done}/{stageTasks.length}</span>
                            </div>
                            <div className="bp-card-grid">
                                {stageTasks.map((task) => (
                                    <TaskCard key={task.id} task={task} selected={selectedId === task.id} comparison={index === 1} onSelect={onSelect} />
                                ))}
                                {stageTasks.length === 0 && <p className="bp-empty">No tasks in this stage.</p>}
                            </div>
                        </section>
                    );
                })}
            </div>
            <p className="bp-board-footnote">Select any task to inspect its sources and output.</p>
        </section>
    );
}
