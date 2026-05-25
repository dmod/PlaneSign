// Layout switcher for PlaneSign frontend
// Supports two layouts: Original (index.html) and Command Center (layout-command.html)

function is_command_center() {
    var path = window.location.pathname.split("/").pop() || "index.html";
    return path === "layout-command.html";
}

function toggle_layout() {
    var goingToCommand = !is_command_center();
    try {
        localStorage.setItem("planesign_layout", goingToCommand ? "command" : "original");
    } catch (e) { }
    window.location.href = goingToCommand ? "layout-command.html" : "index.html";
}

function init_layout_toggle() {
    var toggle = document.getElementById("layout_toggle");
    if (toggle) toggle.checked = is_command_center();
}

function check_layout_redirect() {
    var saved = null;
    try {
        saved = localStorage.getItem("planesign_layout");
    } catch (e) { }
    if (saved) {
        var onCommand = is_command_center();
        if (saved === "command" && !onCommand) {
            window.location.href = "layout-command.html";
        } else if (saved === "original" && onCommand) {
            window.location.href = "index.html";
        }
    }
}

// On first load, redirect to saved layout if needed
check_layout_redirect();
