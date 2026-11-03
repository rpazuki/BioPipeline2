"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { ConfigGate } from "@/features/auth/ConfigGate";
import { createQueryClient } from "@/lib/query-client";

export function Providers({ children }: { children: ReactNode }) {
  useEffect(() => {
    const preference = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      document.documentElement.dataset.bsTheme = preference.matches ? "dark" : "light";
    };
    applyTheme();
    preference.addEventListener("change", applyTheme);
    return () => preference.removeEventListener("change", applyTheme);
  }, []);
  // Created once per browser session, not per render: a new QueryClient
  // would throw away every cache on any parent re-render.
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigGate>{children}</ConfigGate>
    </QueryClientProvider>
  );
}
