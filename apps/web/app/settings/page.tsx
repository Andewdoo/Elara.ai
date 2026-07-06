import { LockKeyhole, Palette, UserRound } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const sections = [
  { icon: UserRound, title: "Account", detail: "Your Firebase-authenticated identity controls access to private runs, reports, feedback, and exports." },
  { icon: LockKeyhole, title: "Security", detail: "Provider, database, cache, tracing, and object-storage credentials remain server-side." },
  { icon: Palette, title: "Interface preferences", detail: "Report filters and drawer state are temporary and reset with the browser session." },
];

export default function SettingsPage() {
  return <div className="grid gap-5"><Card><CardHeader><CardTitle>Settings</CardTitle></CardHeader><CardContent><p className="text-sm leading-6 text-muted-foreground">Account-managed settings are not currently available. Verification depth is selected for each new run, and report data is never stored as a browser preference.</p></CardContent></Card><div className="grid gap-4 md:grid-cols-3">{sections.map(({ icon: Icon, title, detail }) => <Card key={title}><CardHeader><CardTitle className="flex items-center gap-2"><Icon className="h-4 w-4 text-primary" aria-hidden="true"/>{title}</CardTitle></CardHeader><CardContent><p className="text-sm leading-6 text-muted-foreground">{detail}</p></CardContent></Card>)}</div></div>;
}
