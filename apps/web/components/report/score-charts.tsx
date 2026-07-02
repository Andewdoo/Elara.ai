"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { CalculationRecord, ReportRecord } from "@/lib/report-types";

const labels: Record<string, string> = { article_factual_accuracy: "Evidence support", attribution_support: "Attribution support", quote_fidelity: "Quote fidelity", verdict_confidence: "Verdict confidence", source_independence: "Source independence", context_completeness: "Context completeness" };
const number = (value: unknown) => value === null || value === undefined || value === "" || Number.isNaN(Number(value)) ? null : Number(value);
const globalRecord = (rows: CalculationRecord[], name: string) => [...rows].reverse().find((row) => row.formula_name === name && row.atomic_claim_id === null);

export function ScoreCharts({ report }: { report: ReportRecord }) {
  const scores = Object.keys(labels).flatMap((name) => { const row = globalRecord(report.calculations, name); const value = number(row?.result.score); return row && value !== null ? [{ label: labels[name], value, calculationId: row.id }] : []; });
  const balance = report.atomic_claims.map((claim) => {
    const support = report.calculations.find((row) => row.atomic_claim_id === claim.id && row.formula_name === "supporting_weight");
    const contradict = report.calculations.find((row) => row.atomic_claim_id === claim.id && row.formula_name === "contradicting_weight");
    return { claim: claim.claim_text.slice(0, 24), supporting: number(support?.result.P) ?? 0, contradicting: number(contradict?.result.N) ?? 0 };
  });
  const confidence = globalRecord(report.calculations, "verdict_confidence");
  const components = ["coverage", "average_quality", "independence", "consistency", "primary_access"].flatMap((key) => { const value = number(confidence?.inputs[key]); return value === null ? [] : [{ label: key.replaceAll("_", " "), value }]; });
  const penalties = confidence?.inputs.penalties && typeof confidence.inputs.penalties === "object" ? Object.entries(confidence.inputs.penalties as Record<string, unknown>).flatMap(([key, raw]) => { const value = number(raw); return value === null ? [] : [{ label: key.replaceAll("_", " "), value }]; }) : [];
  const coverage = globalRecord(report.calculations, "research_coverage");
  const coverageData = ["adequate_evidence", "insufficient_evidence", "inaccessible_source_impact"].flatMap((key) => { const value = number(coverage?.result[key]); return value === null ? [] : [{ label: key.replaceAll("_", " "), value }]; });
  const numerical = report.calculations.filter((row) => row.formula_name.startsWith("numerical_")).flatMap((row) => {
    const computed = number(row.result.value);
    const claimed = number(row.result.claimed_value ?? row.inputs.claimed_value);
    const values = Array.isArray(row.inputs.values) ? row.inputs.values as Array<Record<string, unknown>> : [];
    const denominator = values.find((item) => item.role === "denominator")?.value;
    const period = values.map((item) => item.period).filter(Boolean).join(" / ");
    return computed === null && claimed === null ? [] : [{ label: row.formula_name.replace("numerical_", ""), computed, claimed, units: row.units ?? "not recorded", denominator: denominator ?? "not applicable", period: period || "not recorded" }];
  });
  return <div className="grid gap-4 xl:grid-cols-2">
    <Chart title="Score breakdown" data={scores} dataKey="value" color="#0f766e" domain={[0, 100]} />
    <DualChart title="Evidence balance" data={balance} />
    <Chart title="Confidence components" data={[...components, ...penalties]} dataKey="value" color="#2563eb" domain={[0, 100]} />
    <Chart title="Research coverage" data={coverageData} dataKey="value" color="#d97706" domain={[0, 100]} />
    <NumericalChart data={numerical} />
  </div>;
}

function Chart({ title, data, dataKey, color, domain }: { title: string; data: Array<Record<string, unknown>>; dataKey: string; color: string; domain?: [number, number] }) {
  return <div className="h-72 rounded-lg border bg-white p-3"><p className="mb-2 text-sm font-semibold">{title}</p>{data.length ? <ResponsiveContainer width="100%" height="88%"><BarChart data={data} layout="vertical" margin={{ left: 28 }}><CartesianGrid strokeDasharray="3 3"/><XAxis type="number" domain={domain}/><YAxis type="category" dataKey="label" width={118} tick={{ fontSize: 10 }}/><Tooltip/><Bar dataKey={dataKey} fill={color} radius={[0, 4, 4, 0]}/></BarChart></ResponsiveContainer> : <p className="text-sm text-muted-foreground">No matching server calculation records were stored.</p>}</div>;
}

function DualChart({ title, data }: { title: string; data: Array<Record<string, unknown>> }) {
  return <div className="h-72 rounded-lg border bg-white p-3"><p className="mb-2 text-sm font-semibold">{title}</p><ResponsiveContainer width="100%" height="88%"><BarChart data={data}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="claim" tick={{ fontSize: 10 }}/><YAxis/><Tooltip/><Legend/><Bar dataKey="supporting" fill="#0f766e"/><Bar dataKey="contradicting" fill="#be123c"/></BarChart></ResponsiveContainer></div>;
}

function NumericalChart({ data }: { data: Array<Record<string, unknown>> }) {
  return <div className="min-h-72 rounded-lg border bg-white p-3"><p className="mb-2 text-sm font-semibold">Numerical audit</p>{data.length ? <><div className="h-56"><ResponsiveContainer width="100%" height="100%"><BarChart data={data}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="label" tick={{ fontSize: 10 }}/><YAxis/><Tooltip/><Legend/><Bar dataKey="claimed" name="Claimed value" fill="#d97706"/><Bar dataKey="computed" name="Source-computed value" fill="#7c3aed"/></BarChart></ResponsiveContainer></div>{data.map((row) => <p key={String(row.label)} className="text-xs text-muted-foreground">{String(row.label)}: units {String(row.units)}, denominator {String(row.denominator)}, period {String(row.period)}</p>)}</> : <p className="text-sm text-muted-foreground">No numerical calculation records were stored.</p>}</div>;
}
