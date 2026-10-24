// Fails when src/lib/schema.d.ts is not what `npm run gen:api` makes from the committed
// OpenAPI document (13 F-20): a changed API must come with regenerated web types.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "maestro-api-"));
try {
  const fresh = join(dir, "schema.d.ts");
  execFileSync("npx", [
    "openapi-typescript",
    "../openapi/maestro-v1.json",
    "--default-non-nullable",
    "false",
    "-o",
    fresh,
  ], {
    stdio: ["ignore", "ignore", "inherit"],
  });
  if (readFileSync(fresh, "utf8") !== readFileSync("src/lib/schema.d.ts", "utf8")) {
    console.error(
      "src/lib/schema.d.ts is out of date with ../openapi/maestro-v1.json; run `npm run gen:api`.",
    );
    process.exit(1);
  }
  console.log("src/lib/schema.d.ts matches the OpenAPI document.");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
