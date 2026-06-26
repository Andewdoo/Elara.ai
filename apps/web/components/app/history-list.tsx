import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { mockedHistory } from "@/lib/mock-report";

export function HistoryList({ savedOnly = false }: { savedOnly?: boolean }) {
  const items = savedOnly ? mockedHistory.slice(0, 2) : mockedHistory;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{savedOnly ? "Saved reports" : "Recent runs"}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {items.map((item) => (
          <Link
            key={item.runId}
            href={`/report/${item.runId}`}
            className="grid gap-3 rounded-md border bg-white p-3 transition hover:border-primary/50 md:grid-cols-[1fr_auto]"
          >
            <span>
              <span className="block text-sm font-semibold">{item.title}</span>
              <span className="block text-xs text-muted-foreground">
                Reviewed {new Date(item.evidenceReviewedAt).toLocaleString()}
              </span>
            </span>
            <span className="flex items-center gap-2">
              <Badge tone="info">{item.verdict}</Badge>
              <ExternalLink className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            </span>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}
