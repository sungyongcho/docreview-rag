"use client";
import { CircleAlert, CircleCheck, Info, BriefcaseBusiness, TriangleAlert } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { NotificationKind } from "@/lib/notification-registry";

const ICONS = { error: CircleAlert, warning: TriangleAlert, success: CircleCheck, info: Info, job: BriefcaseBusiness };
const LABELS = { error: "Error", warning: "Warning", success: "Success", info: "Information", job: "Job" };
/** Share accessible kind pictograms between the banner and persistent history. */
export function NotificationIcon({ kind }: { kind: NotificationKind }) {
  const { t } = useI18n();const Icon = ICONS[kind];
  return <span className={`notification-kind ${kind}`} role="img" aria-label={t(LABELS[kind])}><Icon size={17} aria-hidden="true" /></span>;
}
