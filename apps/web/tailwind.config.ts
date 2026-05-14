import type { Config } from "tailwindcss";

// Tailwind v3 is the Phase 1 pin (see 01-RESEARCH.md Open Question O-1 + apps/web/README.md).
// Phase 7 may revisit v4 when the dense Bloomberg-style styling work begins.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
