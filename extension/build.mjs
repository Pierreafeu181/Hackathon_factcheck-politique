import { build, context } from "esbuild";
import { cpSync, mkdirSync } from "node:fs";

const watch = process.argv.includes("--watch");
const options = {
  entryPoints: ["src/background.ts", "src/sidepanel.ts", "src/extract.ts"],
  outdir: "dist",
  bundle: true,
  format: "iife",
  target: "chrome120",
  logLevel: "info",
};

mkdirSync("dist", { recursive: true });
cpSync("static", "dist", { recursive: true });

if (watch) {
  await (await context(options)).watch();
} else {
  await build(options);
}
