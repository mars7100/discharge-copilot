import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import CanvasApp from "./CanvasApp";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <CanvasApp />
  </StrictMode>,
);
