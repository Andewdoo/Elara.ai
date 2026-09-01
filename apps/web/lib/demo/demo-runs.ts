/** The Demo archive is limited to the owner-designated shared report collection. */
export const DEMO_RUN_LIMIT = 12;
export const DEMO_ARCHIVE_MANIFEST_PATH = "/demo-archive/manifest.json";

export type DemoArchiveResource = "run" | "report" | "sources" | "source-graph";

export function demoArchiveRunResourcePath(runId: string, resource: DemoArchiveResource) {
  return `/demo-archive/runs/${encodeURIComponent(runId)}/${resource}.json`;
}

export type DemoRun = {
  run_id: string;
  title: string;
  submitted_text_preview: string | null;
  research_depth: string;
  verdict: string | null;
  evidence_reviewed_at: string | null;
  updated_at: string;
};
