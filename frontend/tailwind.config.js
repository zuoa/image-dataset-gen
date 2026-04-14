export default {
    darkMode: "class",
    content: ["./index.html", "./src/**/*.{ts,tsx}"],
    theme: {
        extend: {
            fontFamily: {
                sans: ["'IBM Plex Sans'", "sans-serif"],
                mono: ["'IBM Plex Mono'", "monospace"],
            },
            boxShadow: {
                panel: "0 10px 30px rgba(15, 23, 42, 0.08)",
            },
            backgroundImage: {
                "grid-fade": "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.08) 1px, transparent 0)",
            },
        },
    },
    plugins: [],
};
