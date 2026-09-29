import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { DataProvider } from "./lib/data";
import { StoreProvider } from "./lib/store";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DataProvider>
      <StoreProvider>
        <App />
      </StoreProvider>
    </DataProvider>
  </StrictMode>,
);
