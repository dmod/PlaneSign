// Layout switcher for PlaneSign frontend
// Each layout is a completely different HTML+CSS structural refactor.
// To remove a layout: delete its HTML/CSS files and remove its entry from LAYOUTS below.

var LAYOUTS = [
    { id: "original", name: "Original", page: "index.html" },
    { id: "dashboard", name: "Dashboard", page: "layout-dashboard.html" },
    { id: "tabbed", name: "Tabbed", page: "layout-tabbed.html" },
    { id: "cards", name: "Cards", page: "layout-cards.html" },
    { id: "compact", name: "Compact", page: "layout-compact.html" },
    { id: "command", name: "Command Center", page: "layout-command.html" }
];

function get_current_layout_id() {
    var path = window.location.pathname.split("/").pop() || "index.html";
    for (var i = 0; i < LAYOUTS.length; i++) {
        if (LAYOUTS[i].page === path) return LAYOUTS[i].id;
    }
    return "original";
}

function apply_layout(layoutId) {
    var layout = LAYOUTS.find(function (l) { return l.id === layoutId; });
    if (!layout) layout = LAYOUTS[0];

    try {
        localStorage.setItem("planesign_layout", layout.id);
    } catch (e) { }

    // Navigate to the layout page if we're not already on it
    var currentPage = window.location.pathname.split("/").pop() || "index.html";
    if (currentPage !== layout.page) {
        window.location.href = layout.page;
    }
}

function populate_layout_selector() {
    var selector = document.getElementById("layout_selector");
    if (!selector) return;
    var currentId = get_current_layout_id();
    selector.innerHTML = "";
    for (var i = 0; i < LAYOUTS.length; i++) {
        var opt = document.createElement("option");
        opt.value = LAYOUTS[i].id;
        opt.textContent = LAYOUTS[i].name;
        if (LAYOUTS[i].id === currentId) opt.selected = true;
        selector.appendChild(opt);
    }
}

function check_layout_redirect() {
    var saved = null;
    try {
        saved = localStorage.getItem("planesign_layout");
    } catch (e) { }
    if (saved) {
        var current = get_current_layout_id();
        if (saved !== current) {
            apply_layout(saved);
        }
    }
}

// On first load, redirect to saved layout if needed
check_layout_redirect();
