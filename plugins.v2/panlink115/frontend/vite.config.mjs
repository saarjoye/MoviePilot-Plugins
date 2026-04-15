import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import federation from "@originjs/vite-plugin-federation";

export default defineConfig({
  plugins: [
    vue(),
    federation({
      name: "Panlink115",
      filename: "remoteEntry.js",
      exposes: {
        "./Page": "./src/components/Page.vue",
        "./Config": "./src/components/Config.vue",
        "./Dashboard": "./src/components/Dashboard.vue"
      },
      shared: {
        vue: {
          requiredVersion: false,
          generate: false
        },
        vuetify: {
          requiredVersion: false,
          generate: false,
          singleton: true
        }
      },
      format: "esm"
    })
  ],
  build: {
    target: "esnext",
    minify: false,
    cssCodeSplit: true,
    assetsDir: "",
    outDir: "../dist/assets",
    emptyOutDir: true
  }
});
