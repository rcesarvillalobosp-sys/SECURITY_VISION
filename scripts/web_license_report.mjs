// Inventario de licencias de las dependencias de PRODUCCIÓN del frontend (las que se empaquetan).
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const web = process.argv[2] ?? "apps/web";
const tree = JSON.parse(execSync("npm ls --omit=dev --all --json", { cwd: web, encoding: "utf8" }));
const seen = new Map();
(function walk(deps) {
  for (const [name, info] of Object.entries(deps ?? {})) {
    if (seen.has(name)) continue;
    let lic = "DESCONOCIDA";
    try {
      const pkg = JSON.parse(readFileSync(join(web, "node_modules", name, "package.json"), "utf8"));
      lic = typeof pkg.license === "string" ? pkg.license : pkg.license?.type ?? "DESCONOCIDA";
    } catch { /* paquete anidado */ }
    seen.set(name, { version: info.version, lic });
    walk(info.dependencies);
  }
})(tree.dependencies);
const bad = [...seen].filter(([, v]) => /GPL|AGPL|SSPL|DESCONOCIDA/i.test(v.lic) && !/LGPL/i.test(v.lic));
const rows = [...seen].sort().map(([n, v]) => `| ${n} | ${v.version} | ${v.lic} |`).join("\n");
writeFileSync("docs/licenses/web-dependencies.md",
  `# Licencias de dependencias del frontend (producción, generado)\n\nRegenerar con \`node scripts/web_license_report.mjs\`.\n\n| Paquete | Versión | Licencia |\n|---|---|---|\n${rows}\n`);
console.log(`${seen.size} paquetes de producción; a revisar: ${bad.length ? bad.map(([n, v]) => `${n} (${v.lic})`).join(", ") : "ninguno"}`);
process.exit(bad.length && process.argv.includes("--check") ? 1 : 0);
