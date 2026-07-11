import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { extname } from "node:path";
import { z } from "zod";
import { createDeepSeekClient, type DeepSeekClient, type LiteDeepSeekCallMetadata } from "./deepseek";
import { liteCorpusVersionSchema, SUPPORTED_LITE_CORPUS_VERSIONS } from "./schemas";
import {
  assertLiteServerOnly,
  normalizeHttpBaseUrl,
  readOptionalServerEnv,
  requireServerEnv,
  type LiteServerEnv,
} from "./server-config";
import { liteSupabaseAuthHeaders } from "./supabase";

assertLiteServerOnly("Lite corpus ingestion");

export const LITE_CORPUS_INGESTION_VERSION = "lite-corpus-ingestion-v1";
export const LITE_CHUNKER_VERSION = "lite-heading-boundary-chunker-v1";
export const LITE_FIXTURE_EMBEDDING_VERSION = "lite-fixture-embedding-v1";
export const LITE_EMBEDDING_DIMENSION = 1536;
export const LITE_CHUNK_MAX_CHARS = 1200;
export const LITE_CHUNK_OVERLAP_CHARS = 180;

const metadataSchema = z.record(z.string(), z.unknown()).default({});

const liteSourceBlockSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("heading"),
    level: z.number().int().min(1).max(6).default(2),
    text: z.string().trim().min(1).max(240),
    page_number: z.number().int().positive().optional(),
    section_label: z.string().trim().min(1).max(160).optional(),
  }),
  z.object({
    type: z.literal("paragraph"),
    text: z.string().trim().min(1).max(8000),
    page_number: z.number().int().positive().optional(),
    section_label: z.string().trim().min(1).max(160).optional(),
    paragraph_index: z.number().int().nonnegative().optional(),
  }),
  z.object({
    type: z.literal("table_row"),
    cells: z.union([z.array(z.string().trim().max(800)), z.record(z.string(), z.string().trim().max(800))]),
    caption: z.string().trim().min(1).max(240).optional(),
    page_number: z.number().int().positive().optional(),
    section_label: z.string().trim().min(1).max(160).optional(),
    paragraph_index: z.number().int().nonnegative().optional(),
  }),
  z.object({
    type: z.literal("transcript_turn"),
    speaker: z.string().trim().min(1).max(120),
    text: z.string().trim().min(1).max(8000),
    timestamp: z.string().trim().min(1).max(80).optional(),
    page_number: z.number().int().positive().optional(),
    section_label: z.string().trim().min(1).max(160).optional(),
    paragraph_index: z.number().int().nonnegative().optional(),
  }),
  z.object({
    type: z.literal("semantic_break"),
    label: z.string().trim().min(1).max(120).optional(),
  }),
]);

const liteCorpusDocumentSchema = z
  .object({
    id: z.string().trim().min(1).max(120),
    corpus_version: liteCorpusVersionSchema.optional(),
    title: z.string().trim().min(1).max(240),
    source_url: z.string().url().optional(),
    publisher: z.string().trim().min(1).max(160).optional(),
    document_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),
    visibility: z.enum(["public", "private", "disabled"]).default("public"),
    source_citation_label: z.string().trim().min(1).max(120).optional(),
    metadata: metadataSchema,
    content_markdown: z.string().trim().min(1).optional(),
    blocks: z.array(liteSourceBlockSchema).optional(),
  })
  .superRefine((value, context) => {
    if (!value.content_markdown && (!value.blocks || value.blocks.length === 0)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Lite corpus documents require content_markdown or blocks",
        path: ["blocks"],
      });
    }
  });

const liteCorpusFixtureSchema = z.object({
  corpus_version: liteCorpusVersionSchema.default(SUPPORTED_LITE_CORPUS_VERSIONS[0]),
  documents: z.array(liteCorpusDocumentSchema).min(1).max(200),
  metadata: metadataSchema,
});

export type LiteSourceBlock = z.infer<typeof liteSourceBlockSchema>;
export type LiteCorpusDocumentInput = z.infer<typeof liteCorpusDocumentSchema>;
export type LiteCorpusFixture = z.infer<typeof liteCorpusFixtureSchema>;
export type LiteEmbeddingMode = "auto" | "deepseek" | "fixture" | "none";

export interface LitePreparedCorpus {
  corpus_version: string;
  documents: LitePreparedDocument[];
  metadata: Record<string, unknown>;
  ingestion_version: typeof LITE_CORPUS_INGESTION_VERSION;
  chunker_version: typeof LITE_CHUNKER_VERSION;
  embedding: LiteEmbeddingSummary;
}

export interface LitePreparedDocument {
  source_id: string;
  corpus_version: string;
  title: string;
  source_url?: string;
  publisher?: string;
  document_date?: string;
  visibility: "public" | "private" | "disabled";
  source_content_hash: string;
  metadata: Record<string, unknown>;
  chunks: LitePreparedChunk[];
}

export interface LitePreparedChunk {
  source_id: string;
  corpus_version: string;
  chunk_index: number;
  chunk_text: string;
  embedding: number[] | null;
  heading_path: string[];
  page_number?: number;
  section_label?: string;
  paragraph_index?: number;
  char_start: number;
  char_end: number;
  content_hash: string;
  source_citation_label: string;
  metadata: Record<string, unknown>;
}

export interface LiteEmbeddingSummary {
  mode: Exclude<LiteEmbeddingMode, "auto">;
  version: string;
  model: string | null;
  generated_at: string;
  chunk_count: number;
  metadata?: LiteDeepSeekCallMetadata;
}

export interface LitePrepareCorpusOptions {
  defaultCorpusVersion?: string;
  embeddingMode?: LiteEmbeddingMode;
  deepseekClient?: Pick<DeepSeekClient, "embeddingAvailable" | "generateEmbeddings">;
  env?: LiteServerEnv;
  now?: Date;
}

interface LiteEmbeddingOptions extends Omit<LitePrepareCorpusOptions, "now"> {
  now: string;
}

export interface LiteSupabaseIngestionConfig {
  url: string;
  serviceRoleKey: string;
  schema: string;
}

export interface LiteSupabaseIngestionResult {
  dry_run: boolean;
  document_count: number;
  chunk_count: number;
  inserted_document_ids: string[];
  embedding: LiteEmbeddingSummary;
}

interface ChunkUnit {
  text: string;
  heading_path: string[];
  page_number?: number;
  section_label?: string;
  paragraph_index?: number;
  char_start: number;
  char_end: number;
  metadata: Record<string, unknown>;
}

export async function loadLiteCorpusFixture(path: string, options: { defaultCorpusVersion?: string } = {}): Promise<LiteCorpusFixture> {
  const raw = await readFile(path, "utf8");
  if (extname(path).toLowerCase() === ".md") {
    return liteCorpusFixtureSchema.parse({
      corpus_version: options.defaultCorpusVersion ?? SUPPORTED_LITE_CORPUS_VERSIONS[0],
      documents: [
        {
          id: slugify(path.replace(/\\/g, "/").split("/").pop()?.replace(/\.[^.]+$/, "") ?? "lite-markdown-source"),
          title: firstMarkdownHeading(raw) ?? "Lite Markdown Source",
          content_markdown: raw,
          visibility: "public",
        },
      ],
    });
  }

  return liteCorpusFixtureSchema.parse(JSON.parse(raw));
}

export async function prepareLiteCorpus(
  fixture: LiteCorpusFixture,
  options: LitePrepareCorpusOptions = {},
): Promise<LitePreparedCorpus> {
  const parsed = liteCorpusFixtureSchema.parse(fixture);
  const now = (options.now ?? new Date()).toISOString();
  const corpusVersion = options.defaultCorpusVersion ?? parsed.corpus_version;
  const documentsWithoutEmbeddings = parsed.documents.map((document) =>
    prepareLiteDocument(document, document.corpus_version ?? corpusVersion),
  );
  const allChunks = documentsWithoutEmbeddings.flatMap((document) => document.chunks);
  const embedding = await generateLiteChunkEmbeddings(allChunks, {
    defaultCorpusVersion: options.defaultCorpusVersion,
    embeddingMode: options.embeddingMode,
    deepseekClient: options.deepseekClient,
    env: options.env,
    now,
  });

  return {
    corpus_version: corpusVersion,
    documents: documentsWithoutEmbeddings,
    metadata: parsed.metadata,
    ingestion_version: LITE_CORPUS_INGESTION_VERSION,
    chunker_version: LITE_CHUNKER_VERSION,
    embedding,
  };
}

export async function ingestLiteCorpusToSupabase(
  corpus: LitePreparedCorpus,
  options: {
    config?: LiteSupabaseIngestionConfig;
    env?: LiteServerEnv;
    fetchImpl?: typeof fetch;
    dryRun?: boolean;
  } = {},
): Promise<LiteSupabaseIngestionResult> {
  if (options.dryRun) {
    return {
      dry_run: true,
      document_count: corpus.documents.length,
      chunk_count: corpus.documents.reduce((total, document) => total + document.chunks.length, 0),
      inserted_document_ids: [],
      embedding: corpus.embedding,
    };
  }

  const config = options.config ?? loadLiteSupabaseIngestionConfig(options.env);
  const client = new LiteSupabaseIngestionClient(config, options.fetchImpl ?? fetch);
  const insertedDocumentIds: string[] = [];

  for (const document of corpus.documents) {
    const documentId = await client.upsertDocument(document);
    insertedDocumentIds.push(documentId);
    await client.replaceChunks(documentId, document);
  }

  return {
    dry_run: false,
    document_count: corpus.documents.length,
    chunk_count: corpus.documents.reduce((total, document) => total + document.chunks.length, 0),
    inserted_document_ids: insertedDocumentIds,
    embedding: corpus.embedding,
  };
}

export function loadLiteSupabaseIngestionConfig(env: LiteServerEnv = process.env): LiteSupabaseIngestionConfig {
  const required = requireServerEnv(env, ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"], "Lite corpus ingestion Supabase");
  return {
    url: normalizeHttpBaseUrl(required.SUPABASE_URL, "SUPABASE_URL"),
    serviceRoleKey: required.SUPABASE_SERVICE_ROLE_KEY,
    schema: readOptionalServerEnv(env, "SUPABASE_LITE_SCHEMA") ?? "public",
  };
}

export class LiteSupabaseIngestionClient {
  private readonly config: LiteSupabaseIngestionConfig;
  private readonly fetchImpl: typeof fetch;

  constructor(config: LiteSupabaseIngestionConfig, fetchImpl: typeof fetch = fetch) {
    this.config = config;
    this.fetchImpl = fetchImpl;
  }

  async upsertDocument(document: LitePreparedDocument): Promise<string> {
    const response = await this.request(
      "lite_documents?on_conflict=corpus_version,source_content_hash&select=id",
      {
        method: "POST",
        body: JSON.stringify({
          corpus_version: document.corpus_version,
          title: document.title,
          source_url: document.source_url ?? null,
          publisher: document.publisher ?? null,
          document_date: document.document_date ?? null,
          visibility: document.visibility,
          source_content_hash: document.source_content_hash,
          metadata: {
            ...document.metadata,
            source_id: document.source_id,
            ingestion_version: LITE_CORPUS_INGESTION_VERSION,
            chunker_version: LITE_CHUNKER_VERSION,
          },
        }),
        headers: {
          Prefer: "resolution=merge-duplicates,return=representation",
        },
      },
    );
    const rows = (await response.json()) as Array<{ id?: string }>;
    const id = rows[0]?.id;
    if (!id) {
      throw new Error("Lite corpus document upsert did not return an id");
    }
    return id;
  }

  async replaceChunks(documentId: string, document: LitePreparedDocument): Promise<void> {
    await this.request(`lite_chunks?document_id=eq.${encodeURIComponent(documentId)}`, {
      method: "DELETE",
      headers: { Prefer: "return=minimal" },
    });

    if (document.chunks.length === 0) {
      return;
    }

    await this.request("lite_chunks", {
      method: "POST",
      body: JSON.stringify(
        document.chunks.map((chunk) => ({
          document_id: documentId,
          corpus_version: chunk.corpus_version,
          chunk_index: chunk.chunk_index,
          chunk_text: chunk.chunk_text,
          embedding: chunk.embedding,
          heading_path: chunk.heading_path,
          page_number: chunk.page_number ?? null,
          section_label: chunk.section_label ?? null,
          paragraph_index: chunk.paragraph_index ?? null,
          char_start: chunk.char_start,
          char_end: chunk.char_end,
          content_hash: chunk.content_hash,
          source_citation_label: chunk.source_citation_label,
          metadata: chunk.metadata,
        })),
      ),
      headers: { Prefer: "return=minimal" },
    });
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    const response = await this.fetchImpl(`${this.config.url}/rest/v1/${path}`, {
      ...init,
      headers: {
        ...liteSupabaseAuthHeaders(this.config.serviceRoleKey),
        apikey: this.config.serviceRoleKey,
        "Content-Type": "application/json",
        Accept: "application/json",
        "Content-Profile": this.config.schema,
        ...init.headers,
      },
    });
    if (!response.ok) {
      throw new Error(`Lite corpus Supabase write failed with HTTP ${response.status}`);
    }
    return response;
  }
}

function prepareLiteDocument(document: LiteCorpusDocumentInput, corpusVersion: string): LitePreparedDocument {
  const blocks = document.blocks ?? parseMarkdownBlocks(document.content_markdown ?? "");
  const normalizedBody = blocks.map(blockToCanonicalText).join("\n\n");
  const sourceContentHash = sha256Hex(
    JSON.stringify({
      source_id: document.id,
      title: document.title,
      publisher: document.publisher ?? null,
      document_date: document.document_date ?? null,
      normalized_body: normalizedBody,
    }),
  );
  const units = blocksToChunkUnits(blocks);
  const chunks = chunkUnits(units, document, corpusVersion, sourceContentHash);

  return {
    source_id: document.id,
    corpus_version: corpusVersion,
    title: document.title,
    source_url: document.source_url,
    publisher: document.publisher,
    document_date: document.document_date,
    visibility: document.visibility,
    source_content_hash: sourceContentHash,
    metadata: document.metadata,
    chunks,
  };
}

function parseMarkdownBlocks(markdown: string): LiteSourceBlock[] {
  const blocks: LiteSourceBlock[] = [];
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  let paragraph: string[] = [];

  const flushParagraph = () => {
    const text = paragraph.join(" ").replace(/\s+/g, " ").trim();
    if (text) {
      blocks.push({ type: "paragraph", text });
    }
    paragraph = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim() });
      continue;
    }

    if (/^[-*_]{3,}$/.test(line)) {
      flushParagraph();
      blocks.push({ type: "semantic_break" });
      continue;
    }

    if (line.includes("|") && !/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line)) {
      flushParagraph();
      const cells = line
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim())
        .filter(Boolean);
      if (cells.length > 1) {
        blocks.push({ type: "table_row", cells });
        continue;
      }
    }

    const transcript = /^([A-Za-z][A-Za-z0-9 .'-]{0,80}):\s+(.+)$/.exec(line);
    if (transcript) {
      flushParagraph();
      blocks.push({ type: "transcript_turn", speaker: transcript[1].trim(), text: transcript[2].trim() });
      continue;
    }

    paragraph.push(line);
  }

  flushParagraph();
  return blocks;
}

function blocksToChunkUnits(blocks: readonly LiteSourceBlock[]): ChunkUnit[] {
  const units: ChunkUnit[] = [];
  const headingPath: string[] = [];
  let cursor = 0;
  let paragraphIndex = 0;

  for (const block of blocks) {
    if (block.type === "heading") {
      headingPath.splice(block.level - 1);
      headingPath[block.level - 1] = block.text;
      cursor += block.text.length + 1;
      continue;
    }
    if (block.type === "semantic_break") {
      units.push({
        text: "",
        heading_path: [...headingPath],
        char_start: cursor,
        char_end: cursor,
        metadata: { semantic_break: block.label ?? true },
      });
      continue;
    }

    const text = blockToCanonicalText(block);
    const charStart = cursor;
    const charEnd = charStart + text.length;
    units.push({
      text,
      heading_path: [...headingPath].filter(Boolean),
      page_number: "page_number" in block ? block.page_number : undefined,
      section_label: "section_label" in block ? block.section_label : undefined,
      paragraph_index: "paragraph_index" in block ? block.paragraph_index ?? paragraphIndex : paragraphIndex,
      char_start: charStart,
      char_end: charEnd,
      metadata: unitMetadata(block),
    });
    paragraphIndex += 1;
    cursor = charEnd + 2;
  }

  return units;
}

function chunkUnits(
  units: readonly ChunkUnit[],
  document: LiteCorpusDocumentInput,
  corpusVersion: string,
  sourceContentHash: string,
): LitePreparedChunk[] {
  const chunks: LitePreparedChunk[] = [];
  let current: ChunkUnit[] = [];
  let currentLength = 0;
  let previousTail = "";

  const flush = () => {
    const primaryUnits = current.filter((unit) => unit.text);
    if (primaryUnits.length === 0) {
      current = [];
      currentLength = 0;
      return;
    }
    const overlapText = previousTail ? truncateAtWord(previousTail, LITE_CHUNK_OVERLAP_CHARS) : "";
    const primaryText = primaryUnits.map((unit) => unit.text).join("\n\n");
    const chunkText = [overlapText ? `Context overlap: ${overlapText}` : "", primaryText].filter(Boolean).join("\n\n");
    const first = primaryUnits[0];
    const last = primaryUnits[primaryUnits.length - 1];
    const headingPath = first.heading_path.length > 0 ? first.heading_path : ["Unsectioned"];
    const sourceLabel = document.source_citation_label ?? citationLabel(document, headingPath, first);
    const chunkIndex = chunks.length;
    const contentHash = sha256Hex(
      JSON.stringify({
        corpus_version: corpusVersion,
        source_content_hash: sourceContentHash,
        chunk_index: chunkIndex,
        heading_path: headingPath,
        text: chunkText,
      }),
    );

    chunks.push({
      source_id: document.id,
      corpus_version: corpusVersion,
      chunk_index: chunkIndex,
      chunk_text: chunkText,
      embedding: null,
      heading_path: headingPath,
      page_number: first.page_number,
      section_label: first.section_label ?? headingPath.at(-1),
      paragraph_index: first.paragraph_index,
      char_start: first.char_start,
      char_end: last.char_end,
      content_hash: contentHash,
      source_citation_label: sourceLabel,
      metadata: {
        source_id: document.id,
        source_content_hash: sourceContentHash,
        chunker_version: LITE_CHUNKER_VERSION,
        boundary_types: Array.from(new Set(primaryUnits.map((unit) => unit.metadata.boundary_type))),
        overlap_char_count: overlapText.length,
        unit_count: primaryUnits.length,
      },
    });
    previousTail = primaryText;
    current = [];
    currentLength = 0;
  };

  for (const unit of units) {
    if (!unit.text) {
      flush();
      previousTail = "";
      continue;
    }
    const headingChanged = current.length > 0 && current[0].heading_path.join("/") !== unit.heading_path.join("/");
    const wouldExceed = currentLength > 0 && currentLength + unit.text.length > LITE_CHUNK_MAX_CHARS;
    if (headingChanged || wouldExceed) {
      flush();
    }
    current.push(unit);
    currentLength += unit.text.length + 2;
  }
  flush();

  return chunks;
}

async function generateLiteChunkEmbeddings(
  chunks: LitePreparedChunk[],
  options: LiteEmbeddingOptions,
): Promise<LiteEmbeddingSummary> {
  const mode = resolveEmbeddingMode(options);

  if (mode === "none") {
    return {
      mode,
      version: "lite-no-embedding-v1",
      model: null,
      generated_at: options.now,
      chunk_count: chunks.length,
    };
  }

  if (mode === "fixture") {
    for (const chunk of chunks) {
      chunk.embedding = createDeterministicFixtureEmbedding(chunk.chunk_text, chunk.content_hash);
      chunk.metadata.embedding = {
        mode: "fixture",
        version: LITE_FIXTURE_EMBEDDING_VERSION,
        dimension: LITE_EMBEDDING_DIMENSION,
      };
    }
    return {
      mode,
      version: LITE_FIXTURE_EMBEDDING_VERSION,
      model: null,
      generated_at: options.now,
      chunk_count: chunks.length,
    };
  }

  const client = options.deepseekClient ?? createDeepSeekClient();
  const batchSize = 64;
  let metadata: LiteDeepSeekCallMetadata | undefined;
  for (let index = 0; index < chunks.length; index += batchSize) {
    const batch = chunks.slice(index, index + batchSize);
    const response = await client.generateEmbeddings(batch.map((chunk) => chunk.chunk_text));
    metadata = response.metadata;
    response.vectors.forEach((vector, offset) => {
      batch[offset].embedding = vector;
      batch[offset].metadata.embedding = {
        mode: "deepseek",
        version: "lite-embedding-v1",
        model: response.metadata.model,
        dimension: vector.length,
      };
    });
  }

  return {
    mode,
    version: "lite-embedding-v1",
    model: metadata?.model ?? null,
    generated_at: metadata?.generated_at ?? options.now,
    chunk_count: chunks.length,
    metadata,
  };
}

function resolveEmbeddingMode(
  options: Pick<LitePrepareCorpusOptions, "embeddingMode" | "deepseekClient" | "env">,
): Exclude<LiteEmbeddingMode, "auto"> {
  const requested = options.embeddingMode ?? "auto";
  if (requested !== "auto") {
    return requested;
  }
  const env = options.env ?? process.env;
  if (
    options.deepseekClient?.embeddingAvailable ||
    (env.DEEPSEEK_API_KEY?.trim() && env.DEEPSEEK_BASE_URL?.trim() && env.DEEPSEEK_EMBEDDING_MODEL?.trim())
  ) {
    return "deepseek";
  }
  return "fixture";
}

export function createDeterministicFixtureEmbedding(text: string, salt = ""): number[] {
  const values: number[] = [];
  let counter = 0;
  while (values.length < LITE_EMBEDDING_DIMENSION) {
    const digest = createHash("sha256").update(`${salt}\n${counter}\n${text}`).digest();
    for (const byte of digest) {
      values.push(byte / 127.5 - 1);
      if (values.length === LITE_EMBEDDING_DIMENSION) {
        break;
      }
    }
    counter += 1;
  }
  const magnitude = Math.sqrt(values.reduce((sum, value) => sum + value * value, 0)) || 1;
  return values.map((value) => Number((value / magnitude).toFixed(8)));
}

function blockToCanonicalText(block: LiteSourceBlock): string {
  if (block.type === "heading") {
    return block.text;
  }
  if (block.type === "paragraph") {
    return block.text;
  }
  if (block.type === "table_row") {
    if (Array.isArray(block.cells)) {
      return `${block.caption ? `${block.caption}: ` : ""}${block.cells.join(" | ")}`;
    }
    return `${block.caption ? `${block.caption}: ` : ""}${Object.entries(block.cells)
      .map(([key, value]) => `${key}: ${value}`)
      .join(" | ")}`;
  }
  if (block.type === "transcript_turn") {
    return `${block.timestamp ? `[${block.timestamp}] ` : ""}${block.speaker}: ${block.text}`;
  }
  return "";
}

function unitMetadata(block: LiteSourceBlock): Record<string, unknown> {
  return {
    boundary_type: block.type,
    ...(block.type === "transcript_turn" ? { speaker: block.speaker, timestamp: block.timestamp } : {}),
    ...(block.type === "table_row" ? { table_caption: block.caption } : {}),
  };
}

function citationLabel(document: LiteCorpusDocumentInput, headingPath: readonly string[], unit: ChunkUnit): string {
  const parts = [document.title];
  if (headingPath.at(-1)) {
    parts.push(String(headingPath.at(-1)));
  }
  if (unit.page_number) {
    parts.push(`page ${unit.page_number}`);
  } else if (unit.section_label) {
    parts.push(unit.section_label);
  } else if (unit.paragraph_index !== undefined) {
    parts.push(`paragraph ${unit.paragraph_index + 1}`);
  }
  return parts.join(", ").slice(0, 120);
}

function sha256Hex(input: string): string {
  return createHash("sha256").update(input).digest("hex");
}

function truncateAtWord(text: string, maxChars: number): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) {
    return normalized;
  }
  const tail = normalized.slice(-maxChars);
  return tail.replace(/^\S+\s+/, "").trim();
}

function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80) || "lite-source";
}

function firstMarkdownHeading(markdown: string): string | undefined {
  return markdown
    .split(/\r?\n/)
    .map((line) => /^#\s+(.+)$/.exec(line.trim())?.[1]?.trim())
    .find(Boolean);
}
