"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Archive, CheckCircle2, Download, Loader2, MessageSquareWarning } from "lucide-react";
import { useState } from "react";
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
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const exportReport = async () => {
    const popup = window.open("", "_blank");
    if (popup) popup.opener = null;
    try {
      const result = await actions.exportJson.mutateAsync();
      if (!result.download_url) return popup?.close();
      if (popup) popup.location.href = result.download_url;
      else setFallbackUrl(result.download_url);
    } catch {
      popup?.close();
      // TanStack Query retains the authoritative mutation error for the alert below.
    }
  };
  return <div className="flex flex-wrap items-center gap-2">
    <Button className="h-11 flex-1 px-4 sm:flex-none" size="sm" variant="primary" disabled={actions.save.isPending} onClick={() => actions.save.mutate(!saved)}>
      {actions.save.isPending ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Archive className="h-4 w-4" aria-hidden="true" />}{actions.save.isPending ? "Updating" : saved ? "Remove saved" : "Save report"}
    </Button>
    <Button className="h-11 flex-1 border border-border bg-card px-4 sm:flex-none" size="sm" variant="secondary" disabled={actions.exportJson.isPending} onClick={() => void exportReport()}>
      {actions.exportJson.isPending ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Download className="h-4 w-4" aria-hidden="true" />}{actions.exportJson.isPending ? "Preparing JSON" : "Export JSON"}
    </Button>
    {(actions.save.error || actions.exportJson.error) && <span role="alert" className="w-full text-xs text-destructive">{String(actions.save.error?.message ?? actions.exportJson.error?.message)}</span>}
    {fallbackUrl && <a className="inline-flex min-h-11 w-full cursor-pointer items-center text-xs font-medium text-primary underline underline-offset-4" href={fallbackUrl} target="_blank" rel="noreferrer">Download prepared JSON</a>}
    {actions.exportJson.data && <span className="w-full font-mono text-[0.65rem] text-muted-foreground">SHA-256 {actions.exportJson.data.content_hash.slice(0, 12)}…</span>}
    {actions.exportHistory.data?.items.length ? <details className="w-full border-t pt-2 text-xs"><summary className="min-h-11 cursor-pointer py-3 font-medium">Export history ({actions.exportHistory.data.items.length})</summary><ul className="grid gap-2">{actions.exportHistory.data.items.map((item) => <li key={item.export_id} className="grid gap-2 border p-3"><span className="font-mono text-[0.65rem] leading-5">JSON / {new Date(item.created_at).toLocaleString()} / {item.content_hash.slice(0, 12)}…</span><button type="button" className="min-h-11 cursor-pointer justify-self-start font-medium text-primary underline underline-offset-4" onClick={async () => { const reopened = await actions.reopenExport.mutateAsync(item.export_id); if (reopened.download_url) setFallbackUrl(reopened.download_url); }}>Prepare download</button></li>)}</ul></details> : null}
  </div>;
}

export function FeedbackControls({ runId }: { runId: string }) {
  const actions = useReportActions(runId);
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<FeedbackFormValues>({
    resolver: zodResolver(feedbackSchema),
    defaultValues: { category: "CORRECTION", message: "", sourceUrl: "" },
  });
  return <form className="grid gap-4 border bg-muted/30 p-4 sm:p-5" onSubmit={handleSubmit(async (values) => {
    actions.feedback.reset();
    try {
      await actions.feedback.mutateAsync({ category: values.category, message: values.message, ...(values.sourceUrl ? { source_url: values.sourceUrl } : {}) });
      await actions.feedbackHistory.refetch();
      reset({ category: values.category, message: "", sourceUrl: "" });
    } catch { /* Mutation state renders the server-authoritative error. */ }
  })} noValidate>
    <div className="flex items-center gap-3 border-b pb-3"><MessageSquareWarning className="h-5 w-5 text-primary" aria-hidden="true"/><div><p className="font-mono text-[0.65rem] uppercase tracking-wide text-primary">Review channel</p><h3 className="font-editorial text-xl font-semibold">Feedback and correction controls</h3></div></div>
    <div className="grid gap-3 md:grid-cols-[200px_1fr]">
      <label className="grid gap-1.5 text-xs font-medium">Feedback category<select className="min-h-11 rounded-sm border bg-card px-3 text-sm" {...register("category")}>{categories.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label className="grid gap-1.5 text-xs font-medium">Relevant source URL (optional)<input className="min-h-11 rounded-sm border bg-card px-3 text-sm" type="url" {...register("sourceUrl")} aria-invalid={Boolean(errors.sourceUrl)} aria-describedby={errors.sourceUrl ? "feedback-source-error" : undefined}/>{errors.sourceUrl && <span id="feedback-source-error" className="text-xs text-destructive">{errors.sourceUrl.message}</span>}</label>
    </div>
    <label className="grid gap-1.5 text-xs font-medium">Correction or feedback details<textarea className="min-h-28 rounded-sm border bg-card p-3 text-sm leading-6" {...register("message")} aria-invalid={Boolean(errors.message)} aria-describedby={errors.message ? "feedback-message-error" : undefined}/>{errors.message && <span id="feedback-message-error" className="text-xs text-destructive">{errors.message.message}</span>}</label>
    <div className="flex flex-wrap items-center gap-3"><Button className="h-11" size="sm" type="submit" disabled={isSubmitting || actions.feedback.isPending}>{isSubmitting || actions.feedback.isPending ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}{isSubmitting || actions.feedback.isPending ? "Submitting" : "Submit feedback"}</Button>{actions.feedback.isSuccess && <span role="status" className="inline-flex items-center gap-1 text-xs text-primary"><CheckCircle2 className="h-4 w-4" aria-hidden="true" />Feedback recorded for review.</span>}{actions.feedback.error && <span role="alert" className="text-xs text-destructive">{actions.feedback.error.message}</span>}</div>
    <div className="grid gap-2 border-t pt-3" aria-label="Feedback status history"><p className="text-xs font-semibold">Submitted feedback</p>{actions.feedbackHistory.isLoading ? <p className="text-xs text-muted-foreground">Loading feedback status…</p> : actions.feedbackHistory.data?.items.length ? actions.feedbackHistory.data.items.map((item) => <div key={item.feedback_id} className="border bg-card p-3 text-xs"><strong>{item.category.replaceAll("_", " ")}</strong> / <span>{item.status}</span><p className="mt-1 leading-5 text-muted-foreground">{item.message}</p></div>) : <p className="text-xs text-muted-foreground">No feedback has been submitted for this report.</p>}</div>
  </form>;
}
