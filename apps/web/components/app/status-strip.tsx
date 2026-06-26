import { AlertTriangle, CheckCircle2, CircleDot, Search, Sigma, SplitSquareHorizontal } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

const steps = [
  { label: "Accepted", icon: CheckCircle2, status: "done" },
  { label: "Decomposed", icon: SplitSquareHorizontal, status: "done" },
  { label: "Retrieved", icon: Search, status: "done" },
  { label: "Scored", icon: Sigma, status: "done" },
  { label: "Citation audit", icon: CircleDot, status: "active" },
];

export function StatusStrip() {
  return (
    <Card>
      <CardContent className="grid gap-4 md:grid-cols-[1fr_auto] md:items-center">
        <div className="grid gap-3 sm:grid-cols-5">
          {steps.map((step) => {
            const Icon = step.icon;
            return (
              <div key={step.label} className="flex items-center gap-2 rounded-md border bg-white px-3 py-2">
                <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                <span className="text-xs font-medium">{step.label}</span>
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-600" aria-hidden="true" />
          <Badge tone="warning">1 inaccessible source</Badge>
        </div>
      </CardContent>
    </Card>
  );
}
