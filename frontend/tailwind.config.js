/* CODesk palette: a cash-desk ledger. Banknote green for the frame, paper for the work surface,
   brass for money still on its way, a firm red for shortages, leaf green for what agrees. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Schibsted Grotesk Variable", "system-ui", "sans-serif"] },
      colors: {
        ledger: { 950: "#08201a", 900: "#0f2e22", 800: "#173d2f", 700: "#21503e", 300: "#9fbcae" },
        paper: { DEFAULT: "#f3f5f2", line: "#e1e6e0", deep: "#e8ece6" },
        ink: { DEFAULT: "#16211c", soft: "#4a5650", faint: "#7c8781" },
        leaf: { DEFAULT: "#1d7a55", dark: "#145c3f", soft: "#e2f1e9" },
        brass: { DEFAULT: "#b07a1c", dark: "#86590c", soft: "#f8eed9", glow: "#e2b55a" },
        short: { DEFAULT: "#b8402e", dark: "#922f20", soft: "#fae8e4" },
      },
      borderRadius: { panel: "12px" },
      boxShadow: {
        panel: "0 0 0 1px rgba(22,33,28,.06), 0 1px 2px rgba(22,33,28,.04)",
        pop: "0 0 0 1px rgba(22,33,28,.08), 0 12px 32px -12px rgba(22,33,28,.28)",
      },
      keyframes: {
        slideIn: { from: { transform: "translateX(-100%)" }, to: { transform: "translateX(0)" } },
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { slideIn: "slideIn .22s ease-out both", rise: "rise .2s ease-out both" },
    },
  },
  plugins: [],
};
