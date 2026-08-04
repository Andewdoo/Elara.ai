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
  return <section className="grid gap-4 border-t pt-5" aria-labelledby="score-summary-heading">
    <div className="flex flex-wrap items-end justify-between gap-2"><div><p className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-primary">Server calculation records</p><h2 id="score-summary-heading" className="mt-1 font-editorial text-2xl font-semibold">Score summary</h2></div><p className="max-w-md text-xs leading-5 text-muted-foreground">Non-aggregated role scores and numerical checks from the durable report record.</p></div>
    <div className="grid gap-4 xl:grid-cols-2">
    <Chart title="Score breakdown" data={scores} dataKey="value" color="hsl(var(--primary))" domain={[0, 100]} />
    <DualChart title="Evidence balance" data={balance} />
    <Chart title="Confidence components" data={[...components, ...penalties]} dataKey="value" color="hsl(var(--foreground))" domain={[0, 100]} />
    <Chart title="Research coverage" data={coverageData} dataKey="value" color="hsl(var(--accent))" domain={[0, 100]} />
    <NumericalChart data={numerical} />
    </div>
  </section>;
}

function Chart({ title, data, dataKey, color, domain }: { title: string; data: Array<Record<string, unknown>>; dataKey: string; color: string; domain?: [number, number] }) {
  return <div className="h-72 border bg-card p-4"><p className="mb-2 font-editorial text-lg font-semibold">{title}</p>{data.length ? <><div aria-hidden="true" className="h-[85%]"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ left: 28 }}><CartesianGrid stroke="hsl(var(--border))" strokeDasharray="2 4" vertical={false}/><XAxis type="number" domain={domain} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}/><YAxis type="category" dataKey="label" width={118} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}/><Tooltip contentStyle={{ borderRadius: 0, borderColor: "hsl(var(--border))", background: "hsl(var(--card))" }}/><Bar dataKey={dataKey} fill={color}/></BarChart></ResponsiveContainer></div><AccessibleTable title={title} data={data} keys={[dataKey]}/></> : <p className="border border-dashed p-4 text-sm text-muted-foreground">No matching server calculation records were stored.</p>}</div>;
}

function DualChart({ title, data }: { title: string; data: Array<Record<string, unknown>> }) {
  return <div className="h-72 border bg-card p-4"><p className="mb-2 font-editorial text-lg font-semibold">{title}</p>{data.length ? <><div aria-hidden="true" className="h-[85%]"><ResponsiveContainer width="100%" height="100%"><BarChart data={data}><CartesianGrid stroke="hsl(var(--border))" strokeDasharray="2 4" vertical={false}/><XAxis dataKey="claim" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}/><YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}/><Tooltip contentStyle={{ borderRadius: 0, borderColor: "hsl(var(--border))", background: "hsl(var(--card))" }}/><Legend/><Bar dataKey="supporting" fill="hsl(var(--primary))"/><Bar dataKey="contradicting" fill="hsl(var(--destructive))"/></BarChart></ResponsiveContainer></div><AccessibleTable title={title} data={data} keys={["supporting", "contradicting"]}/></> : <p className="border border-dashed p-4 text-sm text-muted-foreground">No claim-level evidence balance records were stored.</p>}</div>;
}

function NumericalChart({ data }: { data: Array<Record<string, unknown>> }) {
  return <div className="min-h-72 border bg-card p-4 xl:col-span-2"><p className="mb-2 font-editorial text-lg font-semibold">Numerical audit</p>{data.length ? <><div aria-hidden="true" className="h-56"><ResponsiveContainer width="100%" height="100%"><BarChart data={data}><CartesianGrid stroke="hsl(var(--border))" strokeDasharray="2 4" vertical={false}/><XAxis dataKey="label" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}/><YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}/><Tooltip contentStyle={{ borderRadius: 0, borderColor: "hsl(var(--border))", background: "hsl(var(--card))" }}/><Legend/><Bar dataKey="claimed" name="Claimed value" fill="hsl(var(--accent))"/><Bar dataKey="computed" name="Source-computed value" fill="hsl(var(--foreground))"/></BarChart></ResponsiveContainer></div><AccessibleTable title="Numerical audit" data={data} keys={["claimed", "computed", "units", "denominator", "period"]}/></> : <p className="border border-dashed p-4 text-sm text-muted-foreground">No numerical calculation records were stored.</p>}</div>;
}

function AccessibleTable({ title, data, keys }: { title: string; data: Array<Record<string, unknown>>; keys: string[] }) {
  return <div className="sr-only"><table><caption>{title} data from server calculation records</caption><thead><tr><th scope="col">Item</th>{keys.map((key) => <th scope="col" key={key}>{key.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{data.map((row, index) => <tr key={`${String(row.label ?? row.claim)}-${index}`}><th scope="row">{String(row.label ?? row.claim ?? index + 1)}</th>{keys.map((key) => <td key={key}>{String(row[key] ?? "not recorded")}</td>)}</tr>)}</tbody></table></div>;
}
