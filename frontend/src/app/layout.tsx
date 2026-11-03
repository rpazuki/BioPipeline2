import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Providers } from "@/app/providers";
import "@tabler/core/dist/css/tabler.min.css";
import "@/styles/globals.css";
import "@/styles/tabler-theme.css";

export const metadata: Metadata = {
  title: "BioPipeline2",
  description: "Author, publish, and run pipelines.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
