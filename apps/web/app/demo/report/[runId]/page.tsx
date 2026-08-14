import { ReportRoute } from "@/components/report/report-route";

export default async function DemoReportPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;

  return <ReportRoute runId={runId} demoOnly />;
}
