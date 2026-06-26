"use client";

import { useQuery } from "@tanstack/react-query";

import { mockedHistory, mockedReport } from "@/lib/mock-report";

export function useMockedReport(runId: string) {
  return useQuery({
    queryKey: ["report", runId],
    queryFn: async () => ({ ...mockedReport, runId }),
  });
}

export function useMockedHistory() {
  return useQuery({
    queryKey: ["history", "mocked"],
    queryFn: async () => mockedHistory,
  });
}
