import { z } from "zod";

import type { DeepSeekClient, LiteDeepSeekCallMetadata, LiteDeepSeekMessage } from "./deepseek";
import { assertLiteServerOnly } from "./server-config";
import type { LiteModelMetadata } from "./schemas";

assertLiteServerOnly("Lite prompt utilities");

export const LITE_PROMPT_UTILS_VERSION = "lite-prompt-utils-v1";
export const LITE_SYSTEM_PROMPT_MAX_CHARS = 1400;
export const LITE_CONTEXT_PAYLOAD_MAX_CHARS = 24_000;
export const LITE_TOTAL_PROMPT_MAX_TOKENS = 8_000;

export interface LitePromptBudget {
  systemMaxChars?: number;
  contextMaxChars?: number;
  totalMaxTokens?: number;
}

export type LiteStructuredClient = Pick<DeepSeekClient, "generateStructured">;

export interface LiteStructuredStageResult<T> {
  output: T;
  metadata: LiteDeepSeekCallMetadata;
  model: LiteModelMetadata;
}

export function buildBoundedLitePayload(
  stage: string,
  payload: unknown,
  maxChars = LITE_CONTEXT_PAYLOAD_MAX_CHARS,
): string {
  const serialized = JSON.stringify(payload);
  assertLitePromptBudget(stage, "", serialized, { contextMaxChars: maxChars });
  return serialized;
}

export function assertLitePromptBudget(
  stage: string,
  systemPrompt: string,
  contextPayload: string,
  budget: LitePromptBudget = {},
): void {
  const systemMaxChars = budget.systemMaxChars ?? LITE_SYSTEM_PROMPT_MAX_CHARS;
  const contextMaxChars = budget.contextMaxChars ?? LITE_CONTEXT_PAYLOAD_MAX_CHARS;
  const totalMaxTokens = budget.totalMaxTokens ?? LITE_TOTAL_PROMPT_MAX_TOKENS;

  if (systemPrompt.length > systemMaxChars) {
    throw new LitePromptBudgetError(stage, "system_prompt_too_large", systemPrompt.length, systemMaxChars);
  }
  if (contextPayload.length > contextMaxChars) {
    throw new LitePromptBudgetError(stage, "context_payload_too_large", contextPayload.length, contextMaxChars);
  }

  const estimatedTokens = estimateLitePromptTokens(`${systemPrompt}\n${contextPayload}`);
  if (estimatedTokens > totalMaxTokens) {
    throw new LitePromptBudgetError(stage, "estimated_prompt_tokens_too_large", estimatedTokens, totalMaxTokens);
  }
}

export async function callLiteStructuredStage<T>(request: {
  client: LiteStructuredClient;
  stage: string;
  promptVersion: string;
  systemPrompt: string;
  contextPayload: string;
  outputSchema: z.ZodType<T>;
  temperature?: number;
  maxTokens?: number;
  modelRole?: "chat" | "reasoning";
  budget?: LitePromptBudget;
  signal?: AbortSignal;
}): Promise<LiteStructuredStageResult<T>> {
  assertLitePromptBudget(request.stage, request.systemPrompt, request.contextPayload, request.budget);
  const messages: LiteDeepSeekMessage[] = [
    { role: "system", content: request.systemPrompt },
    { role: "user", content: request.contextPayload },
  ];
  const result = await request.client.generateStructured({
    messages,
    outputSchema: request.outputSchema,
    promptVersion: request.promptVersion,
    temperature: request.temperature ?? 0,
    maxTokens: request.maxTokens,
    modelRole: request.modelRole,
    signal: request.signal,
  });

  const output = request.outputSchema.parse(result.output);
  return {
    output,
    metadata: result.metadata,
    model: toLiteModelMetadata(result.metadata),
  };
}

export function toLiteModelMetadata(metadata: LiteDeepSeekCallMetadata): LiteModelMetadata {
  return {
    provider: "deepseek",
    model: metadata.model,
    temperature: metadata.temperature,
    latency_ms: metadata.latency_ms,
    token_usage: metadata.token_usage,
    generated_at: metadata.generated_at,
  };
}

export function estimateLitePromptTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

export function truncateLiteText(value: string, maxChars: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxChars - 16)).trim()} [truncated]`;
}

export class LitePromptBudgetError extends Error {
  readonly code = "lite_prompt_budget_exceeded";
  readonly stage: string;
  readonly reason: string;
  readonly actual: number;
  readonly limit: number;

  constructor(stage: string, reason: string, actual: number, limit: number) {
    super(`Lite ${stage} prompt budget exceeded: ${reason}`);
    this.name = "LitePromptBudgetError";
    this.stage = stage;
    this.reason = reason;
    this.actual = actual;
    this.limit = limit;
  }
}
