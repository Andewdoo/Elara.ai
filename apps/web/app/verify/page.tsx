import { ShieldCheck } from "lucide-react";

import { VerifyForm } from "@/components/app/verify-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function VerifyPage() {
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
      <VerifyForm />
      <Card className="self-start">
        <CardHeader>
          <CardTitle>Submission boundaries</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm text-muted-foreground">
          <p className="flex gap-2">
            <ShieldCheck className="mt-0.5 h-4 w-4 text-primary" aria-hidden="true" />
            Browser validation is a convenience layer. FastAPI will authenticate, authorize, validate, persist the run, and enqueue worker jobs.
          </p>
          <p>No model, search, database, Redis, object-storage, Firebase Admin, Sentry auth, or tracing credentials are exposed to the browser.</p>
        </CardContent>
      </Card>
    </div>
  );
}
