"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";

export type FeedbackCategory = "CORRECTION" | "MISSED_EVIDENCE" | "APPEAL" | "BROKEN_CITATION";

type ExportRecord = {
  export_id: string;
  run_id: string;
  format: "JSON";
  content_hash: string;
  created_at: string;
  download_url: string | null;
  expires_at: string | null;
};

export function useReportActions(runId: string) {
  const { user } = useFirebaseAuth();
  const queryClient = useQueryClient();
  const request = async <T,>(path: string, init: RequestInit): Promise<T> => {
    if (!user) throw new Error("Sign in to update this report.");
    const response = await authenticatedApiFetch(user, path, init);
    if (!response.ok) throw new Error(await apiErrorMessage(response));
    return response.json() as Promise<T>;
  };
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["run", runId] }),
      queryClient.invalidateQueries({ queryKey: ["history"] }),
    ]);
  };
  const save = useMutation({
    mutationFn: (saved: boolean) => request(`/v1/verifications/${runId}/save`, { method: saved ? "POST" : "DELETE" }),
    onSuccess: invalidate,
  });
  const feedback = useMutation({
    mutationFn: (body: { category: FeedbackCategory; message: string; source_url?: string }) =>
      request(`/v1/verifications/${runId}/feedback`, { method: "POST", body: JSON.stringify(body) }),
  });
  const exportJson = useMutation({
    mutationFn: async () => {
      const created = await request<ExportRecord>(`/v1/verifications/${runId}/exports`, {
        method: "POST",
        body: JSON.stringify({ format: "JSON" }),
      });
      return request<ExportRecord>(`/v1/verifications/${runId}/exports/${created.export_id}`, { method: "GET" });
    },
  });
  return { save, feedback, exportJson };
}
