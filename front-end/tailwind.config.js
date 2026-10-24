
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",

  content: ["./index.html", "./src/**/*.{ts,tsx}"],

  theme: {
    extend: {
      colors: {
        ink: "#10231e",
        leaf: "#2f7d5c",
        mint: "#dff4e9",
        sand: "#f7f4ed",
        amber: "#d99028",
      },

      boxShadow: {
        soft: "0 20px 60px rgba(16, 35, 30, 0.10)",
      },
    },
  },

  plugins: [],
};
