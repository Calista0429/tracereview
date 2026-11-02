// Copies the four fictional sample PDFs (and their manifest) into public/samples so the
// list page can offer them through the normal upload path.
import { cp, mkdir, readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "..", "fixtures");
const target = join(here, "..", "public", "samples");

const manifest = JSON.parse(await readFile(join(source, "manifest.json"), "utf8"));
await mkdir(target, { recursive: true });
await cp(join(source, "manifest.json"), join(target, "manifest.json"));
for (const sample of manifest.samples) {
  await cp(join(source, sample.file), join(target, sample.file));
}
console.log(`Synced ${manifest.samples.length} samples to public/samples`);
