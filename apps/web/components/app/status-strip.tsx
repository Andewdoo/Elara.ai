import { CheckCircle2, Database, FileSearch, ShieldCheck } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

const guarantees = [
  { label: "Durable run state", icon: Database },
  { label: "Exact evidence passages", icon: FileSearch },
  { label: "Citation-audited reports", icon: CheckCircle2 },
  { label: "Server-authoritative scores", icon: ShieldCheck },
];

export function StatusStrip() {
  return <Card><CardContent className="grid gap-3 sm:grid-cols-2">
    {guarantees.map(({ label, icon: Icon }) => <div key={label} className="flex items-center gap-2 rounded-md border bg-white px-3 py-2"><Icon className="h-4 w-4 text-primary" aria-hidden="true"/><span className="text-xs font-medium">{label}</span></div>)}
  </CardContent></Card>;
}
