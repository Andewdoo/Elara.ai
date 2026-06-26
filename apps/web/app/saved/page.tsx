import { Archive } from "lucide-react";

import { HistoryList } from "@/components/app/history-list";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function SavedPage() {
  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Archive className="h-4 w-4 text-primary" aria-hidden="true" />
            Saved workspace
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-6 text-muted-foreground">
            Saved reports will remain account-owned records served through FastAPI. This shell renders mocked saved entries without storing sensitive report content in browser storage.
          </p>
        </CardContent>
      </Card>
      <HistoryList savedOnly />
    </div>
  );
}
