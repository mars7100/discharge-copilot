/** Throwaway simulated design data. No backend requests. */
export type WorkStatus = "queued" | "working" | "done" | "attention";
export type PrototypeTask = {
    id: string;
    label: string;
    role: string;
    detail: string;
    output: string;
    status: WorkStatus;
};
export type PrototypeVariantProps = {
    tasks: PrototypeTask[];
    selectedId: string;
    onSelect: (id: string) => void;
    phase: "reading" | "conflict" | "drafting" | "ready";
};
