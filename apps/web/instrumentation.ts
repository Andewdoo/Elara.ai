const sentryEnabled = () => Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN);

export async function register() {
  if (!sentryEnabled()) return;
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

export async function onRequestError(...args: Parameters<(typeof import("@sentry/nextjs"))["captureRequestError"]>) {
  if (!sentryEnabled()) return;
  const { captureRequestError } = await import("@sentry/nextjs");
  captureRequestError(...args);
}
