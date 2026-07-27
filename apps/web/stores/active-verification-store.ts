import { create } from "zustand";

import type { RunProgressEvent } from "@/hooks/use-run-events";

const terminalRunStatuses = ["COMPLETED", "FAILED", "CANCELLED"] as const;

type ActiveVerificationState = {
  runId: string | null;
  isActive: boolean;
  latestEvent: RunProgressEvent | null;
  resume: (runId: string) => void;
  recordProgress: (event: RunProgressEvent) => void;
  finish: (runId: string) => void;
};

function isTerminal(stage: RunProgressEvent["stage"]) {
  return terminalRunStatuses.includes(stage as (typeof terminalRunStatuses)[number]);
}

function isNewerProgress(event: RunProgressEvent, current: RunProgressEvent | null) {
  if (!current || current.run_id !== event.run_id || isTerminal(event.stage)) return true;
  const eventTime = Date.parse(event.created_at);
  const currentTime = Date.parse(current.created_at);
  if (Number.isFinite(eventTime) && Number.isFinite(currentTime) && eventTime !== currentTime) {
    return eventTime > currentTime;
  }
  return event.completed_steps >= current.completed_steps;
}

// Intentionally in-memory only: the active run is browser-session UI state, not durable data.
export const useActiveVerificationStore = create<ActiveVerificationState>((set) => ({
  runId: null,
  isActive: false,
  latestEvent: null,
  resume: (runId) => set((current) => (
    current.runId === runId
      ? { isActive: true }
      : { runId, isActive: true, latestEvent: null }
  )),
  recordProgress: (event) => set((current) => (
    isNewerProgress(event, current.latestEvent)
      ? { runId: event.run_id, isActive: !isTerminal(event.stage), latestEvent: event }
      : current
  )),
  finish: (runId) => set((current) => (
    current.runId === runId ? { isActive: false } : current
  )),
}));
