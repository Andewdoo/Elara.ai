import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function HistoryList({ savedOnly = false }: { savedOnly?: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{savedOnly ? "Saved reports" : "Recent runs"}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          {savedOnly ? "Saved report records" : "History records"} will appear here when the authorized Step 15 API is available. No mock reports are linked into the live workspace.
        </p>
      </CardContent>
    </Card>
  );
}
