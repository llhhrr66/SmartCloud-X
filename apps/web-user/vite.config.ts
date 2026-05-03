import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import { resolve } from "node:path";

const here = fileURLToPath(new URL(".", import.meta.url));
const ROOT = resolve(here, "../..");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: [
      // longer paths first so subpath aliases match before the bare package alias
      { find: "@smartcloud-x/frontend-sdk/core",      replacement: resolve(ROOT, "packages/frontend-sdk/src/core/index.ts") },
      { find: "@smartcloud-x/frontend-sdk/web-user",  replacement: resolve(ROOT, "packages/frontend-sdk/src/web-user/index.ts") },
      { find: "@smartcloud-x/frontend-sdk/web-admin", replacement: resolve(ROOT, "packages/frontend-sdk/src/web-admin/index.ts") },
      { find: "@smartcloud-x/frontend-sdk",           replacement: resolve(ROOT, "packages/frontend-sdk/src/index.ts") },
      { find: "@smartcloud-x/common-schemas",         replacement: resolve(ROOT, "packages/common-schemas/src/index.ts") },
      { find: "@smartcloud-x/common-auth",            replacement: resolve(ROOT, "packages/common-auth/src/index.ts") },
      { find: "@smartcloud-x/common",                 replacement: resolve(ROOT, "packages/common/src/index.ts") },
      { find: "@",                                    replacement: resolve(here, "./src") },
    ],
  },
  server: {
    host: "0.0.0.0",
    port: 3100,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
