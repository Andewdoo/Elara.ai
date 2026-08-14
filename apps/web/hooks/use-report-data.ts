"use client";

import { useQuery } from "@tanstack/react-query";

import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { apiBaseUrl, apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";
import type { ReportRecord, SourceGraphRecord, SourceRecord } from "@/lib/report-types";
import type { VerificationRun } from "@/hooks/use-run-events";

export function useReportData(runId: string, { demoOnly = false }: { demoOnly?: boolean } = {}) {
  const { user, loading: authLoading } = useFirebaseAuth();
  const request = async <T,>(demoPath: string, privatePath: string): Promise<T> => {
    const demoResponse = await fetch(`${apiBaseUrl}${demoPath}`);
    if (demoResponse.ok) return demoResponse.json() as Promise<T>;
    if (demoOnly) throw new Error(await apiErrorMessage(demoResponse));
    if (demoResponse.status !== 404) throw new Error(await apiErrorMessage(demoResponse));
    if (!user) throw new Error("Sign in to view this report.");
    const response = await authenticatedApiFetch(user, privatePath);
    if (!response.ok) throw new Error(await apiErrorMessage(response));
    return response.json() as Promise<T>;
  };
  const enabled = Boolean(runId) && (demoOnly || !authLoading);
  const queryScope = demoOnly ? "demo" : user?.uid ?? "public";
  const run = useQuery({ queryKey: ["run", runId, queryScope], enabled, queryFn: () => request<VerificationRun>(`/v1/demo-runs/${runId}`, `/v1/verifications/${runId}`) });
  const completed = run.data?.status === "COMPLETED";
  const report = useQuery({ queryKey: ["report", runId, queryScope], enabled: enabled && completed, queryFn: () => request<ReportRecord>(`/v1/demo-runs/${runId}/report`, `/v1/verifications/${runId}/report`) });
  const sources = useQuery({ queryKey: ["sources", runId, queryScope], enabled: enabled && completed, queryFn: () => request<{ sources: SourceRecord[] }>(`/v1/demo-runs/${runId}/sources`, `/v1/verifications/${runId}/sources`) });
  const sourceGraph = useQuery({ queryKey: ["source-graph", runId, queryScope], enabled: enabled && completed, queryFn: () => request<SourceGraphRecord>(`/v1/demo-runs/${runId}/source-graph`, `/v1/verifications/${runId}/source-graph`) });
  return { run, report, sources, sourceGraph, authLoading: demoOnly ? false : authLoading, authenticated: demoOnly || Boolean(user) };
}
