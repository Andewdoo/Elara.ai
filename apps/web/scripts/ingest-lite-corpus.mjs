#!/usr/bin/env node
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const tempRoot = join(root, "tests", ".tmp", `lite-ingest-cli-${process.pid}`);

const args = parseArgs(process.argv.slice(2));
if (!args.input) {
  console.error("Usage: node scripts/ingest-lite-corpus.mjs --input <fixture.json|source.md> [--embedding-mode auto|deepseek|fixture|none] [--dry-run]");
  process.exit(1);
}

try {
  const ingestion = await compileLiteIngestionModules();
  const fixture = await ingestion.loadLiteCorpusFixture(args.input, {
    defaultCorpusVersion: process.env.LITE_CORPUS_VERSION || "lite-corpus-v1",
  });
  const corpus = await ingestion.prepareLiteCorpus(fixture, {
    defaultCorpusVersion: process.env.LITE_CORPUS_VERSION || fixture.corpus_version,
    embeddingMode: args.embeddingMode ?? "auto",
  });
  const result = await ingestion.ingestLiteCorpusToSupabase(corpus, { dryRun: Boolean(args.dryRun) });
  console.log(JSON.stringify(result, null, 2));
} finally {
  await rm(tempRoot, { recursive: true, force: true });
}

async function compileLiteIngestionModules() {
  const ts = require("typescript");
  const files = ["schemas.ts", "server-config.ts", "deepseek.ts", "ingestion.ts"];
  const moduleDir = join(tempRoot, "lib", "lite");
  await mkdir(moduleDir, { recursive: true });
  await writeFile(join(tempRoot, "package.json"), "{\"type\":\"commonjs\"}", "utf8");

  for (const file of files) {
    const sourcePath = join(root, "lib", "lite", file);
    const source = await readFile(sourcePath, "utf8");
    const output = ts.transpileModule(source, {
      fileName: sourcePath,
      reportDiagnostics: true,
      compilerOptions: {
        esModuleInterop: true,
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    });
    const errors = output.diagnostics?.filter((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error) ?? [];
    if (errors.length > 0) {
      throw new Error(`${file} failed to transpile for Lite ingestion CLI`);
    }
    await writeFile(join(moduleDir, file.replace(/\.ts$/, ".js")), output.outputText, "utf8");
  }

  return require(join(moduleDir, "ingestion.js"));
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--dry-run") {
      parsed.dryRun = true;
      continue;
    }
    if (arg === "--input") {
      parsed.input = argv[++index];
      continue;
    }
    if (arg === "--embedding-mode") {
      parsed.embeddingMode = argv[++index];
      if (!["auto", "deepseek", "fixture", "none"].includes(parsed.embeddingMode)) {
        throw new Error("--embedding-mode must be auto, deepseek, fixture, or none");
      }
      continue;
    }
    throw new Error(`Unknown argument: ${arg}`);
  }
  return parsed;
}
