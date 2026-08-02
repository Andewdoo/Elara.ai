import { BadgeCheck, BookOpenCheck, Crosshair, FileCheck2, Globe2, Quote, Scale, ShieldCheck } from "lucide-react";

const principles = [
  { id: "narrow-conclusion", number: "01", icon: Crosshair, title: "Narrow conclusion", text: "Each report answers one submitted claim or document. Its conclusion is limited to that scope and does not extend to a person’s or publisher’s permanent credibility." },
  { id: "evidence-traceability", number: "02", icon: FileCheck2, title: "Evidence traceability", text: "Each material claim is supported by verifiable evidence with precise attribution. Exact passages, source snapshots, retrieval timestamps, and citation checks are retained." },
  { id: "source-independence", number: "03", icon: Globe2, title: "Source independence", text: "Information is evaluated by its content and corroboration, not by the identity, popularity, or reputation of a source. Derivative reporting is grouped." },
  { id: "deterministic-scoring", number: "04", icon: Scale, title: "Deterministic scoring", text: "Scores are produced by a fixed, transparent method. Given the same evidence, retrieval timestamp, and model version, the calculation can be reproduced." },
];

const scoreRoles = [
  { icon: FileCheck2, title: "Evidence support", text: "Assesses how well available evidence supports material claims, considering quantity, relevance, and corroboration." },
  { icon: BadgeCheck, title: "Attribution support", text: "Assesses the quality and precision of source attribution, including transparency, specificity, and verifiability." },
  { icon: Quote, title: "Quote fidelity", text: "Assesses the accuracy of quotations and excerpts, and whether they faithfully reflect the original source content." },
  { icon: ShieldCheck, title: "Verdict confidence", text: "Reflects confidence in the report’s conclusion based on the strength and consistency of the available evidence." },
  { icon: Globe2, title: "Source independence", text: "Assesses how much the conclusion relies on independent sources rather than a single outlet or viewpoint." },
  { icon: BookOpenCheck, title: "Context completeness", text: "Assesses whether the background, context, and limitations needed to understand the evidence were captured." },
];

export default function MethodologyPage() {
  return <main className="mx-auto grid w-full max-w-7xl gap-6">
    <section className="grid gap-6 border-b pb-6 lg:grid-cols-[minmax(0,1fr)_260px] lg:items-start">
      <div><h1 className="font-editorial text-4xl font-normal tracking-[-0.03em] text-foreground sm:text-5xl">Evidence-management methodology</h1><p className="mt-3 max-w-3xl text-base leading-7 text-muted-foreground">Elara organizes evidence as of a retrieval timestamp, separates attribution from factual content, records inaccessible sources, and exposes how report scores are produced.</p><p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">Research depth changes evidence breadth, not truth criteria or citation rigor. Discovery begins with required primary, contradiction, and attribution paths, then may expand to a second phase when deterministic candidate and source-diversity coverage is insufficient.</p></div>
      <nav className="border-l pl-5" aria-label="On this page"><p className="font-mono text-xs font-semibold uppercase tracking-wide text-primary">On this page</p><ol className="mt-3 grid gap-2 font-mono text-xs text-muted-foreground">{principles.map((item) => <li key={item.id}><a className="flex gap-3 hover:text-primary focus-visible:outline-none focus-visible:underline" href={`#${item.id}`}><span>{item.number}</span>{item.title}</a></li>)}<li><a className="flex gap-3 hover:text-primary focus-visible:outline-none focus-visible:underline" href="#score-roles"><span>05</span>Score roles</a></li></ol></nav>
    </section>

    <section aria-label="Methodology principles" className="grid divide-y border-y md:grid-cols-2 md:divide-x md:divide-y-0 xl:grid-cols-4">
      {principles.map((principle) => { const Icon = principle.icon; return <article id={principle.id} key={principle.id} className="p-4 sm:p-5"><p className="font-mono text-sm font-semibold text-destructive">{principle.number}</p><Icon className="mt-3 h-12 w-12 text-primary" strokeWidth={1.5} aria-hidden="true" /><h2 className="mt-3 font-editorial text-2xl font-normal">{principle.title}</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">{principle.text}</p></article>; })}
    </section>

    <section id="score-roles"><div><p className="font-mono text-sm font-semibold text-destructive">05</p><h2 className="mt-1 font-editorial text-3xl font-normal">Score roles</h2><p className="mt-1 text-sm text-muted-foreground">Elara evaluates reports across six roles. Each role captures a distinct dimension of evidentiary quality.</p></div><dl className="mt-4 grid divide-y border md:grid-cols-2 md:divide-x md:divide-y-0 xl:grid-cols-6">{scoreRoles.map((role) => { const Icon = role.icon; return <div key={role.title} className="p-4"><Icon className="h-10 w-10 text-primary" strokeWidth={1.5} aria-hidden="true" /><dt className="mt-3 font-editorial text-lg font-normal">{role.title}</dt><dd className="mt-2 text-sm leading-6 text-muted-foreground">{role.text}</dd></div>; })}</dl></section>

    <aside className="flex items-center gap-4 border border-destructive/70 bg-destructive/5 p-4 text-destructive"><ShieldCheck className="h-10 w-10 shrink-0" strokeWidth={1.5} aria-hidden="true" /><div><p className="font-mono text-xs font-semibold uppercase tracking-wide">Boundary note</p><p className="mt-1 font-editorial text-lg font-normal">A report evaluates the submitted claim or document — not the permanent credibility of a person or publisher.</p></div></aside>
  </main>;
}
