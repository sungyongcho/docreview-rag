import type { Metadata } from "next";
import type { ReactNode } from "react";
import { NotificationProvider } from "@/components/notifications";

import { I18nProvider } from "@/lib/i18n";

import "./styles.css";
import "./v2.css";

export const metadata: Metadata = {
  title: "DocReview RAG",
  description: "Evidence-first SEC and DART filing review",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ko">
      <body><I18nProvider><NotificationProvider>{children}</NotificationProvider></I18nProvider></body>
    </html>
  );
}
