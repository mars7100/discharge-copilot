import { StrictMode } from "react";
import { lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

const CanvasPrototype = lazy(() => import("./CanvasPrototype"));
const showMockup = import.meta.env.DEV && new URLSearchParams(location.search).get("mockup") === "canvas";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {showMockup ? <Suspense fallback={<p>Opening canvas…</p>}><CanvasPrototype /></Suspense> : <App />}
  </StrictMode>,
);
