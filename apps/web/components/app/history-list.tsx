"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";

type HistoryItem = {
  run_id: string; status: string; input_type: string; research_depth: string;
  title: string | null; submitted_text_preview: string | null; verdict: string | null;
  verdict_confidence: number | null; evidence_reviewed_at: string | null;
  created_at: string; updated_at: string; saved_at: string | null;
};
type HistoryResponse = { items: HistoryItem[]; total: number; page: number; page_size: number };

export function HistoryList({ savedOnly = false }: { savedOnly?: boolean }) {
  const { user, loading } = useFirebaseAuth();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [depth, setDepth] = useState("all");
  const [verdict, setVerdict] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [sort, setSort] = useState("recent");
  const [page, setPage] = useState(1);
  const params = new URLSearchParams({ page: String(page), page_size: "20", sort, ...(savedOnly ? { saved_only: "true" } : {}) });
  if (query.trim()) params.set("query", query.trim());
  if (status !== "all") params.set("status", status);
  if (depth !== "all") params.set("research_depth", depth);
  if (verdict.trim()) params.set("verdict", verdict.trim());
  if (createdFrom) params.set("created_from", new Date(`${createdFrom}T00:00:00`).toISOString());
  if (createdTo) params.set("created_to", new Date(`${createdTo}T23:59:59.999`).toISOString());
  const key = ["history", { query, status, depth, verdict, createdFrom, createdTo, sort, page, savedOnly }];
  const history = useQuery({
    queryKey: key,
    enabled: Boolean(user),
    queryFn: async () => {
      const response = await authenticatedApiFetch(user!, `/v1/history?${params.toString()}`);
      if (!response.ok) throw new Error(await apiErrorMessage(response));
      return response.json() as Promise<HistoryResponse>;
    },
  });
  const action = useMutation({
    mutationFn: async ({ runId, kind }: { runId: string; kind: "save" | "unsave" | "delete" }) => {
      const path = kind === "delete" ? `/v1/verifications/${runId}` : `/v1/verifications/${runId}/save`;
      const response = await authenticatedApiFetch(user!, path, { method: kind === "save" ? "POST" : "DELETE" });
      if (!response.ok) throw new Error(await apiErrorMessage(response));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["history"] }),
  });
  const resetPage = (setter: (value: string) => void) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setter(event.target.value); setPage(1); };

  return <div className="grid gap-4">
    {!savedOnly && <Card><CardHeader><CardTitle>History filters</CardTitle></CardHeader><CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <label className="flex items-center rounded-md border bg-white px-3"><Search className="h-4 w-4 text-muted-foreground" aria-hidden="true"/><input aria-label="Search verification history" className="min-w-0 flex-1 px-2 py-2 text-sm outline-none" value={query} onChange={resetPage(setQuery)} placeholder="Search runs or verdicts" /></label>
      <select aria-label="Filter history by status" className="rounded-md border bg-white px-3 py-2 text-sm" value={status} onChange={resetPage(setStatus)}><option value="all">All statuses</option>{["QUEUED", "VALIDATING", "DECOMPOSING", "RESEARCHING", "EXTRACTING", "ANALYZING_PROVENANCE", "SCORING", "SYNTHESIZING", "AUDITING", "COMPLETED", "FAILED", "CANCELLED"].map((value) => <option key={value} value={value}>{value.toLowerCase().replaceAll("_", " ")}</option>)}</select>
      <select aria-label="Filter history by research depth" className="rounded-md border bg-white px-3 py-2 text-sm" value={depth} onChange={resetPage(setDepth)}><option value="all">All depths</option>{["QUICK", "STANDARD", "DEEP"].map((value) => <option key={value} value={value}>{value.toLowerCase()}</option>)}</select>
      <select aria-label="Sort verification history" className="rounded-md border bg-white px-3 py-2 text-sm" value={sort} onChange={resetPage(setSort)}><option value="recent">Most recent</option><option value="oldest">Oldest first</option><option value="confidence">Confidence</option></select>
      <input className="rounded-md border bg-white px-3 py-2 text-sm" value={verdict} onChange={resetPage(setVerdict)} placeholder="Filter verdict" aria-label="Filter by verdict" />
      <label className="grid gap-1 text-xs text-muted-foreground">Created from<input className="rounded-md border bg-white px-3 py-2 text-sm text-foreground" type="date" value={createdFrom} onChange={resetPage(setCreatedFrom)} /></label>
      <label className="grid gap-1 text-xs text-muted-foreground">Created to<input className="rounded-md border bg-white px-3 py-2 text-sm text-foreground" type="date" value={createdTo} onChange={resetPage(setCreatedTo)} /></label>
    </CardContent></Card>}
    <Card><CardHeader><CardTitle>{savedOnly ? "Saved reports" : "Verification history"}</CardTitle></CardHeader><CardContent className="grid gap-3">
      {loading || history.isLoading ? <p className="text-sm text-muted-foreground">Loading account history…</p> : !user ? <p className="text-sm text-muted-foreground">Sign in to view your report history.</p> : history.error ? <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-red-700"><span>{history.error.message}</span><Button size="sm" variant="secondary" onClick={() => void history.refetch()}>Retry</Button></div> : history.data?.items.length ? history.data.items.map((item) => <article key={item.run_id} className="grid gap-3 rounded-md border p-4 md:grid-cols-[1fr_auto]">
        <div><div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>{item.status}</span><span>{item.research_depth}</span>{item.saved_at && <span className="text-primary">Saved</span>}</div><Link className="mt-1 block font-semibold hover:text-primary" href={item.status === "COMPLETED" ? `/report/${item.run_id}` : `/verify/${item.run_id}`}>{item.title ?? item.submitted_text_preview ?? "Untitled verification"}</Link><p className="mt-1 text-sm text-muted-foreground">{item.verdict ?? "No verdict yet"}{item.verdict_confidence == null ? "" : ` · confidence ${item.verdict_confidence}`}</p><p className="mt-1 text-xs text-muted-foreground">Created {new Date(item.created_at).toLocaleString()}</p></div>
        <div className="flex items-center gap-2"><Button size="sm" variant="secondary" disabled={action.isPending || item.status !== "COMPLETED"} onClick={() => action.mutate({ runId: item.run_id, kind: item.saved_at ? "unsave" : "save" })}><Archive className="mr-2 h-4 w-4"/>{item.saved_at ? "Unsave" : "Save"}</Button><Button size="icon" variant="ghost" aria-label="Delete report" disabled={action.isPending || !["COMPLETED", "FAILED", "CANCELLED"].includes(item.status)} onClick={() => { if (window.confirm("Delete this report and its private exports?")) action.mutate({ runId: item.run_id, kind: "delete" }); }}><Trash2 className="h-4 w-4"/></Button></div>
      </article>) : <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">{savedOnly ? "No saved reports yet." : "No verification runs match these filters."}</p>}
      {action.error && <p role="alert" className="text-sm text-red-700">{action.error.message}</p>}
      {history.data && history.data.total > history.data.page_size && <div className="flex items-center justify-between"><Button variant="secondary" size="sm" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Previous</Button><span className="text-xs text-muted-foreground">Page {page} of {Math.ceil(history.data.total / history.data.page_size)}</span><Button variant="secondary" size="sm" disabled={page * history.data.page_size >= history.data.total} onClick={() => setPage((value) => value + 1)}>Next</Button></div>}
    </CardContent></Card>
  </div>;
}
