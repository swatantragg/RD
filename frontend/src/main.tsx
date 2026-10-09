import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Root from "./App";
import "./styles.css";
import { applyTheme, currentTheme } from "./theme";

applyTheme(currentTheme());

const client = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, retry: (n, e: any) => e?.status !== 401 && e?.status !== 403 && n < 1, staleTime: 5_000 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <Root />
    </QueryClientProvider>
  </React.StrictMode>,
);
