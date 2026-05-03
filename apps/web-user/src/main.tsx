import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { Toaster } from "react-hot-toast";

import { router } from "@/router";
import { queryClient } from "@/lib/query-client";
import "@/stores/auth"; // mount session subscription
import "./styles.css";

const root = createRoot(document.getElementById("root")!);

root.render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster
        position="top-center"
        toastOptions={{
          duration: 3500,
          style: {
            borderRadius: "10px",
            background: "#0F172A",
            color: "#fff",
            fontSize: 13,
            padding: "10px 14px",
          },
          success: { iconTheme: { primary: "#10B981", secondary: "#fff" } },
          error:   { iconTheme: { primary: "#EF4444", secondary: "#fff" } },
        }}
      />
    </QueryClientProvider>
  </StrictMode>
);
