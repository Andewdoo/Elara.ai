import { Bell, LockKeyhole, Palette, UserRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/form-controls";

const sections = [
  { icon: UserRound, title: "Account", detail: "Firebase Authentication supplies identity. PostgreSQL ownership records arrive in the API step." },
  { icon: LockKeyhole, title: "Security", detail: "Server-only credentials stay outside the Next.js browser bundle." },
  { icon: Bell, title: "Notifications", detail: "Progress and report completion alerts will attach to authenticated run records." },
  { icon: Palette, title: "Interface", detail: "Only non-sensitive display preferences may be persisted locally." },
];

export default function SettingsPage() {
  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>Settings</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-1 text-sm font-medium">
            Default research depth
            <Select defaultValue="STANDARD">
              <option value="QUICK">Quick</option>
              <option value="STANDARD">Standard</option>
              <option value="DEEP">Deep</option>
            </Select>
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Default report tab
            <Select defaultValue="overview">
              <option value="overview">Overview</option>
              <option value="claims">Claims</option>
              <option value="evidence">Evidence</option>
              <option value="graph">Graph</option>
            </Select>
          </label>
        </CardContent>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {sections.map((section) => {
          const Icon = section.icon;
          return (
            <Card key={section.title}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                  {section.title}
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3">
                <Badge tone="neutral">Mock setting</Badge>
                <p className="text-sm leading-6 text-muted-foreground">{section.detail}</p>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
