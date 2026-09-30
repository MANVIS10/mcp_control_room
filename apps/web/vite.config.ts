import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build lands inside the Python package so `pip install` ships the dashboard.
export default defineConfig({ plugins: [react()], build: { outDir: "../api/app/static", emptyOutDir: true } });
