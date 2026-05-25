// Theme switcher for PlaneSign frontend
// Each theme is a separate CSS file that overrides the base style.css
// To remove a theme: delete its CSS file and remove its entry from THEMES below.

var THEMES = [
    { id: "original", name: "Original", css: null },
    { id: "retro", name: "Retro", css: "style-retro.css" },
    { id: "futuristic", name: "Futuristic", css: "style-futuristic.css" },
    { id: "midnight", name: "Midnight", css: "style-midnight.css" },
    { id: "terminal", name: "Terminal", css: "style-terminal.css" },
    { id: "warm-minimal", name: "Warm Minimal", css: "style-warm-minimal.css" }
];

var THEME_LINK_ID = "theme-override-css";

function apply_theme(themeId) {
    var existing = document.getElementById(THEME_LINK_ID);
    var theme = THEMES.find(function (t) { return t.id === themeId; });
    if (!theme) theme = THEMES[0];

    if (theme.css) {
        if (existing) {
            existing.href = theme.css;
        } else {
            var link = document.createElement("link");
            link.id = THEME_LINK_ID;
            link.rel = "stylesheet";
            link.href = theme.css;
            document.head.appendChild(link);
        }
    } else {
        if (existing) existing.remove();
    }

    try {
        localStorage.setItem("planesign_theme", theme.id);
    } catch (e) { }

    var selector = document.getElementById("theme_selector");
    if (selector) selector.value = theme.id;
}

function init_theme_selector() {
    var saved = null;
    try {
        saved = localStorage.getItem("planesign_theme");
    } catch (e) { }
    if (saved) apply_theme(saved);
}

// Apply saved theme as early as possible
init_theme_selector();
