"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body>
        <main className="mx-auto max-w-xl p-8">
          <h1 className="text-2xl font-semibold">Elara could not load this view.</h1>
          <p className="mt-3 text-slate-600">The error was recorded without report content or credentials.</p>
        </main>
      </body>
    </html>
  );
}
