import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export function readPackageVersion(frontendRoot: string): string {
  const packageJson = JSON.parse(readFileSync(resolve(frontendRoot, "../package.json"), "utf8")) as { version: string };
  return packageJson.version;
}
