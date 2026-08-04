import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // The Docker-published local app is opened through IPv4 because another
  // development server owns the IPv6 localhost listener on port 3000.
  // Allow Next's dev resources to load and hydrate client components there.
  allowedDevOrigins: ["127.0.0.1"],
};

const sentryConfig = {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT_WEB,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: !process.env.CI,
  sourcemaps: { disable: !process.env.SENTRY_AUTH_TOKEN },
  webpack: { treeshake: { removeDebugLogging: true } },
};

export default process.env.NEXT_PUBLIC_SENTRY_DSN ? withSentryConfig(nextConfig, sentryConfig) : nextConfig;
