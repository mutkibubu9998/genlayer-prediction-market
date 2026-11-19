import { defineConfig } from "vite";

export default defineConfig({
  // GitHub Pages project site: https://mutkibubu9998.github.io/genlayer-prediction-market/
  base: "/genlayer-prediction-market/",
  build: {
    outDir: "../docs",
    emptyOutDir: true,
  },
});
