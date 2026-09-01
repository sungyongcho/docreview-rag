import type { Metadata } from "next";
import type { ReactNode } from "react";
import { NotificationProvider } from "@/components/notifications";

import "./styles.css";

export const metadata: Metadata = {
  title: "DocReview",
  description: "Evidence-first SEC and DART filing review",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body><NotificationProvider>{children}</NotificationProvider></body>
    </html>
  );
}
