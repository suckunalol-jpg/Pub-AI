import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          950: "#0a0a1a",
          900: "#0d1b2a",
          800: "#1b2838",
          700: "#1f3044",
          600: "#264060",
        },
        accent: {
          DEFAULT: "#00aaff",
          dark: "#0066ff",
          glow: "#00aaff40",
        },
        glass: {
          DEFAULT: "rgba(255, 255, 255, 0.05)",
          light: "rgba(255, 255, 255, 0.1)",
          border: "rgba(255, 255, 255, 0.1)",
        },
      },
      backdropBlur: {
        xs: "2px",
        xl: "24px",
        "2xl": "40px",
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        "pulse-glow": "pulseGlow 2s ease-in-out infinite",
        "terminal-blink": "terminalBlink 1s step-end infinite",
        "typewriter-cursor": "typewriterCursor 0.6s step-end infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseGlow: {
          "0%, 100%": { boxShadow: "0 0 5px #00aaff20" },
          "50%": { boxShadow: "0 0 20px #00aaff40" },
        },
        terminalBlink: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
        typewriterCursor: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0" },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};

export default config;
