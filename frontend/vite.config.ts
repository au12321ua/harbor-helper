import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve, relative } from "node:path";
import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "harbor-build-identity",
      writeBundle() {
        const root = resolve(
          import.meta.dirname,
          "../src/harbor_helper/static",
        );
        const files = readdirSync(root, {
          recursive: true,
          withFileTypes: true,
        })
          .filter((item) => item.isFile() && item.name !== "index.html")
          .map((item) => resolve(item.parentPath, item.name))
          .sort();
        const hash = createHash("sha256");
        for (const file of files) {
          hash.update(relative(root, file));
          hash.update(readFileSync(file));
        }
        const index = resolve(root, "index.html");
        writeFileSync(
          index,
          readFileSync(index, "utf8").replace(
            "</head>",
            `<meta name="hh-build" content="${hash.digest("hex")}" /></head>`,
          ),
        );
      },
    },
  ],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "../src/harbor_helper/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
