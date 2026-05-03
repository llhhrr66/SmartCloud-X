import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ['"Instrument Serif"', "serif"],
        body: ['"General Sans"', '"Noto Sans SC"', "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
      colors: {
        ink: { 50: "#f0f2f8", 100: "#d9ddf0", 200: "#b3bbdf", 300: "#8d99cf", 400: "#6777bf", 500: "#4155af", 600: "#34448d", 700: "#27336b", 800: "#1a2249", 900: "#0d1127", 950: "#060913" },
        volt: { 50: "#eefbf3", 100: "#d6f6e2", 200: "#adedc5", 300: "#84e4a8", 400: "#5bdb8b", 500: "#33d26e", 600: "#29a859", 700: "#1f7e43", 800: "#15542e", 900: "#0b2a18" },
        frost: { 50: "#edf6ff", 100: "#d4e9ff", 200: "#a9d3ff", 300: "#7ebdff", 400: "#53a7ff", 500: "#2891ff", 600: "#2074cc", 700: "#185799", 800: "#103a66", 900: "#081d33" },
        ember: { 50: "#fff5ed", 100: "#ffe6d1", 200: "#ffcca3", 300: "#ffb375", 400: "#ff9a47", 500: "#ff8119", 600: "#cc670e", 700: "#994d0b", 800: "#663308", 900: "#331a04" },
        slate: { 50: "#f4f5f7", 100: "#e0e3ea", 200: "#c1c7d4", 300: "#a2abbe", 400: "#838fa8", 500: "#647392", 600: "#4f5c75", 700: "#3a4558", 800: "#252e3b", 900: "#101720" },
      },
      borderRadius: {
        "4xl": "2rem",
        "5xl": "2.5rem",
      },
      boxShadow: {
        glow: "0 0 40px -12px rgba(40,145,255,0.45)",
        "glow-volt": "0 0 40px -12px rgba(51,210,110,0.45)",
        "glow-ember": "0 0 40px -12px rgba(255,129,25,0.45)",
        glass: "0 8px 32px rgba(13,17,39,0.18), inset 0 0 0 1px rgba(255,255,255,0.06)",
        "glass-lg": "0 24px 64px rgba(13,17,39,0.28), inset 0 0 0 1px rgba(255,255,255,0.08)",
        panel: "0 2px 16px rgba(13,17,39,0.08)",
      },
      animation: {
        "fade-in": "fadeIn 0.35s ease-out both",
        "slide-up": "slideUp 0.4s cubic-bezier(0.16,1,0.3,1) both",
        "slide-in-right": "slideInRight 0.35s cubic-bezier(0.16,1,0.3,1) both",
        "scale-in": "scaleIn 0.3s cubic-bezier(0.16,1,0.3,1) both",
        shimmer: "shimmer 1.8s ease-in-out infinite",
        pulse: "pulse 2.4s ease-in-out infinite",
        "toast-in": "toastIn 0.4s cubic-bezier(0.16,1,0.3,1) both",
        "toast-out": "toastOut 0.25s ease-in both",
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: { "0%": { opacity: "0", transform: "translateY(16px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        slideInRight: { "0%": { opacity: "0", transform: "translateX(20px)" }, "100%": { opacity: "1", transform: "translateX(0)" } },
        scaleIn: { "0%": { opacity: "0", transform: "scale(0.96)" }, "100%": { opacity: "1", transform: "scale(1)" } },
        shimmer: { "0%,100%": { backgroundPosition: "-200% 0" }, "50%": { backgroundPosition: "200% 0" } },
        pulse: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.55" } },
        toastIn: { "0%": { opacity: "0", transform: "translateX(100%) scale(0.9)" }, "100%": { opacity: "1", transform: "translateX(0) scale(1)" } },
        toastOut: { "0%": { opacity: "1", transform: "translateX(0) scale(1)" }, "100%": { opacity: "0", transform: "translateX(100%) scale(0.9)" } },
      },
    },
  },
  plugins: [],
} satisfies Config;
