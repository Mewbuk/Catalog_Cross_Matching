/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        space:  "#0B1020",   // midnight base
        panel:  "#141B2E",   // instrument panel
        panel2: "#1B2540",   // raised panel
        line:   "#26314F",   // hairline
        ink:    "#E6ECF7",   // primary text
        muted:  "#8A97B4",   // secondary text
        cyan:   "#38BDF8",   // detections
        known:  "#34D399",   // catalog match
        newobj: "#FB7185",   // new / unknown
        amber:  "#FBBF24",
      },
      fontFamily: {
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        mono:    ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
