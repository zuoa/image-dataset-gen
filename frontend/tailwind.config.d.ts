declare const _default: {
    darkMode: "class";
    corePlugins: {
        preflight: false;
    };
    content: string[];
    theme: {
        extend: {
            fontFamily: {
                sans: [string, string, string, string, string];
                mono: [string, string];
            };
            boxShadow: {
                panel: string;
            };
            backgroundImage: {
                "grid-fade": string;
            };
        };
    };
    plugins: any[];
};
export default _default;
