import { defineConfig } from "@rsbuild/core";
import { pluginReact } from "@rsbuild/plugin-react";

export default defineConfig({
  plugins: [pluginReact()],
  server: {
    host: "127.0.0.1",
    port: 3000,
  },
  source: {
    entry: {
      index: "./src/renderer/index.tsx",
    },
  },
  html: {
    title: "Jarvis Assistant",
    template: "./src/renderer/index.html",
  },
  output: {
    assetPrefix: "./",
    distPath: {
      root: "dist",
    },
  },
});

