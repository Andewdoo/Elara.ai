"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Archive, Download, MessageSquareWarning } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { useReportActions, type FeedbackCategory } from "@/hooks/use-report-actions";

const categories: Array<{ value: FeedbackCategory; label: string }> = [
  { value: "CORRECTION", label: "Correction" },
  { value: "MISSED_EVIDENCE", label: "Missed evidence" },
  { value: "APPEAL", label: "Appeal" },
  { value: "BROKEN_CITATION", label: "Broken citation" },
];

const feedbackSchema = z.object({
  category: z.enum(["CORRECTION", "MISSED_EVIDENCE", "APPEAL", "BROKEN_CITATION"]),
  message: z.string().trim().min(3, "Describe the issue in at least three characters.").max(10000),
  sourceUrl: z.union([z.literal(""), z.string().trim().url("Enter a valid source URL.")]),
});

type FeedbackFormValues = z.infer<typeof feedbackSchema>;

export function ReportHeaderActions({ runId, saved }: { runId: string; saved: boolean }) {
  const actions = useReportActions(runId);
  const exportReport = async () => {
    const result = await actions.exportJson.mutateAsync();
    if (result.download_url) window.open(result.download_url, "_blank", "noopener,noreferrer");
  };
  return <div className="flex flex-wrap items-center gap-2">
    <Button size="sm" variant="secondary" disabled={actions.save.isPending} onClick={() => actions.save.mutate(!saved)}>
      <Archive className="mr-2 h-4 w-4" />{saved ? "Remove saved" : "Save report"}
    </Button>
    <Button size="sm" variant="secondary" disabled={actions.exportJson.isPending} onClick={exportReport}>
      <Download className="mr-2 h-4 w-4" />{actions.exportJson.isPending ? "Preparing JSON" : "Export JSON"}
    </Button>
    {(actions.save.error || actions.exportJson.error) && <span role="alert" className="text-xs text-red-700">{String(actions.save.error?.message ?? actions.exportJson.error?.message)}</span>}
    {actions.exportJson.data && <span className="text-xs text-muted-foreground">SHA-256 {actions.exportJson.data.content_hash.slice(0, 12)}…</span>}
  </div>;
}

export function FeedbackControls({ runId }: { runId: string }) {
  const actions = useReportActions(runId);
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<FeedbackFormValues>({
    resolver: zodResolver(feedbackSchema),
    defaultValues: { category: "CORRECTION", message: "", sourceUrl: "" },
  });
  return <form className="grid gap-3 rounded-md border bg-muted/30 p-4" onSubmit={handleSubmit(async (values) => {
    actions.feedback.reset();
    try {
      await actions.feedback.mutateAsync({ category: values.category, message: values.message, ...(values.sourceUrl ? { source_url: values.sourceUrl } : {}) });
      reset({ category: values.category, message: "", sourceUrl: "" });
    } catch {
      // Mutation state renders the server-authoritative error below.
    }
  })} noValidate>
    <div className="flex items-center gap-2"><MessageSquareWarning className="h-4 w-4 text-primary"/><h3 className="text-sm font-semibold">Feedback and correction controls</h3></div>
    <div className="grid gap-2 md:grid-cols-[200px_1fr]">
      <select className="rounded-md border bg-white px-3 py-2 text-sm" {...register("category")} aria-label="Feedback category">
        {categories.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
      <div className="grid gap-1"><input className="rounded-md border px-3 py-2 text-sm" type="url" {...register("sourceUrl")} placeholder="Relevant source URL (optional)" />{errors.sourceUrl && <span className="text-xs text-destructive">{errors.sourceUrl.message}</span>}</div>
    </div>
    <div className="grid gap-1"><textarea className="min-h-24 rounded-md border p-3 text-sm" {...register("message")} placeholder="Describe the correction, evidence, appeal, or citation problem." />{errors.message && <span className="text-xs text-destructive">{errors.message.message}</span>}</div>
    <div className="flex items-center gap-3"><Button size="sm" type="submit" disabled={isSubmitting || actions.feedback.isPending}>{isSubmitting || actions.feedback.isPending ? "Submitting" : "Submit feedback"}</Button>{actions.feedback.isSuccess && <span className="text-xs text-emerald-700">Feedback recorded for review.</span>}{actions.feedback.error && <span role="alert" className="text-xs text-red-700">{actions.feedback.error.message}</span>}</div>
  </form>;
}
