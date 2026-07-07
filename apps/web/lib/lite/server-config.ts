const SAFE_IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/;

export type LiteServerEnv = Record<string, string | undefined>;

export class LiteServerConfigurationError extends Error {
  readonly code = "lite_server_configuration_error";
  readonly missing: readonly string[];

  constructor(message: string, missing: readonly string[] = []) {
    super(message);
    this.name = "LiteServerConfigurationError";
    this.missing = missing;
  }
}

export function assertLiteServerOnly(moduleName: string): void {
  if (typeof window !== "undefined") {
    throw new LiteServerConfigurationError(`${moduleName} is server-only and cannot run in the browser`);
  }
}

export function isProductionLikeLiteExecution(env: LiteServerEnv = process.env): boolean {
  return (
    env.NODE_ENV === "production" ||
    env.VERCEL_ENV === "production" ||
    env.VERCEL_ENV === "preview" ||
    env.LITE_DEMO_ENABLED === "true"
  );
}

export function requireServerEnv(
  env: LiteServerEnv,
  names: readonly string[],
  context: string,
): Record<string, string> {
  const missing = names.filter((name) => !env[name]?.trim());
  if (missing.length > 0) {
    throw new LiteServerConfigurationError(
      `Missing ${context} server configuration: ${missing.join(", ")}`,
      missing,
    );
  }

  return Object.fromEntries(names.map((name) => [name, env[name]!.trim()]));
}

export function readOptionalServerEnv(env: LiteServerEnv, name: string): string | undefined {
  const value = env[name]?.trim();
  return value ? value : undefined;
}

export function normalizeHttpBaseUrl(rawValue: string, envName: string): string {
  let parsed: URL;
  try {
    parsed = new URL(rawValue.trim());
  } catch {
    throw new LiteServerConfigurationError(`${envName} must be an absolute HTTP(S) URL`);
  }

  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    !parsed.host ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new LiteServerConfigurationError(
      `${envName} must be an absolute HTTP(S) URL without credentials, query, or fragment`,
    );
  }

  return parsed.toString().replace(/\/$/, "");
}

export function requireSafeIdentifier(value: string, label: string): string {
  if (!SAFE_IDENTIFIER.test(value)) {
    throw new LiteServerConfigurationError(`${label} must be a non-sensitive stable identifier`);
  }
  return value;
}

export function redactForLiteLog(value: unknown): unknown {
  if (typeof value === "string") {
    if (value.length <= 24 && SAFE_IDENTIFIER.test(value)) {
      return value;
    }
    return "[redacted]";
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactForLiteLog(item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, nestedValue]) => [
        key,
        /(key|token|secret|authorization|prompt|source|content|text|body)/i.test(key)
          ? "[redacted]"
          : redactForLiteLog(nestedValue),
      ]),
    );
  }
  return value;
}
