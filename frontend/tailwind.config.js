/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        space:  "#070B14",   // HUD base
        panel:  "#0A1220",   // panel fill (over the grid)
        panel2: "#0E1A2B",   // raised
        line:   "#17324A",   // HUD hairline
        ink:    "#EAF2FB",   // bright text
        muted:  "#6B8BB0",   // HUD muted (bluish)
        cyan:   "#38BDF8",   // detections / accent
        known:  "#34D399",   // catalog match
        newobj: "#FB7185",   // new / unknown
        amber:  "#FBBF24",
      },
      fontFamily: {
        serif:   ["var(--font-serif)", "Georgia", "serif"],       // editorial hero
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        mono:    ["var(--font-mono)", "ui-monospace", "monospace"], // JetBrains Mono
      },
    },
  },
  plugins: [],
};
