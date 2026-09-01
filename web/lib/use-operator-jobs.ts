"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useNotifications } from "@/components/notifications";
import { cancelOperatorJob, getOperatorJobs, retryOperatorJob } from "./api";
import { desktopJobNotificationsEnabled } from "./storage";
import type { OperatorJob, OperatorJobBoard } from "./types";

const EMPTY_BOARD: OperatorJobBoard = { jobs: [], active_count: 0, queued_count: 0 };

function jobLabel(job: OperatorJob): string {
  return job.kind.replaceAll("_", " ").replace(/\b\w/g, (value) => value.toUpperCase());
}

function desktopNotify(job: OperatorJob): void {
  if (!desktopJobNotificationsEnabled() || typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  if (!(["succeeded", "failed", "interrupted", "cancelled"] as string[]).includes(job.status)) {
    return;
  }
  new Notification(`DocReview · ${jobLabel(job)}`, { body: `${job.status}: ${job.message}` });
}

export function useOperatorJobs(
  enabled: boolean,
  onTerminal?: () => void | Promise<void>,
) {
  const [board, setBoard] = useState<OperatorJobBoard>(EMPTY_BOARD);
  const [loading, setLoading] = useState(enabled);
  const previous = useRef<Map<string, string>>(new Map());
  const initialized = useRef(false);
  const { notify } = useNotifications();

  const apply = useCallback((next: OperatorJobBoard) => {
    if (initialized.current) {
      for (const job of next.jobs) {
        const before = previous.current.get(job.job_id);
        if (before === job.status) continue;
        const tone = job.status === "succeeded"
          ? "success"
          : job.status === "failed" || job.status === "interrupted"
            ? "error"
            : job.status === "cancelled"
              ? "warning"
              : "info";
        notify(`${jobLabel(job)} · ${job.status}: ${job.message}`, tone, `job:${job.job_id}:${job.status}`);
        desktopNotify(job);
        if (["succeeded", "failed", "interrupted", "cancelled"].includes(job.status)) {
          void onTerminal?.();
        }
      }
    }
    previous.current = new Map(next.jobs.map((job) => [job.job_id, job.status]));
    initialized.current = true;
    setBoard(next);
    setLoading(false);
  }, [notify, onTerminal]);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      apply(await getOperatorJobs());
    } catch (reason) {
      setLoading(false);
      notify(reason instanceof Error ? reason.message : "Job activity could not be loaded.", "error", "jobs-refresh");
    }
  }, [apply, enabled, notify]);

  useEffect(() => {
    if (!enabled) {
      setBoard(EMPTY_BOARD);
      setLoading(false);
      return;
    }
    let stopped = false;
    let timer = 0;
    const poll = async () => {
      await refresh();
      if (stopped) return;
      const active = board.active_count > 0 || board.queued_count > 0;
      const delay = document.visibilityState === "visible" ? active ? 1_000 : 5_000 : 15_000;
      timer = window.setTimeout(poll, delay);
    };
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [enabled, refresh, board.active_count, board.queued_count]);

  const retry = useCallback(async (jobId: string) => {
    try {
      await retryOperatorJob(jobId);
      await refresh();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Job retry failed.", "error", `job-retry:${jobId}`);
    }
  }, [notify, refresh]);

  const cancel = useCallback(async (jobId: string) => {
    try {
      await cancelOperatorJob(jobId);
      await refresh();
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Job cancellation failed.", "error", `job-cancel:${jobId}`);
    }
  }, [notify, refresh]);

  return { board, loading, refresh, retry, cancel };
}
