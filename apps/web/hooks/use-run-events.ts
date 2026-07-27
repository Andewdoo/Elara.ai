"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { apiBaseUrl, apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";
import { useActiveVerificationStore } from "@/stores/active-verification-store";

export const terminalRunStatuses = ["COMPLETED", "FAILED", "CANCELLED"] as const;
export type TerminalRunStatus = (typeof terminalRunStatuses)[number];
export type RunStatus =
  | "QUEUED"
  | "VALIDATING"
  | "DECOMPOSING"
  | "RESEARCHING"
  | "EXTRACTING"
  | "ANALYZING_PROVENANCE"
  | "SCORING"
  | "SYNTHESIZING"
  | "AUDITING"
  | TerminalRunStatus;

export type VerificationRun = {
  run_id: string;
  status: RunStatus;
  input_type: string;
  research_depth: string;
  title: string | null;
  verdict: string | null;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  cancellation_requested_at: string | null;
  failure_code: string | null;
  failure_message: string | null;
  updated_at: string;
  saved_at: string | null;
  is_owner: boolean;
};

export type RunProgressEvent = {
  run_id: string;
  stage: RunStatus;
  message: string;
  completed_steps: number;
  total_steps: number;
  source_counts: Record<string, number>;
  inaccessible_count: number;
  event_type: string;
  created_at: string;
};

type ConnectionState = "connecting" | "connected" | "reconnecting" | "polling" | "closed";

function isTerminal(status: RunStatus | undefined): status is TerminalRunStatus {
  return Boolean(status && terminalRunStatuses.includes(status as TerminalRunStatus));
}

export function useRunEvents(runId: string) {
  const { user } = useFirebaseAuth();
  const queryClient = useQueryClient();
  const latestEvent = useActiveVerificationStore((state) => (
    state.runId === runId ? state.latestEvent : null
  ));
  const resumeVerification = useActiveVerificationStore((state) => state.resume);
  const recordProgress = useActiveVerificationStore((state) => state.recordProgress);
  const finishVerification = useActiveVerificationStore((state) => state.finish);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [pollingFallback, setPollingFallback] = useState(false);
  const reconnectAttempts = useRef(0);
  const invalidatedTerminalResult = useRef<string | null>(null);

  useEffect(() => {
    resumeVerification(runId);
  }, [resumeVerification, runId]);

  const runQuery = useQuery({
    queryKey: ["run", runId],
    enabled: Boolean(user && runId),
    queryFn: async () => {
      if (!user) throw new Error("Sign in to view this verification.");
      const response = await authenticatedApiFetch(user, `/v1/verifications/${runId}`);
      if (!response.ok) throw new Error(await apiErrorMessage(response));
      return (await response.json()) as VerificationRun;
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return pollingFallback && !isTerminal(status) ? 3_000 : false;
    },
  });

  const progressHistoryQuery = useQuery({
    queryKey: ["run-progress", runId],
    enabled: Boolean(user && runId),
    queryFn: async () => {
      if (!user) throw new Error("Sign in to view this verification.");
      const response = await authenticatedApiFetch(user, `/v1/verifications/${runId}/progress`);
      if (!response.ok) throw new Error(await apiErrorMessage(response));
      return (await response.json()) as RunProgressEvent[];
    },
  });

  const refreshDurableResult = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["run", runId] }),
      queryClient.invalidateQueries({ queryKey: ["report", runId] }),
      queryClient.invalidateQueries({ queryKey: ["sources", runId] }),
      queryClient.invalidateQueries({ queryKey: ["source-graph", runId] }),
      queryClient.invalidateQueries({ queryKey: ["run-progress", runId] }),
    ]);
  }, [queryClient, runId]);

  useEffect(() => {
    const durableRun = runQuery.data;
    if (!durableRun || !isTerminal(durableRun.status)) return;
    finishVerification(runId);
    const resultVersion = `${durableRun.run_id}:${durableRun.status}:${durableRun.updated_at}`;
    if (invalidatedTerminalResult.current === resultVersion) return;
    invalidatedTerminalResult.current = resultVersion;
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["report", runId] }),
      queryClient.invalidateQueries({ queryKey: ["sources", runId] }),
      queryClient.invalidateQueries({ queryKey: ["source-graph", runId] }),
    ]);
  }, [finishVerification, queryClient, runId, runQuery.data]);

  useEffect(() => {
    if (!user || !runId || isTerminal(runQuery.data?.status)) {
      return;
    }

    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      let failed = false;
      source = new EventSource(`${apiBaseUrl}/v1/verifications/${runId}/events`, {
        withCredentials: true,
      });
      source.onopen = () => {
        setConnectionState("connected");
      };
      source.addEventListener("progress", (event) => {
        let progress: RunProgressEvent;
        try {
          progress = JSON.parse(event.data) as RunProgressEvent;
        } catch {
          reconnectOrPoll();
          return;
        }
        reconnectAttempts.current = 0;
        recordProgress(progress);
        queryClient.setQueryData<RunProgressEvent[]>(["run-progress", runId], (events = []) => {
          const alreadyRecorded = events.some(
            (existing) =>
              existing.created_at === progress.created_at &&
              existing.stage === progress.stage &&
              existing.event_type === progress.event_type,
          );
          return alreadyRecorded ? events : [...events, progress];
        });
        if (isTerminal(progress.stage)) {
          source?.close();
          setConnectionState("closed");
          void refreshDurableResult();
        }
      });

      const reconnectOrPoll = () => {
        if (failed || disposed) return;
        failed = true;
        source?.close();
        reconnectAttempts.current += 1;
        if (reconnectAttempts.current >= 3) {
          setPollingFallback(true);
          setConnectionState("polling");
          return;
        }
        setConnectionState("reconnecting");
        reconnectTimer = setTimeout(connect, 1_000 * 2 ** (reconnectAttempts.current - 1));
      };
      source.onerror = reconnectOrPoll;
      source.addEventListener("unavailable", reconnectOrPoll);
    };

    connect();
    return () => {
      disposed = true;
      source?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [queryClient, recordProgress, refreshDurableResult, runId, runQuery.data?.status, user]);

  const cancelMutation = useMutation({
    mutationFn: async () => {
      if (!user) throw new Error("Sign in to cancel this verification.");
      const response = await authenticatedApiFetch(user, `/v1/verifications/${runId}/cancel`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response));
      return response.json();
    },
    onSuccess: () => refreshDurableResult(),
  });

  const retryMutation = useMutation({
    mutationFn: async () => {
      if (!user) throw new Error("Sign in to retry this verification.");
      const response = await authenticatedApiFetch(user, `/v1/verifications/${runId}/retry`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response));
      return response.json() as Promise<{ run_id: string }>;
    },
  });

  return {
    runQuery,
    latestEvent,
    progressHistoryQuery,
    connectionState: isTerminal(runQuery.data?.status) ? "closed" : connectionState,
    pollingFallback,
    cancelMutation,
    retryMutation,
    refreshDurableResult,
  };
}
