import tailwindcss from "@tailwindcss/vite"
import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vite"

const backendTarget = process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8000"

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: backendTarget },
      "/health": { target: backendTarget },
      "/internal": { target: backendTarget },
    },
  },
})
