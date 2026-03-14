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
          950: "#000000", // pure black base
          900: "#020813",
          800: "#0a1324",
          700: "#112038",
          600: "#182e4c",
        },
        accent: {
          DEFAULT: "#5b8bb8", // darkish pastel blue
          dark: "#4a759c",
          glow: "#5b8bb840",
        },
        glass: {
          DEFAULT: "rgba(91, 139, 184, 0.05)",
          light: "rgba(91, 139, 184, 0.1)",
          border: "rgba(91, 139, 184, 0.3)",
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
          "0%, 100%": { boxShadow: "0 0 5px #5b8bb820" },
          "50%": { boxShadow: "0 0 20px #5b8bb840" },
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
