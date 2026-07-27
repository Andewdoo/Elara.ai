"use client";

import { LiveResearchView } from "@/components/app/live-research-view";
import { VerifyForm } from "@/components/app/verify-form";
import { useActiveVerificationStore } from "@/stores/active-verification-store";

export function VerifyRoute() {
  const activeRunId = useActiveVerificationStore((state) => (
    state.isActive ? state.runId : null
  ));

  return activeRunId ? <LiveResearchView runId={activeRunId} /> : <VerifyForm />;
}
