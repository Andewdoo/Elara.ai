"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    Sentry.withScope((scope) => {
      if (error.digest) scope.setTag("next_error_digest", error.digest);
      Sentry.captureMessage("Client view failed without recording exception content", "error");
    });
  }, [error]);

  return (
    <html lang="en">
      <body>
        <main className="mx-auto max-w-xl p-8">
          <h1 className="text-2xl font-semibold">Elara could not load this view.</h1>
          <p className="mt-3 text-slate-600">The error was recorded without report content or credentials.</p>
          <button type="button" className="mt-4 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white" onClick={reset}>Try again</button>
        </main>
      </body>
    </html>
  );
}
