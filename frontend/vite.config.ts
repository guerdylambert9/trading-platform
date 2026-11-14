import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the dashboard runs on :5173 and forwards /api to `trader serve` on :8000.
// `npm run build` writes frontend/dist, which `trader serve` then hosts on :8000 by itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
