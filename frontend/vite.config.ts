import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import pkg from "./package.json"

const devApiTarget = process.env.VITE_DEV_API_TARGET || "http://127.0.0.1:5611"
const devWsTarget = devApiTarget.replace(/^http/, "ws")
const buildTimestamp = Date.now()

function getNodeModuleName(normalizedId: string) {
  const marker = "/node_modules/"
  const markerIndex = normalizedId.lastIndexOf(marker)
  if (markerIndex === -1) return null

  const parts = normalizedId.slice(markerIndex + marker.length).split("/")
  if (!parts[0]) return null
  if (parts[0].startsWith("@") && parts[1]) return `${parts[0]}/${parts[1]}`
  return parts[0]
}

function manualChunks(id: string) {
  const normalizedId = id.split(path.sep).join("/")

  if (normalizedId.includes("/node_modules/")) {
    const packageName = getNodeModuleName(normalizedId)
    if (!packageName) return "vendor"

    if (["react", "react-dom", "scheduler"].includes(packageName)) {
      return "vendor-react"
    }
    if (packageName.startsWith("@radix-ui/")) {
      return "vendor-radix"
    }
    if (
      packageName === "recharts" ||
      packageName === "chart.js" ||
      packageName === "react-chartjs-2" ||
      packageName === "lightweight-charts" ||
      packageName === "victory-vendor" ||
      packageName.startsWith("d3-")
    ) {
      return "vendor-charts"
    }
    if (packageName === "monaco-editor" || packageName === "@monaco-editor/react") {
      return "vendor-monaco"
    }
    if (packageName === "lucide-react") {
      return "vendor-icons"
    }
    if (
      packageName === "react-markdown" ||
      packageName === "react-syntax-highlighter" ||
      packageName.startsWith("remark-") ||
      packageName.startsWith("rehype-") ||
      packageName.startsWith("mdast-") ||
      packageName.startsWith("hast-") ||
      packageName.startsWith("unist-") ||
      packageName.startsWith("micromark") ||
      packageName === "unified" ||
      packageName === "parse5" ||
      packageName === "vfile" ||
      packageName === "vfile-message" ||
      packageName === "property-information" ||
      packageName === "entities"
    ) {
      return "vendor-markdown"
    }
    if (packageName.startsWith("@assistant-ui/")) {
      return "vendor-assistant-ui"
    }
    if (
      packageName === "ethers" ||
      packageName === "aes-js" ||
      packageName.startsWith("@adraffy/") ||
      packageName.startsWith("@noble/")
    ) {
      return "vendor-ethers"
    }
    if (packageName === "i18next" || packageName === "react-i18next" || packageName.startsWith("i18next-")) {
      return "vendor-i18n"
    }
    if (packageName === "react-hot-toast" || packageName === "goober") {
      return "vendor-hot-toast"
    }
    if (["dayjs", "js-cookie"].includes(packageName)) {
      return "vendor-app-utils"
    }
    return "vendor-core"
  }

  if (normalizedId.includes("/app/components/hyper-ai/")) return "feature-hyper-ai"
  if (normalizedId.includes("/app/components/klines/")) return "feature-klines"
  if (normalizedId.includes("/app/components/signal/")) return "feature-signals"
  if (normalizedId.includes("/app/components/program/")) return "feature-program"
  if (normalizedId.includes("/app/components/portfolio/")) return "feature-portfolio"
  if (normalizedId.includes("/app/components/analytics/")) return "feature-analytics"
  if (normalizedId.includes("/app/components/hyperliquid/")) return "feature-hyperliquid"
  if (normalizedId.includes("/app/components/settings/")) return "feature-settings"
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        entryFileNames: `assets/[name]-[hash]-${buildTimestamp}.js`,
        chunkFileNames: `assets/[name]-[hash]-${buildTimestamp}.js`,
        assetFileNames: `assets/[name]-[hash]-${buildTimestamp}.[ext]`,
        manualChunks,
      }
    }
  },
  server: {
    host: "0.0.0.0",
    port: 8802,
    allowedHosts: true,  // Allow all hosts for flexible deployment
    proxy: {
      '/api': {
        target: devApiTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: devWsTarget,
        changeOrigin: true,
        ws: true,
      },
      // Backend serves branding/logo assets under /static (e.g. logo_app.png);
      // proxy it in dev so those URLs resolve like they do in production.
      '/static': {
        target: devApiTarget,
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./app"),
    },
  },
})
