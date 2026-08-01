/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        oncall: {
          bg: "#0b1220",
          panel: "#111b2e",
          card: "#16243b",
          border: "#1e3a5f",
          accent: "#10b981",
          accent2: "#34d399",
          muted: "#94a3b8",
        },
      },
      keyframes: {
        "fade-slide": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
      },
      animation: {
        "fade-slide": "fade-slide 0.25s ease-out",
        "pulse-soft": "pulse-soft 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
}
