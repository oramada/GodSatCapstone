import "@sam/design-system/fonts";
import "./index.css";

import { ToastProvider, TooltipProvider } from "@sam/design-system";
import { startThemeSync } from "@sam/design-system/theme";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

startThemeSync();

const root = document.getElementById("root");
if (!root) throw new Error("Studio root element is missing");

createRoot(root).render(
  <StrictMode>
    <TooltipProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </TooltipProvider>
  </StrictMode>,
);
