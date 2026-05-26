// Layout switcher for PlaneSign frontend
// Supports two layouts: Original (index.html) and New Interface (layout-new.html)

function is_new_interface() {
    var path = window.location.pathname.split("/").pop() || "index.html";
    return path === "layout-new.html";
}

function toggle_layout() {
    var goingToNew = !is_new_interface();
    try {
        localStorage.setItem("planesign_layout", goingToNew ? "new" : "original");
    } catch (e) { }
    window.location.href = goingToNew ? "layout-new.html" : "index.html";
}

function init_layout_toggle() {
    var toggle = document.getElementById("layout_toggle");
    if (toggle) toggle.checked = is_new_interface();
}

function check_layout_redirect() {
    var saved = null;
    try {
        saved = localStorage.getItem("planesign_layout");
    } catch (e) { }
    if (saved) {
        var onNew = is_new_interface();
        if ((saved === "new" || saved === "command") && !onNew) {
            window.location.href = "layout-new.html";
        } else if (saved === "original" && onNew) {
            window.location.href = "index.html";
        }
    }
}

// On first load, redirect to saved layout if needed
check_layout_redirect();
