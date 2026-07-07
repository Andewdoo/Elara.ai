import { z } from "zod";

import type { LiteStructuredClient } from "../prompt-utils";
import { buildBoundedLitePayload, callLiteStructuredStage, truncateLiteText } from "../prompt-utils";
import {
  liteClaimRequestSchema,
  liteCitedSentenceSchema,
  liteInputClassificationSchema,
  liteSelectedContextSchema,
  liteSynthesisOutputSchema,
  type LiteClaimRequest,
  type LiteInputClassification,
  type LiteSelectedContext,
  type LiteSynthesisOutput,
} from "../schemas";
import { assertLiteServerOnly } from "../server-config";

assertLiteServerOnly("Lite synthesis prompt");

export const LITE_SYNTHESIS_PROMPT_VERSION = "lite-synthesis-v1";
export const LITE_SYNTHESIS_SYSTEM_PROMPT = [
  "Answer only from selected Lite chunks.",
  "Every factual sentence must cite one or more supplied chunk ids.",
  "Include contradictions when selected evidence directly contradicts the target.",
  "Distinguish insufficient evidence from false and attribution from fact.",
  "Do not add facts, browse, compute scores, claim full production verification, or cite missing chunks.",
].join(" ");

const liteSynthesisModelSentenceSchema = liteCitedSentenceSchema.omit({
  source_labels: true,
  support_status: true,
});

export const liteSynthesisModelOutputSchema = z.object({
  status: z.enum(["answer", "insufficient_evidence"]),
  answer_markdown: z.string().trim().min(1).max(8000),
  cited_sentences: z.array(liteSynthesisModelSentenceSchema).max(40).default([]),
  limitations: z.array(z.string().trim().min(1).max(400)).max(8).default([]),
  confidence: z.number().min(0).max(1),
  uncertainty: z.array(z.string().trim().min(1).max(240)).max(8).default([]),
});

export function buildLiteSynthesisContext(
  request: LiteClaimRequest,
  classification: LiteInputClassification,
  selectedContext: LiteSelectedContext,
): string {
  const parsedRequest = liteClaimRequestSchema.parse(request);
  const parsedClassification = liteInputClassificationSchema.parse(classification);
  const parsedContext = liteSelectedContextSchema.parse(selectedContext);

  return buildBoundedLitePayload(
    "synthesis",
    {
      task: "synthesize_lite_answer",
      corpus_version: parsedRequest.corpus_version,
      target: parsedClassification.normalized_input,
      input_type: parsedClassification.input_type,
      evidence_reviewed_at: parsedContext.reviewed_at,
      selected_chunks: parsedContext.chunks.map((chunk) => ({
        chunk_id: chunk.chunk_id,
        source_label: chunk.source_label,
        source_title: chunk.source_title,
        publisher: chunk.publisher ?? null,
        document_date: chunk.document_date ?? null,
        page_or_position: chunk.page_or_position ?? null,
        text: truncateLiteText(chunk.chunk_text, 2200),
      })),
      judgments: parsedContext.judgments.map((judgment) => ({
        chunk_id: judgment.chunk_id,
        stance: judgment.stance,
        cited_span: judgment.cited_span ?? null,
        rationale: judgment.rationale ?? null,
        confidence: judgment.confidence,
      })),
      required_language: [
        "Evidence reviewed timestamp belongs in metadata, not as a new uncited fact.",
        "Lite Mode answers from a curated stored evidence library.",
        "Use insufficient_evidence when selected chunks do not directly support or contradict the target.",
      ],
    },
    22_000,
  );
}

export async function synthesizeLiteAnswer(options: {
  request: LiteClaimRequest;
  classification: LiteInputClassification;
  selectedContext: LiteSelectedContext;
  client: LiteStructuredClient;
  signal?: AbortSignal;
}): Promise<LiteSynthesisOutput> {
  const stage = await callLiteStructuredStage({
    client: options.client,
    stage: "synthesis",
    promptVersion: LITE_SYNTHESIS_PROMPT_VERSION,
    systemPrompt: LITE_SYNTHESIS_SYSTEM_PROMPT,
    contextPayload: buildLiteSynthesisContext(options.request, options.classification, options.selectedContext),
    outputSchema: liteSynthesisModelOutputSchema,
    temperature: 0,
    maxTokens: 2200,
    signal: options.signal,
  });

  const sourceLabelsByChunk = new Map(
    options.selectedContext.chunks.map((chunk) => [chunk.chunk_id, chunk.source_label]),
  );

  return liteSynthesisOutputSchema.parse({
    prompt_version: LITE_SYNTHESIS_PROMPT_VERSION,
    model: stage.model,
    ...stage.output,
    cited_sentences: stage.output.cited_sentences.map((sentence) => ({
      ...sentence,
      source_labels: sentence.citation_ids.map((chunkId) => sourceLabelsByChunk.get(chunkId) ?? "Unknown Lite chunk"),
      support_status: "supported",
    })),
  });
}
