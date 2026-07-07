import { NextResponse } from "next/server";

import { answerLiteClaim } from "@/lib/lite/pipeline";
import { persistLiteRunIfConfigured } from "@/lib/lite/run-persistence";
import {
  liteClaimRequestSchema,
  liteResponseSchema,
  LITE_REQUEST_MAX_LENGTH,
  type LiteErrorResponse,
  type LiteResponse,
} from "@/lib/lite/schemas";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const LITE_ROUTE_MAX_BODY_CHARS = LITE_REQUEST_MAX_LENGTH + 2048;
const LITE_ROUTE_RATE_LIMIT_WINDOW_MS = 60_000;
const LITE_ROUTE_RATE_LIMIT_MAX = 8;
const LITE_ROUTE_RATE_LIMIT_BUCKETS = new Map<string, number[]>();

type LiteAnswerPipeline = typeof answerLiteClaim;
type LiteRunPersistence = typeof persistLiteRunIfConfigured;

export interface LiteAnswerRouteDependencies {
  answerLiteClaim?: LiteAnswerPipeline;
  persistLiteRunIfConfigured?: LiteRunPersistence;
  now?: () => number;
  rateBuckets?: Map<string, number[]>;
  runIdFactory?: () => string;
}

export async function POST(request: Request) {
  return handleLiteAnswerRequest(request);
}

export async function handleLiteAnswerRequest(
  request: Request,
  dependencies: LiteAnswerRouteDependencies = {},
) {
  if (!isJsonRequest(request)) {
    return jsonLiteResponse(
      liteRouteError("lite_unsupported_content_type", "Lite requests must use application/json.", false),
      415,
    );
  }

  const contentLength = request.headers.get("content-length");
  if (contentLength && Number(contentLength) > LITE_ROUTE_MAX_BODY_CHARS) {
    return jsonLiteResponse(
      liteRouteError("lite_request_too_large", "Lite requests must stay within the public demo size limit.", false),
      413,
    );
  }

  const rateLimit = consumeLiteRateLimit(request, dependencies);
  if (!rateLimit.allowed) {
    return jsonLiteResponse(
      liteRouteError("lite_rate_limited", "Lite public demo rate limit exceeded. Please retry shortly.", true),
      429,
      { "Retry-After": String(Math.ceil(rateLimit.retryAfterMs / 1000)) },
    );
  }

  let body: unknown;
  try {
    const text = await request.text();
    if (text.length > LITE_ROUTE_MAX_BODY_CHARS) {
      return jsonLiteResponse(
        liteRouteError("lite_request_too_large", "Lite requests must stay within the public demo size limit.", false),
        413,
      );
    }
    body = JSON.parse(text);
  } catch {
    return jsonLiteResponse(
      liteRouteError("lite_invalid_json", "Lite requests must be valid JSON.", false),
      400,
    );
  }

  const parsed = liteClaimRequestSchema.safeParse(body);
  if (!parsed.success) {
    return jsonLiteResponse(
      liteRouteError(
        "lite_invalid_request",
        "Lite requests require a supported corpus version and a bounded claim or question.",
        false,
      ),
      400,
    );
  }

  if (isAbusiveLiteInput(parsed.data.input)) {
    return jsonLiteResponse(
      liteRouteError("lite_abuse_limit", "Lite requests must be concise public-demo claims or questions.", false),
      422,
    );
  }

  let response: LiteResponse;
  try {
    response = liteResponseSchema.parse(
      await (dependencies.answerLiteClaim ?? answerLiteClaim)({
        request: parsed.data,
        runId: dependencies.runIdFactory?.() ?? createRouteRunId(),
        signal: request.signal,
      }),
    );
  } catch {
    return jsonLiteResponse(
      liteRouteError(
        "lite_route_pipeline_error",
        "Lite Mode could not complete this request.",
        true,
        parsed.data.corpus_version,
        "internal_error",
      ),
      503,
    );
  }

  const publicResponse = sanitizeLiteResponseForPublic(response);
  try {
    await (dependencies.persistLiteRunIfConfigured ?? persistLiteRunIfConfigured)(publicResponse, {
      signal: request.signal,
    });
  } catch {
    return jsonLiteResponse(
      liteRouteError(
        "lite_run_persistence_error",
        "Lite Mode could not safely store this demo run.",
        true,
        parsed.data.corpus_version,
        "internal_error",
      ),
      503,
    );
  }

  return jsonLiteResponse(publicResponse, statusForLiteResponse(publicResponse));
}

function statusForLiteResponse(response: LiteResponse): number {
  if (response.kind !== "error") {
    return 200;
  }
  if (response.status === "invalid_request") {
    return 400;
  }
  if (response.status === "unsupported_request") {
    return 422;
  }
  if (response.status === "model_error" || response.status === "retrieval_error") {
    return response.retryable ? 503 : 502;
  }
  return 500;
}

function jsonLiteResponse(response: LiteResponse, status: number, headers?: HeadersInit) {
  return NextResponse.json(response, { status, headers });
}

function liteRouteError(
  errorCode: string,
  message: string,
  retryable: boolean,
  corpusVersion?: LiteErrorResponse["corpus_version"],
  status: LiteErrorResponse["status"] = "invalid_request",
): LiteErrorResponse {
  return {
    kind: "error",
    status,
    corpus_version: corpusVersion,
    reviewed_at: new Date().toISOString(),
    error_code: errorCode,
    message,
    retryable,
    audit_status: "not_run",
  };
}

function isJsonRequest(request: Request): boolean {
  const contentType = request.headers.get("content-type");
  return !contentType || contentType.toLowerCase().includes("application/json");
}

function consumeLiteRateLimit(
  request: Request,
  dependencies: LiteAnswerRouteDependencies,
): { allowed: true } | { allowed: false; retryAfterMs: number } {
  const now = dependencies.now?.() ?? Date.now();
  const buckets = dependencies.rateBuckets ?? LITE_ROUTE_RATE_LIMIT_BUCKETS;
  const key = rateLimitKey(request);
  const recent = (buckets.get(key) ?? []).filter((timestamp) => now - timestamp < LITE_ROUTE_RATE_LIMIT_WINDOW_MS);
  if (recent.length >= LITE_ROUTE_RATE_LIMIT_MAX) {
    return { allowed: false, retryAfterMs: LITE_ROUTE_RATE_LIMIT_WINDOW_MS - (now - recent[0]) };
  }
  recent.push(now);
  buckets.set(key, recent);
  return { allowed: true };
}

function rateLimitKey(request: Request): string {
  return (
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    request.headers.get("x-real-ip")?.trim() ||
    request.headers.get("cf-connecting-ip")?.trim() ||
    "anonymous"
  ).slice(0, 160);
}

function isAbusiveLiteInput(input: string): boolean {
  const urlCount = input.match(/https?:\/\//gi)?.length ?? 0;
  const controlCount = input.match(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g)?.length ?? 0;
  const repeatedRun = /(.)\1{799,}/.test(input);
  return urlCount > 8 || controlCount > 0 || repeatedRun;
}

function sanitizeLiteResponseForPublic(response: LiteResponse): LiteResponse {
  if (response.kind !== "error") {
    return response;
  }
  if (response.status === "invalid_request" || response.status === "unsupported_request") {
    return response;
  }
  return {
    ...response,
    message: "A server-side Lite provider failed before a public answer could be completed.",
  };
}

function createRouteRunId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0").slice(-12)}`;
}
