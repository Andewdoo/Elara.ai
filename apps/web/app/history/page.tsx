import { HistoryList } from "@/components/app/history-list";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form-controls";

export default function HistoryPage() {
  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>History filters</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-[1fr_220px_220px]">
          <Input placeholder="Search runs, sources, or verdicts" />
          <Select defaultValue="all">
            <option value="all">All statuses</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </Select>
          <Select defaultValue="recent">
            <option value="recent">Most recent</option>
            <option value="oldest">Oldest first</option>
            <option value="confidence">Confidence</option>
          </Select>
        </CardContent>
      </Card>
      <HistoryList />
    </div>
  );
}
