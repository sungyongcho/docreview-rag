"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useNotifications } from "./notifications";
import { useRetainedPanelActive } from "./retained-panel";

/** Use the shared upper-right toast; closing it never changes request eligibility. */
export function ProfileCompatibilityNotice({ message, conversationId }: { message: string; conversationId: string }) {
  const { t } = useI18n();
  const { notify, dismissNotice } = useNotifications();
  const active = useRetainedPanelActive();
  const [closed, setClosed] = useState(false);
  const key = `profile-compatibility:${conversationId}`;
  const translated = t(message);
  useEffect(() => {
    if (!active || closed) return;
    notify(translated, "warning", key, 0, {
      event: "profile-compatibility-warning",
      onDismiss: () => setClosed(true),
    });
    return () => dismissNotice(key);
  }, [active, closed, translated, key, notify, dismissNotice]);
  return null;
}
