import { mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { dirname, basename, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ARCHIVE_SCHEMA_VERSION = 1;
const DEFAULT_EXPECTED_COUNT = 12;
const REQUEST_TIMEOUT_MS = 15_000;
const PASSING_CITATION_STATUSES = new Set(["passed", "partial"]);
const PUBLISHABLE_STATES = new Set(["published", "approved", "unreviewed"]);
const RESOURCE_NAMES = ["run", "report", "sources", "source-graph"];
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const defaultOutputDir = fileURLToPath(new URL("../public/demo-archive", import.meta.url));

export async function snapshotDemoArchive({
  apiBaseUrl,
  outputDir = defaultOutputDir,
  expectedCount = DEFAULT_EXPECTED_COUNT,
  fetchImpl = fetch,
  generatedAt = new Date(),
}) {
  const normalizedApiBaseUrl = requireHttpOrigin(apiBaseUrl);
  const resolvedOutputDir = resolve(outputDir);
  if (basename(resolvedOutputDir) !== "demo-archive") {
    throw new Error("The snapshot output directory must be named demo-archive.");
  }

  const history = await fetchJson(fetchImpl, `${normalizedApiBaseUrl}/v1/demo-runs`);
  validateHistory(history, expectedCount);

  const artifacts = [];
  for (const item of history.items) {
    const runId = item.run_id;
    const resourceEntries = await Promise.all(
      RESOURCE_NAMES.map(async (resource) => {
        const suffix = resource === "run" ? "" : `/${resource}`;
        return [resource, await fetchJson(fetchImpl, `${normalizedApiBaseUrl}/v1/demo-runs/${runId}${suffix}`)];
      }),
    );
    const resources = Object.fromEntries(resourceEntries);
    validatePublishedRun(item, resources);
    artifacts.push({ runId, resources });
  }

  const manifest = {
    schema_version: ARCHIVE_SCHEMA_VERSION,
    generated_at: generatedAt.toISOString(),
    items: history.items,
    total: history.items.length,
    page: 1,
    page_size: expectedCount,
  };

  await replaceArchiveDirectory(resolvedOutputDir, async (stagingDir) => {
    for (const { runId, resources } of artifacts) {
      const runDir = join(stagingDir, "runs", runId);
      await mkdir(runDir, { recursive: true });
      for (const resource of RESOURCE_NAMES) {
        await writeJson(join(runDir, `${resource}.json`), resources[resource]);
      }
    }
    await writeJson(join(stagingDir, "manifest.json"), manifest);
  });

  return { count: artifacts.length, generatedAt: manifest.generated_at, outputDir: resolvedOutputDir };
}

export async function validateBundledDemoArchive({
  outputDir = defaultOutputDir,
  expectedCount = DEFAULT_EXPECTED_COUNT,
} = {}) {
  const resolvedOutputDir = requireArchiveDirectory(outputDir);
  const manifest = await readJson(join(resolvedOutputDir, "manifest.json"));
  validateHistory(manifest, expectedCount);
  if (manifest.total !== expectedCount || manifest.page !== 1 || manifest.page_size !== expectedCount) {
    throw new Error("The bundled Demo archive manifest count metadata is inconsistent.");
  }

  const expectedRunIds = new Set(manifest.items.map((item) => item.run_id));
  const runEntries = await readdir(join(resolvedOutputDir, "runs"), { withFileTypes: true });
  const bundledRunIds = runEntries.filter((entry) => entry.isDirectory()).map((entry) => entry.name);
  if (bundledRunIds.length !== expectedCount || bundledRunIds.some((runId) => !expectedRunIds.has(runId))) {
    throw new Error("The bundled Demo archive run directories do not match its manifest.");
  }

  for (const item of manifest.items) {
    const resources = Object.fromEntries(
      await Promise.all(
        RESOURCE_NAMES.map(async (resource) => [
          resource,
          await readJson(join(resolvedOutputDir, "runs", item.run_id, `${resource}.json`)),
        ]),
      ),
    );
    validatePublishedRun(item, resources);
  }

  return { count: expectedCount, generatedAt: manifest.generated_at, outputDir: resolvedOutputDir };
}

function requireHttpOrigin(value) {
  if (!value) throw new Error("An API base URL is required.");
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("The API base URL must be an HTTP(S) origin without credentials or a path.");
  }
  return url.origin;
}

async function fetchJson(fetchImpl, url) {
  const response = await fetchImpl(url, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!response.ok) throw new Error(`Archive source request failed with status ${response.status}.`);
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new Error("Archive source returned a non-JSON response.");
  }
  return await response.json();
}

function validateHistory(history, expectedCount) {
  if (!history || !Array.isArray(history.items)) throw new Error("The Demo archive list is malformed.");
  if (!Number.isInteger(expectedCount) || expectedCount < 1) throw new Error("Expected count must be a positive integer.");
  if (history.items.length !== expectedCount) {
    throw new Error(`Expected ${expectedCount} designated Demo reports, received ${history.items.length}.`);
  }
  const ids = new Set();
  for (const item of history.items) {
    if (!UUID_PATTERN.test(item?.run_id ?? "")) throw new Error("A Demo archive run ID is invalid.");
    if (ids.has(item.run_id)) throw new Error("The Demo archive contains a duplicate run ID.");
    if (item.status !== "COMPLETED" || !item.evidence_reviewed_at) {
      throw new Error(`Demo report ${item.run_id} is not durably citation-audited and completed.`);
    }
    ids.add(item.run_id);
  }
}

function validatePublishedRun(item, resources) {
  const { run, report, sources, "source-graph": sourceGraph } = resources;
  if (run?.run_id !== item.run_id || report?.run_id !== item.run_id) {
    throw new Error(`Demo report ${item.run_id} returned mismatched resource identifiers.`);
  }
  if (run.status !== "COMPLETED" || !PUBLISHABLE_STATES.has(run.publication_state)) {
    throw new Error(`Demo report ${item.run_id} is not publishable.`);
  }
  if (!report.evidence_reviewed_at || !Array.isArray(report.report_sentences) || report.report_sentences.length === 0) {
    throw new Error(`Demo report ${item.run_id} has no durable citation audit.`);
  }
  if (report.report_sentences.some((citation) => !PASSING_CITATION_STATUSES.has(citation.audit_status))) {
    throw new Error(`Demo report ${item.run_id} contains a failing citation audit.`);
  }
  if (!Array.isArray(sources?.sources) || !Array.isArray(sourceGraph?.nodes) || !Array.isArray(sourceGraph?.edges)) {
    throw new Error(`Demo report ${item.run_id} returned malformed supporting resources.`);
  }
}

async function replaceArchiveDirectory(outputDir, build) {
  const parent = dirname(outputDir);
  const nonce = `${process.pid}-${Date.now()}`;
  const stagingDir = join(parent, `.demo-archive-staging-${nonce}`);
  const backupDir = join(parent, `.demo-archive-backup-${nonce}`);
  let previousMoved = false;

  await mkdir(parent, { recursive: true });
  await mkdir(stagingDir, { recursive: true });
  try {
    await build(stagingDir);
    try {
      await rename(outputDir, backupDir);
      previousMoved = true;
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    await rename(stagingDir, outputDir);
    if (previousMoved) await rm(backupDir, { recursive: true, force: true });
  } catch (error) {
    await rm(stagingDir, { recursive: true, force: true });
    if (previousMoved) {
      await rm(outputDir, { recursive: true, force: true });
      await rename(backupDir, outputDir);
    }
    throw error;
  }
}

function requireArchiveDirectory(outputDir) {
  const resolvedOutputDir = resolve(outputDir);
  if (basename(resolvedOutputDir) !== "demo-archive") {
    throw new Error("The snapshot output directory must be named demo-archive.");
  }
  return resolvedOutputDir;
}

async function readJson(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    throw new Error(`The bundled Demo archive is missing or malformed: ${path}`, { cause: error });
  }
}

async function writeJson(path, value) {
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function parseArguments(argv) {
  const options = {
    apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? process.env.API_BASE_URL,
    outputDir: defaultOutputDir,
    expectedCount: DEFAULT_EXPECTED_COUNT,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    const value = argv[index + 1];
    if (argument === "--api-base-url" && value) options.apiBaseUrl = value;
    else if (argument === "--output-dir" && value) options.outputDir = value;
    else if (argument === "--expected-count" && value) options.expectedCount = Number(value);
    else throw new Error(`Unsupported or incomplete argument: ${argument}`);
    index += 1;
  }
  return options;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  snapshotDemoArchive(parseArguments(process.argv.slice(2)))
    .then((result) => {
      process.stdout.write(`Published ${result.count} static Demo reports to ${result.outputDir}.\n`);
    })
    .catch((error) => {
      process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 1;
    });
}
