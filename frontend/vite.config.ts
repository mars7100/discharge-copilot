/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import flowbiteReact from "flowbite-react/plugin/vite";

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), ...(mode === "test" ? [] : [flowbiteReact()])],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
}));
