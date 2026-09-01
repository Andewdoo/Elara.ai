import { validateBundledDemoArchive } from "./snapshot-demo-archive.mjs";

validateBundledDemoArchive()
  .then((result) => {
    process.stdout.write(`Verified ${result.count} bundled Demo reports.\n`);
  })
  .catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
