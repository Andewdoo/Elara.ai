import { NextResponse } from "next/server";

import { answerLiteClaim } from "@/lib/lite/pipeline";
import { liteResponseSchema, type LiteResponse } from "@/lib/lite/schemas";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      {
        kind: "error",
        status: "invalid_request",
        error_code: "lite_invalid_json",
        message: "Lite requests must be valid JSON.",
        retryable: false,
        audit_status: "not_run",
      },
      { status: 400 },
    );
  }

  const response = liteResponseSchema.parse(await answerLiteClaim({ request: body }));
  return NextResponse.json(response, { status: statusForLiteResponse(response) });
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
