import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { THEME_BOOTSTRAP } from "@/lib/theme";

import { I18nProvider } from "@/lib/i18n";

import "./styles.css";
import "./v2.css";
import "@/components/side-panels.css";

export const metadata: Metadata = {
  title: "DocReview RAG",
  description: "Evidence-first SEC and DART filing review",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} /></head>
      <body><I18nProvider><ThemeProvider>{children}</ThemeProvider></I18nProvider></body>
    </html>
  );
}
