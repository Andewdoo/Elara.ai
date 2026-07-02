"use client";

import { useQuery } from "@tanstack/react-query";

import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";
import type { ReportRecord, SourceGraphRecord, SourceRecord } from "@/lib/report-types";
import type { VerificationRun } from "@/hooks/use-run-events";

export function useReportData(runId: string) {
  const { user, loading: authLoading } = useFirebaseAuth();
  const request = async <T,>(path: string): Promise<T> => {
    if (!user) throw new Error("Sign in to view this report.");
    const response = await authenticatedApiFetch(user, path);
    if (!response.ok) throw new Error(await apiErrorMessage(response));
    return response.json() as Promise<T>;
  };
  const enabled = Boolean(user && runId);
  const run = useQuery({ queryKey: ["run", runId], enabled, queryFn: () => request<VerificationRun>(`/v1/verifications/${runId}`) });
  const report = useQuery({ queryKey: ["report", runId], enabled, queryFn: () => request<ReportRecord>(`/v1/verifications/${runId}/report`) });
  const sources = useQuery({ queryKey: ["sources", runId], enabled, queryFn: () => request<{ sources: SourceRecord[] }>(`/v1/verifications/${runId}/sources`) });
  const sourceGraph = useQuery({ queryKey: ["source-graph", runId], enabled, queryFn: () => request<SourceGraphRecord>(`/v1/verifications/${runId}/source-graph`) });
  return { run, report, sources, sourceGraph, authLoading, authenticated: Boolean(user) };
}
