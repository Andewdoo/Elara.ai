import { LiveResearchView } from "@/components/app/live-research-view";

export default async function VerifyRunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;

  return <LiveResearchView runId={runId} />;
}
