import type { Metadata } from "next";
import type { ReactNode } from "react";
import { NotificationProvider } from "@/components/notifications";
import { ThemeProvider } from "@/components/theme-provider";
import { THEME_BOOTSTRAP } from "@/lib/theme";

import { I18nProvider } from "@/lib/i18n";

import "./styles.css";
import "./v2.css";

export const metadata: Metadata = {
  title: "DocReview RAG",
  description: "Evidence-first SEC and DART filing review",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} /></head>
      <body><I18nProvider><ThemeProvider><NotificationProvider>{children}</NotificationProvider></ThemeProvider></I18nProvider></body>
    </html>
  );
}
