import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The compiled bundle is served by Flask from the same origin, so there is no
// CORS and no separate token store: the HttpOnly session cookie just works.
// In dev, Vite proxies the API to Flask so that stays true locally too.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5000",
        changeOrigin: false,
      },
    },
  },
});
