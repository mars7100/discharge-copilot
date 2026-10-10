import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import CanvasPrototype from "./CanvasPrototype";

afterEach(() => { cleanup(); vi.useRealTimers(); });

test("pause, conflict gate, corrected draft approval, and replay", () => {
    vi.useFakeTimers();
    render(<CanvasPrototype />);
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    act(() => vi.advanceTimersByTime(6000));
    expect(screen.getByRole("status").textContent).toBe("Simulation paused");
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    act(() => vi.advanceTimersByTime(4500));
    expect((screen.getByRole("button", { name: "Resolve & continue" }) as HTMLButtonElement).disabled).toBe(true);
    act(() => vi.advanceTimersByTime(10000));
    expect(screen.getByRole("status").textContent).toBe("Waiting for your decision");
    fireEvent.click(screen.getByRole("radio", { name: /^1 g/ }));
    fireEvent.click(screen.getByRole("button", { name: "Resolve & continue" }));
    expect(screen.getByRole("status").textContent).toBe("Simulation running");
    act(() => vi.advanceTimersByTime(4500));
    fireEvent.click(screen.getByRole("button", { name: "Review draft" }));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain("amoxicillin 1 g");
    fireEvent.click(screen.getByRole("button", { name: "Approve draft" }));
    expect((screen.getByRole("button", { name: "Export demo" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Corrected summary" } });
    expect((screen.getByRole("button", { name: "Export demo" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("Simulation running");
});
