var global_current_mode;
var recordButton, recorder;
var valid_tickers = null;
var valid_resorts = null;
var free_sketch_is_drawing = false;
var free_sketch_is_eraser = false;
var free_sketch_is_stamp = false;
var free_sketch_is_color_picker = false;
var free_sketch_is_paint_bucket = false;
var free_sketch_stamp_category = "snowflake";
var free_sketch_is_fullscreen = false;
var free_sketch_last_pixel = null;
var free_sketch_brush_size = 1;
var free_sketch_brush_shape = "square"; // square, plus, x, circle
var free_sketch_hover_position = null;
var free_sketch_brush_sizes = [1, 2, 3, 4, 5];
var free_sketch_undo_stack = [];
var free_sketch_max_undo = 20;
var free_sketch_recent_colors = [];
var free_sketch_max_recent_colors = 6;

document.addEventListener("fullscreenchange", sync_free_sketch_fullscreen_state);

window.onload = function () {
    update_sign_status();
    update_brightness_slider();
    set_version();
    update_device_info();
    setInterval(update_device_info, 10000);
    get_audio_support();
    setup_free_sketch();

    recordButton = document.getElementById('mic_button');

    document.getElementById("config").onsubmit = function (e) {
        e.preventDefault();
        var confdiv = document.getElementById("config");
        var str = "";
        for (let i = 0; i < confdiv.children.length - 1; i++) {
            str += String(confdiv.children[i].children[0].textContent).slice(0, -2).replaceAll(' ', '_');
            str += "=";
            if (confdiv.children[i].children[1].type == "checkbox") {
                str += String(confdiv.children[i].children[1].checked);
            } else {
                str += String(confdiv.children[i].children[1].value);
            }
            str += "&";
        }
        str = str.slice(0, -1);

        var btn = document.getElementById("submit_config_button");
        var originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.classList.remove("config-save-success");
        btn.classList.remove("config-save-error");

        fetch("api/write_config?" + str)
            .then(async (resp) => {
                let body = null;
                try {
                    body = await resp.json();
                } catch (_) {
                    body = null;
                }

                if (!resp.ok || !body || body.ok !== true) {
                    throw new Error((body && body.error) ? body.error : ("HTTP " + resp.status));
                }

                btn.classList.add("config-save-success");
                btn.innerHTML = originalHtml +
                    " <span class=\"config-save-icon\" aria-hidden=\"true\">" +
                    "<svg viewBox=\"0 0 24 24\" width=\"26\" height=\"26\" focusable=\"false\" role=\"img\" aria-label=\"Saved\">" +
                    "<path d=\"M20 6L9 17l-5-5\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"3\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>" +
                    "</svg></span>";

                window.setTimeout(function () {
                    btn.classList.remove("config-save-success");
                    btn.innerHTML = originalHtml;
                }, 2000);
            })
            .catch((err) => {
                console.error("write_config failed:", err);
                btn.classList.add("config-save-error");
                window.setTimeout(function () {
                    btn.classList.remove("config-save-error");
                }, 2000);
            })
            .finally(() => {
                btn.disabled = false;
            });
    }

    document.getElementById("brightness_slider").oninput = function () {
        call_endpoint("/set_brightness/" + this.value);
    }

    document.getElementById("custom_message").oninput = function () {
        call_endpoint("/set_custom_message/" + encodeURIComponent(this.value));
    }

    document.getElementById("mandelbrot_slider").oninput = function () {
        call_endpoint("/set_mandelbrot_colorscale/" + this.value);
    }

    document.getElementById("pong_player1_slider").oninput = function () {
        call_endpoint("/set_pong_player_1/" + encodeURIComponent(this.value));
    }

    document.getElementById("pong_player2_slider").oninput = function () {
        call_endpoint("/set_pong_player_2/" + encodeURIComponent(this.value));
    }

    document.getElementById("lightning_slider").oninput = function () {
        call_endpoint("/lightning/" + this.value);
    }

    toggle_switch.onchange = function () {
        if (document.getElementById("toggle_switch").checked) {
            call_endpoint('/turn_on')
            call_endpoint("/get_mode", function (current_mode) {
                if (current_mode && current_mode !== "0") {
                    document.getElementById(current_mode).style.backgroundColor = "red";
                    global_current_mode = current_mode;
                }
            });
        } else {
            call_endpoint('/turn_off')
            if (global_current_mode) {
                document.getElementById(global_current_mode).style.backgroundColor = "black"; // Turn off current button
            }
        }
    }

}

function set_version() {
    call_endpoint("/version", function (version) {
        document.getElementById('version').textContent = version;
    });
}

function update_device_info() {
    call_endpoint("/device_info", function (response) {
        var info = JSON.parse(response);

        document.getElementById('di_hostname').textContent = info.hostname || '—';
        document.getElementById('di_ip').textContent = info.ip_address || '—';

        if (info.cpu_temp_c !== null) {
            document.getElementById('di_cpu_temp').textContent = info.cpu_temp_c + '°C';
        } else {
            document.getElementById('di_cpu_temp').textContent = 'N/A';
        }

        if (info.disk_usage_percent !== null) {
            document.getElementById('di_disk').textContent = info.disk_usage_percent + '% (' + info.disk_used_gb + ' / ' + info.disk_total_gb + ' GB)';
        } else {
            document.getElementById('di_disk').textContent = 'N/A';
        }

        if (info.mem_usage_percent !== null) {
            document.getElementById('di_mem').textContent = info.mem_usage_percent + '% (' + Math.round(info.mem_used_mb) + ' / ' + Math.round(info.mem_total_mb) + ' MB)';
        } else {
            document.getElementById('di_mem').textContent = 'N/A';
        }

        document.getElementById('di_uptime').textContent = info.uptime || '—';
    });
}

function start_recording() {
    console.log("Starting recording...")

    var mic = document.getElementById("mic-icon");
    mic.style.fill = "red"

    recorder.start();
}

function stop_recording() {
    console.log("Stopping recording...")

    var mic = document.getElementById("mic-icon");
    mic.style.fill = "#1E2D70"

    // Stopping the recorder will eventually trigger the `dataavailable` event and we can complete the recording process
    recorder.stop();
}

function on_recording_ready(e) {
    fetch('api/play_mic_audio', {
        method: "POST",
        body: e.data
    })
        .then(_ => console.log('Audio blob uploaded'))
        .catch(err => console.error(err));
}

function submit_ticker() {
    call_endpoint("/submit_ticker/" + encodeURIComponent(document.getElementById("ticker").value));
    document.getElementById("ticker").value = "";
}

function call_endpoint(endpoint, callback) {
    var request = new XMLHttpRequest();
    request.onreadystatechange = function () {
        if (this.readyState === 4 && request.status == 200 && callback) {
            callback(request.responseText);
        }
    }
    request.open('GET', "api" + endpoint, true);
    request.send();
}

function post_json_endpoint(endpoint, data, callback) {
    fetch("api" + endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data || {})
    })
        .then(async function (resp) {
            var body = await resp.json().catch(function () { return null; });
            if (!resp.ok || !body || body.ok !== true) {
                throw new Error((body && body.error) ? body.error : ("HTTP " + resp.status));
            }
            if (callback) {
                callback(body);
            }
        })
        .catch(function (err) {
            console.error(endpoint + " failed:", err);
        });
}

function setup_free_sketch() {
    var canvas = document.getElementById("free_sketch_canvas");
    if (!canvas) {
        return;
    }

    var context = canvas.getContext("2d");
    context.imageSmoothingEnabled = false;
    context.fillStyle = "#000000";
    context.fillRect(0, 0, canvas.width, canvas.height);

    var hover_canvas = document.getElementById("free_sketch_hover_canvas");
    if (hover_canvas) {
        var hover_context = hover_canvas.getContext("2d");
        hover_context.imageSmoothingEnabled = false;
        hover_context.clearRect(0, 0, hover_canvas.width, hover_canvas.height);
    }

    canvas.addEventListener("pointerdown", function (event) {
        free_sketch_is_drawing = true;
        free_sketch_last_pixel = null;
        canvas.setPointerCapture(event.pointerId);
        paint_free_sketch_pixel(event);
        update_free_sketch_hover(event);
    });

    canvas.addEventListener("pointermove", function (event) {
        if (free_sketch_is_drawing) {
            paint_free_sketch_pixel(event);
        }
        update_free_sketch_hover(event);
    });

    canvas.addEventListener("pointerup", function (event) {
        stop_free_sketch_drawing();
        update_free_sketch_hover(event);
    });
    canvas.addEventListener("pointercancel", function () {
        stop_free_sketch_drawing();
        clear_free_sketch_hover();
    });
    canvas.addEventListener("pointerleave", function () {
        free_sketch_last_pixel = null;
        clear_free_sketch_hover();
    });

    var color = document.getElementById("free_sketch_color");
    if (color) {
        color.addEventListener("input", function () {
            set_free_sketch_eraser(false);
            set_free_sketch_stamp(false);
            add_color_to_recent(color.value);
        });
    }
    
    // Load recent colors from localStorage
    load_recent_colors();
    
    // Initialize with default state
    update_undo_button_state();
}

function open_free_sketch_modal() {
    var modal = document.getElementById("free_sketch_modal");
    if (!modal) {
        return;
    }
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    update_free_sketch_fullscreen_ui(is_free_sketch_in_browser_fullscreen() || free_sketch_is_fullscreen);
    load_free_sketch_gallery();
}

function close_free_sketch_modal() {
    var modal = document.getElementById("free_sketch_modal");
    if (!modal) {
        return;
    }
    exit_free_sketch_fullscreen();
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    free_sketch_is_drawing = false;
    free_sketch_last_pixel = null;
    clear_free_sketch_hover();
}

function is_free_sketch_in_browser_fullscreen() {
    var fs = document.fullscreenElement;
    var modal = document.getElementById("free_sketch_modal");
    return !!(fs && modal && fs === modal);
}

function update_free_sketch_fullscreen_ui(is_fullscreen) {
    free_sketch_is_fullscreen = is_fullscreen;

    var modal = document.getElementById("free_sketch_modal");
    if (modal) {
        modal.classList.toggle("free_sketch_fullscreen", is_fullscreen);
    }

    var toggle = document.getElementById("free_sketch_fullscreen_toggle");
    if (toggle) {
        toggle.textContent = is_fullscreen ? "Exit Full Screen" : "Full Screen";
        toggle.setAttribute("aria-pressed", is_fullscreen ? "true" : "false");
    }
}

function sync_free_sketch_fullscreen_state() {
    update_free_sketch_fullscreen_ui(is_free_sketch_in_browser_fullscreen());
}

function enter_free_sketch_fullscreen() {
    var modal = document.getElementById("free_sketch_modal");
    if (!modal) {
        return;
    }

    if (!modal.hidden && modal.requestFullscreen) {
        modal.requestFullscreen()
            .then(function () {
                update_free_sketch_fullscreen_ui(true);
            })
            .catch(function () {
                // Fallback to full-width modal if browser fullscreen is blocked.
                update_free_sketch_fullscreen_ui(true);
            });
        return;
    }

    update_free_sketch_fullscreen_ui(true);
}

function exit_free_sketch_fullscreen() {
    if (is_free_sketch_in_browser_fullscreen() && document.exitFullscreen) {
        document.exitFullscreen()
            .then(function () {
                update_free_sketch_fullscreen_ui(false);
            })
            .catch(function () {
                update_free_sketch_fullscreen_ui(false);
            });
        return;
    }

    update_free_sketch_fullscreen_ui(false);
}

function toggle_free_sketch_fullscreen() {
    if (is_free_sketch_in_browser_fullscreen() || free_sketch_is_fullscreen) {
        exit_free_sketch_fullscreen();
    } else {
        enter_free_sketch_fullscreen();
    }
}

function toggle_free_sketch_eraser() {
    set_free_sketch_eraser(!free_sketch_is_eraser);
}

function set_free_sketch_eraser(is_eraser) {
    free_sketch_is_eraser = is_eraser;
    var eraser = document.getElementById("free_sketch_eraser");
    if (eraser) {
        eraser.classList.toggle("active", free_sketch_is_eraser);
    }
    if (is_eraser) {
        set_free_sketch_stamp(false);
        set_free_sketch_color_picker(false);
        set_free_sketch_paint_bucket(false);
    }
}

function toggle_free_sketch_stamp() {
    set_free_sketch_stamp(!free_sketch_is_stamp);
}

function set_free_sketch_stamp(is_stamp) {
    free_sketch_is_stamp = is_stamp;
    var btn = document.getElementById("free_sketch_stamp");
    if (btn) {
        btn.classList.toggle("active", is_stamp);
    }
    if (is_stamp) {
        set_free_sketch_eraser(false);
        set_free_sketch_color_picker(false);
        set_free_sketch_paint_bucket(false);
    }
}

function toggle_free_sketch_color_picker() {
    set_free_sketch_color_picker(!free_sketch_is_color_picker);
}

function set_free_sketch_color_picker(is_picker) {
    free_sketch_is_color_picker = is_picker;
    var btn = document.getElementById("free_sketch_color_picker");
    if (btn) {
        btn.classList.toggle("active", is_picker);
    }
    if (is_picker) {
        set_free_sketch_eraser(false);
        set_free_sketch_stamp(false);
        set_free_sketch_paint_bucket(false);
    }
}

function toggle_free_sketch_paint_bucket() {
    set_free_sketch_paint_bucket(!free_sketch_is_paint_bucket);
}

function set_free_sketch_paint_bucket(is_bucket) {
    free_sketch_is_paint_bucket = is_bucket;
    var btn = document.getElementById("free_sketch_paint_bucket");
    if (btn) {
        btn.classList.toggle("active", is_bucket);
    }
    if (is_bucket) {
        set_free_sketch_eraser(false);
        set_free_sketch_stamp(false);
        set_free_sketch_color_picker(false);
    }
}

function set_free_sketch_brush_size(size) {
    if (free_sketch_brush_sizes.indexOf(size) === -1) {
        return;
    }

    free_sketch_brush_size = size;

    free_sketch_brush_sizes.forEach(function (brush_size) {
        var button = document.getElementById("free_sketch_brush_" + brush_size);
        if (button) {
            var is_active = brush_size === size;
            button.classList.toggle("active", is_active);
            button.setAttribute("aria-pressed", is_active ? "true" : "false");
        }
    });

    if (free_sketch_hover_position) {
        draw_free_sketch_hover(free_sketch_hover_position.x, free_sketch_hover_position.y);
    }
}

function set_free_sketch_brush_shape(shape) {
    free_sketch_brush_shape = shape;
    
    ["square", "plus", "x", "circle"].forEach(function (s) {
        var button = document.getElementById("free_sketch_brush_shape_" + s);
        if (button) {
            var is_active = s === shape;
            button.classList.toggle("active", is_active);
            button.setAttribute("aria-pressed", is_active ? "true" : "false");
        }
    });

    if (free_sketch_hover_position) {
        draw_free_sketch_hover(free_sketch_hover_position.x, free_sketch_hover_position.y);
    }
}

function set_free_sketch_color(colorHex) {
    var colorInput = document.getElementById("free_sketch_color");
    if (colorInput) {
        colorInput.value = colorHex;
    }
    set_free_sketch_eraser(false);
    set_free_sketch_stamp(false);
    add_color_to_recent(colorHex);
}

function clear_free_sketch() {
    save_free_sketch_undo_state();
    var canvas = document.getElementById("free_sketch_canvas");
    if (canvas) {
        var context = canvas.getContext("2d");
        context.fillStyle = "#000000";
        context.fillRect(0, 0, canvas.width, canvas.height);
    }
    post_json_endpoint("/free_sketch/clear", {});
}

function save_free_sketch() {
    post_json_endpoint("/free_sketch/save", {}, function () {
        load_free_sketch_gallery();
    });
}

function load_free_sketch_gallery() {
    var gallery = document.getElementById("free_sketch_gallery");
    if (!gallery) {
        return;
    }

    fetch("api/free_sketch/list")
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
            if (!data || !data.ok) {
                return;
            }

            gallery.innerHTML = "";

            if (data.sketches.length === 0) {
                return;
            }

            data.sketches.forEach(function (sketch) {
                var item = document.createElement("div");
                item.className = "free_sketch_gallery_item";

                var img = document.createElement("img");
                img.src = "api/free_sketch/image/" + sketch.filename;
                img.alt = sketch.filename;
                img.draggable = false;
                img.addEventListener("click", function () {
                    recall_free_sketch(sketch.filename);
                });

                var del_btn = document.createElement("button");
                del_btn.className = "free_sketch_gallery_delete";
                del_btn.textContent = "\u00d7";
                del_btn.title = "Delete sketch";
                del_btn.addEventListener("click", function (e) {
                    e.stopPropagation();
                    delete_free_sketch(sketch.filename);
                });

                item.appendChild(img);
                item.appendChild(del_btn);
                gallery.appendChild(item);
            });
        })
        .catch(function (err) {
            console.error("Failed to load sketch gallery:", err);
        });
}

function recall_free_sketch(filename) {
    post_json_endpoint("/free_sketch/load/" + filename, {}, function () {
        var canvas = document.getElementById("free_sketch_canvas");
        if (!canvas) {
            return;
        }
        var img = new Image();
        img.onload = function () {
            var ctx = canvas.getContext("2d");
            ctx.imageSmoothingEnabled = false;
            ctx.drawImage(img, 0, 0);
        };
        img.src = "api/free_sketch/image/" + filename + "?t=" + Date.now();
    });
}

function delete_free_sketch(filename) {
    post_json_endpoint("/free_sketch/delete/" + filename, {}, function () {
        load_free_sketch_gallery();
    });
}

function stop_free_sketch_drawing() {
    free_sketch_is_drawing = false;
    free_sketch_last_pixel = null;
}

function save_free_sketch_undo_state() {
    var canvas = document.getElementById("free_sketch_canvas");
    if (!canvas) {
        return;
    }
    var ctx = canvas.getContext("2d");
    var imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    free_sketch_undo_stack.push(imageData);
    if (free_sketch_undo_stack.length > free_sketch_max_undo) {
        free_sketch_undo_stack.shift();
    }
    update_undo_button_state();
}

function undo_free_sketch() {
    if (free_sketch_undo_stack.length === 0) {
        return;
    }
    var canvas = document.getElementById("free_sketch_canvas");
    if (!canvas) {
        return;
    }
    var ctx = canvas.getContext("2d");
    var imageData = free_sketch_undo_stack.pop();
    ctx.putImageData(imageData, 0, 0);
    
    // Sync the state back to the server
    sync_free_sketch_to_server(canvas);
    update_undo_button_state();
}

function sync_free_sketch_to_server(canvas) {
    var ctx = canvas.getContext("2d");
    var imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var pixels = [];
    for (var i = 0; i < imageData.data.length; i += 4) {
        pixels.push(imageData.data[i], imageData.data[i + 1], imageData.data[i + 2]);
    }
    post_json_endpoint("/free_sketch/sync", { pixels: pixels });
}

function update_undo_button_state() {
    var btn = document.getElementById("free_sketch_undo");
    if (btn) {
        btn.disabled = free_sketch_undo_stack.length === 0;
    }
}

function add_color_to_recent(colorHex) {
    // Remove if already exists
    var index = free_sketch_recent_colors.indexOf(colorHex);
    if (index !== -1) {
        free_sketch_recent_colors.splice(index, 1);
    }
    // Add to beginning
    free_sketch_recent_colors.unshift(colorHex);
    // Keep only max
    if (free_sketch_recent_colors.length > free_sketch_max_recent_colors) {
        free_sketch_recent_colors.pop();
    }
    // Save to localStorage
    localStorage.setItem("free_sketch_recent_colors", JSON.stringify(free_sketch_recent_colors));
    update_recent_colors_ui();
}

function load_recent_colors() {
    var stored = localStorage.getItem("free_sketch_recent_colors");
    if (stored) {
        try {
            free_sketch_recent_colors = JSON.parse(stored);
        } catch (e) {
            free_sketch_recent_colors = [];
        }
    }
    update_recent_colors_ui();
}

function update_recent_colors_ui() {
    var container = document.getElementById("free_sketch_recent_colors");
    if (!container) {
        return;
    }
    container.innerHTML = "";
    free_sketch_recent_colors.forEach(function (color) {
        var btn = document.createElement("button");
        btn.className = "free_sketch_color_swatch";
        btn.style.backgroundColor = color;
        btn.title = color;
        btn.setAttribute("aria-label", "Select color " + color);
        btn.onclick = function () {
            set_free_sketch_color(color);
        };
        container.appendChild(btn);
    });
}

function get_free_sketch_color() {
    if (free_sketch_is_eraser) {
        return { r: 0, g: 0, b: 0, hex: "#000000" };
    }

    var color = document.getElementById("free_sketch_color").value;
    return {
        r: parseInt(color.substring(1, 3), 16),
        g: parseInt(color.substring(3, 5), 16),
        b: parseInt(color.substring(5, 7), 16),
        hex: color
    };
}

function get_free_sketch_canvas_pixel(event) {
    var canvas = document.getElementById("free_sketch_canvas");
    if (!canvas) {
        return null;
    }

    var rect = canvas.getBoundingClientRect();
    var x = Math.floor((event.clientX - rect.left) * canvas.width / rect.width);
    var y = Math.floor((event.clientY - rect.top) * canvas.height / rect.height);

    if (x < 0 || x >= canvas.width || y < 0 || y >= canvas.height) {
        return null;
    }

    return { x: x, y: y };
}

function get_free_sketch_brush_bounds(x, y) {
    return {
        x: x - Math.floor(free_sketch_brush_size / 2),
        y: y - Math.floor(free_sketch_brush_size / 2),
        size: free_sketch_brush_size
    };
}

function clear_free_sketch_hover() {
    var hover_canvas = document.getElementById("free_sketch_hover_canvas");
    if (!hover_canvas) {
        return;
    }

    var context = hover_canvas.getContext("2d");
    context.clearRect(0, 0, hover_canvas.width, hover_canvas.height);
    free_sketch_hover_position = null;
}

function draw_free_sketch_hover(x, y) {
    var hover_canvas = document.getElementById("free_sketch_hover_canvas");
    if (!hover_canvas) {
        return;
    }

    var context = hover_canvas.getContext("2d");
    context.clearRect(0, 0, hover_canvas.width, hover_canvas.height);

    if (free_sketch_is_color_picker) {
        // Show eyedropper icon
        context.font = "12px sans-serif";
        context.fillStyle = "rgba(255, 255, 255, 0.9)";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText("💧", x, y);
    } else if (free_sketch_is_paint_bucket) {
        // Show paint bucket icon
        context.font = "12px sans-serif";
        context.fillStyle = "rgba(255, 255, 255, 0.9)";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText("🪣", x, y);
    } else if (free_sketch_is_stamp) {
        context.font = "10px sans-serif";
        context.fillStyle = "rgba(255, 255, 255, 0.7)";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText("\u2744", x, y);
    } else {
        // Show brush preview
        context.fillStyle = "rgba(190, 190, 190, 0.55)";
        var brushPixels = get_brush_shape_pixels(x, y, free_sketch_brush_size, free_sketch_brush_shape);
        brushPixels.forEach(function (p) {
            if (p.x >= 0 && p.x < hover_canvas.width && p.y >= 0 && p.y < hover_canvas.height) {
                context.fillRect(p.x, p.y, 1, 1);
            }
        });
    }
    free_sketch_hover_position = { x: x, y: y };
}

function update_free_sketch_hover(event) {
    var pixel = get_free_sketch_canvas_pixel(event);
    if (!pixel) {
        clear_free_sketch_hover();
        return;
    }

    draw_free_sketch_hover(pixel.x, pixel.y);
}

function place_free_sketch_stamp(canvas, x, y) {
    post_json_endpoint("/free_sketch/stamp", {
        x: x,
        y: y,
        category: free_sketch_stamp_category
    }, function (result) {
        if (!result || !result.ok) {
            return;
        }
        var img = new Image();
        img.onload = function () {
            var ctx = canvas.getContext("2d");
            ctx.imageSmoothingEnabled = false;
            var dx = x - Math.floor(img.width / 2);
            var dy = y - Math.floor(img.height / 2);

            if (result.tint) {
                // Draw sprite to an offscreen canvas and tint white pixels
                var off = document.createElement("canvas");
                off.width = img.width;
                off.height = img.height;
                var oc = off.getContext("2d");
                oc.drawImage(img, 0, 0);
                var id = oc.getImageData(0, 0, off.width, off.height);
                var d = id.data;
                for (var i = 0; i < d.length; i += 4) {
                    if (d[i] === 255 && d[i + 1] === 255 && d[i + 2] === 255 && d[i + 3] === 255) {
                        d[i] = result.tint[0];
                        d[i + 1] = result.tint[1];
                        d[i + 2] = result.tint[2];
                    }
                }
                oc.putImageData(id, 0, 0);
                ctx.drawImage(off, dx, dy);
            } else {
                ctx.drawImage(img, dx, dy);
            }
        };
        img.src = "api/free_sketch/stamp_image/" + result.stamp_id + "?t=" + Date.now();
    });
}

function paint_free_sketch_pixel(event) {
    event.preventDefault();

    var canvas = document.getElementById("free_sketch_canvas");
    var pixel = get_free_sketch_canvas_pixel(event);
    if (!canvas || !pixel) {
        return;
    }

    var x = pixel.x;
    var y = pixel.y;

    // Handle color picker tool
    if (free_sketch_is_color_picker) {
        if (!free_sketch_last_pixel) {
            pick_color_from_canvas(event);
        }
        free_sketch_last_pixel = { x: x, y: y };
        return;
    }

    // Handle paint bucket tool
    if (free_sketch_is_paint_bucket) {
        if (!free_sketch_last_pixel) {
            paint_bucket_fill(event);
        }
        free_sketch_last_pixel = { x: x, y: y };
        return;
    }

    // Handle stamp tool
    if (free_sketch_is_stamp) {
        if (!free_sketch_last_pixel) {
            place_free_sketch_stamp(canvas, x, y);
            save_free_sketch_undo_state();
        }
        free_sketch_last_pixel = { x: x, y: y };
        return;
    }

    // Save undo state before first stroke
    if (!free_sketch_last_pixel) {
        save_free_sketch_undo_state();
    }

    var selected_color = get_free_sketch_color();
    var context = canvas.getContext("2d");
    context.fillStyle = selected_color.hex;

    if (free_sketch_last_pixel && (free_sketch_last_pixel.x !== x || free_sketch_last_pixel.y !== y)) {
        // Interpolate a line from the last position to the current one
        var points = bresenham_line(free_sketch_last_pixel.x, free_sketch_last_pixel.y, x, y);
        for (var i = 0; i < points.length; i++) {
            var brushPixels = get_brush_shape_pixels(points[i].x, points[i].y, free_sketch_brush_size, free_sketch_brush_shape);
            brushPixels.forEach(function (p) {
                if (p.x >= 0 && p.x < canvas.width && p.y >= 0 && p.y < canvas.height) {
                    context.fillRect(p.x, p.y, 1, 1);
                }
            });
        }

        post_json_endpoint("/free_sketch/line", {
            x0: free_sketch_last_pixel.x,
            y0: free_sketch_last_pixel.y,
            x1: x,
            y1: y,
            brush_size: free_sketch_brush_size,
            brush_shape: free_sketch_brush_shape,
            r: selected_color.r,
            g: selected_color.g,
            b: selected_color.b
        });
    } else if (!free_sketch_last_pixel || (free_sketch_last_pixel.x !== x || free_sketch_last_pixel.y !== y)) {
        // First point or same check - just paint a single stamp
        var brushPixels = get_brush_shape_pixels(x, y, free_sketch_brush_size, free_sketch_brush_shape);
        brushPixels.forEach(function (p) {
            if (p.x >= 0 && p.x < canvas.width && p.y >= 0 && p.y < canvas.height) {
                context.fillRect(p.x, p.y, 1, 1);
            }
        });

        post_json_endpoint("/free_sketch/pixel", {
            x: x,
            y: y,
            brush_size: free_sketch_brush_size,
            brush_shape: free_sketch_brush_shape,
            r: selected_color.r,
            g: selected_color.g,
            b: selected_color.b
        });
    }

    free_sketch_last_pixel = { x: x, y: y };
}

function bresenham_line(x0, y0, x1, y1) {
    var points = [];
    var dx = Math.abs(x1 - x0);
    var dy = -Math.abs(y1 - y0);
    var sx = x0 < x1 ? 1 : -1;
    var sy = y0 < y1 ? 1 : -1;
    var err = dx + dy;
    while (true) {
        points.push({ x: x0, y: y0 });
        if (x0 === x1 && y0 === y1) break;
        var e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
    return points;
}

function get_brush_shape_pixels(cx, cy, size, shape) {
    var pixels = [];
    var half = Math.floor(size / 2);
    
    if (shape === "square") {
        for (var dy = -half; dy <= half && dy < size - half; dy++) {
            for (var dx = -half; dx <= half && dx < size - half; dx++) {
                pixels.push({ x: cx + dx, y: cy + dy });
            }
        }
    } else if (shape === "plus") {
        // Vertical and horizontal lines
        for (var d = -half; d <= half && d < size - half; d++) {
            pixels.push({ x: cx, y: cy + d }); // vertical
            pixels.push({ x: cx + d, y: cy }); // horizontal
        }
    } else if (shape === "x") {
        // Diagonal lines
        for (var d = -half; d <= half && d < size - half; d++) {
            pixels.push({ x: cx + d, y: cy + d }); // diagonal \
            pixels.push({ x: cx + d, y: cy - d }); // diagonal /
        }
    } else if (shape === "circle") {
        // Circle approximation using distance formula
        var radiusSquared = (size / 2) * (size / 2);
        for (var dy = -half; dy <= half && dy < size - half; dy++) {
            for (var dx = -half; dx <= half && dx < size - half; dx++) {
                var distSquared = dx * dx + dy * dy;
                if (distSquared <= radiusSquared) {
                    pixels.push({ x: cx + dx, y: cy + dy });
                }
            }
        }
    }
    
    // Remove duplicates
    var seen = {};
    return pixels.filter(function (p) {
        var key = p.x + "," + p.y;
        if (seen[key]) return false;
        seen[key] = true;
        return true;
    });
}

function pick_color_from_canvas(event) {
    var canvas = document.getElementById("free_sketch_canvas");
    var pixel = get_free_sketch_canvas_pixel(event);
    if (!canvas || !pixel) {
        return;
    }
    
    var ctx = canvas.getContext("2d");
    var imageData = ctx.getImageData(pixel.x, pixel.y, 1, 1);
    var data = imageData.data;
    var r = data[0];
    var g = data[1];
    var b = data[2];
    var hex = "#" + 
        ("0" + r.toString(16)).slice(-2) +
        ("0" + g.toString(16)).slice(-2) +
        ("0" + b.toString(16)).slice(-2);
    
    set_free_sketch_color(hex);
    set_free_sketch_color_picker(false);
}

function paint_bucket_fill(event) {
    var canvas = document.getElementById("free_sketch_canvas");
    var pixel = get_free_sketch_canvas_pixel(event);
    if (!canvas || !pixel) {
        return;
    }
    
    save_free_sketch_undo_state();
    
    var ctx = canvas.getContext("2d");
    var imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var targetPixel = (pixel.y * canvas.width + pixel.x) * 4;
    var targetR = imageData.data[targetPixel];
    var targetG = imageData.data[targetPixel + 1];
    var targetB = imageData.data[targetPixel + 2];
    
    var selected_color = get_free_sketch_color();
    var fillR = selected_color.r;
    var fillG = selected_color.g;
    var fillB = selected_color.b;
    
    // Don't fill if target color is the same as fill color
    if (targetR === fillR && targetG === fillG && targetB === fillB) {
        return;
    }
    
    // Flood fill algorithm
    var stack = [{ x: pixel.x, y: pixel.y }];
    var filled = {};
    
    while (stack.length > 0) {
        var p = stack.pop();
        var key = p.x + "," + p.y;
        
        if (p.x < 0 || p.x >= canvas.width || p.y < 0 || p.y >= canvas.height) {
            continue;
        }
        
        if (filled[key]) {
            continue;
        }
        
        var index = (p.y * canvas.width + p.x) * 4;
        if (imageData.data[index] !== targetR ||
            imageData.data[index + 1] !== targetG ||
            imageData.data[index + 2] !== targetB) {
            continue;
        }
        
        imageData.data[index] = fillR;
        imageData.data[index + 1] = fillG;
        imageData.data[index + 2] = fillB;
        filled[key] = true;
        
        stack.push({ x: p.x + 1, y: p.y });
        stack.push({ x: p.x - 1, y: p.y });
        stack.push({ x: p.x, y: p.y + 1 });
        stack.push({ x: p.x, y: p.y - 1 });
    }
    
    ctx.putImageData(imageData, 0, 0);
    sync_free_sketch_to_server(canvas);
    set_free_sketch_paint_bucket(false);
}

function close_all_flight_lists() {
    var allitems = document.getElementsByClassName("autocomplete-flight-items");

    for (let x of allitems) {
        document.getElementById("track-a-flight_div").removeChild(x)
    }
}

function get_possible_autofill_flights(query_string) {
    call_endpoint("/get_possible_flights/" + query_string, function (value) {
        live_flights = JSON.parse(value)['results'].filter((flight) => { return flight['type'] == 'live' })

        close_all_flight_lists();

        a = document.createElement("div");
        a.setAttribute("class", "autocomplete-flight-items");
        document.getElementById("track-a-flight_div").appendChild(a);

        live_flights.forEach(flight => {
            b = document.createElement("div");

            let start = flight['label'].toLowerCase().search(query_string.toLowerCase())

            b.innerHTML += flight['label'].substring(0, start);
            b.innerHTML += "<strong>" + flight['label'].substr(start, query_string.length) + "</strong>";
            b.innerHTML += flight['label'].substr(start + query_string.length);
            b.innerHTML += "<br>" + flight['detail']['route']

            b.addEventListener("click", function (e) {
                close_all_flight_lists();
                document.getElementById("track-a-flight_flight-num-input").value = flight['detail']['callsign']
                call_endpoint('/set_track_a_flight/' + flight['id'])
            });
            a.appendChild(b);
        });
    });
}

function clear_user_resorts_list() {
    user_resort_list = document.getElementById('user_resort_list');
    while (user_resort_list.firstChild) {
        user_resort_list.removeChild(user_resort_list.lastChild);
    }
}

function get_saved_resorts() {
    call_endpoint("/get_saved_resorts", function (value) {
        saved_resorts = value.toString().split("\n");

        tracked_resorts_div = document.getElementById('tracked_resorts');
        user_resort_list = document.getElementById('user_resort_list');
        clear_user_resorts_list();
        if (saved_resorts != "" && saved_resorts.length > 0) {

            if (valid_resorts === null) {
                // Should really call this asyncronously and wait for
                // the response to continue...
                get_resorts()
            }

            saved_resorts.forEach(uuid => {

                // Lookup data for this uuid
                found_res = Object.values(valid_resorts['resorts']).filter((entry) => entry.uuid == uuid);

                if (found_res.length == 0) {
                    console.log("UUID: " + uuid + " not found in valid resorts data")
                    return;
                }
                resort = found_res[0]

                elem = document.createElement("div");

                inner = document.createElement("div");

                inner.innerHTML += resort['title'];
                inner.innerHTML += "<br>";
                inner.innerHTML += resort['region_en'] + " (" + resort['country_code'] + ")";
                inner.setAttribute("class", "user-resort-name")

                closebutton = document.createElement("div");
                closebutton.setAttribute("class", "close");
                closebutton.setAttribute("href", "")
                closebutton.addEventListener("click", function (e) {
                    call_endpoint('/delete_saved_resort/' + this.parentElement.getAttribute("uuid"), function () {
                        setTimeout(get_saved_resorts, 500);
                    })
                });

                elem.setAttribute("class", "user-resort-item");
                elem.setAttribute("uuid", uuid)
                elem.appendChild(inner);
                elem.appendChild(closebutton);

                user_resort_list.appendChild(elem);
            });
            tracked_resorts_div.hidden = false
        }
        else {
            tracked_resorts_div.hidden = true
        }
    });
}

function save_current_resort() {
    call_endpoint("/save_current_resort", function () {
        setTimeout(get_saved_resorts, 500);
    });
}

function close_resort_opts_list() {
    var allitems = document.getElementsByClassName("autocomplete-resort-items");

    for (let x of allitems) {
        document.getElementById("resort_search").removeChild(x);
    }
}

function get_resorts() {
    // Need to call this endpoint even if we already have
    // the valid_resorts already because the sign may have
    // been reset and this call is the ONLY trigger for the
    // sign to load its own copy of the data.
    call_endpoint("/get_resort_opts", function (value) {
        valid_resorts = JSON.parse(value)
        document.getElementById('resort_search').hidden = false
    });
}

function get_possible_autofill_resorts(query_string) {

    if (valid_resorts === null) {
        // Might be nice to call get_resorts() here
        // but need to do some kind of async nonsense
        // to make it work
        return;
    }

    if (query_string == "") {
        close_resort_opts_list();
        return;
    }

    query_string = query_string.toLowerCase();
    lq = query_string.length

    function score(word) {

        if (word == undefined || word == "") {
            return 0.0;
        }

        word = word.toLowerCase()

        if (!word.includes(query_string)) {
            return 0.0;
        }

        lm = word.length;

        s = lq / lm;

        if (lm > 2 * lq + 1) {
            s *= 0.75
        }

        if (word.startsWith(query_string)) {
            s *= 1.5;
        }

        return s;
    }

    resorts = Object.values(valid_resorts['resorts']);
    alts = Object.values(valid_resorts["alt_names"]);
    misses = Object.values(valid_resorts["misspellings"]);

    function getScore(entry) {
        alt_score = 0.0;
        if (alts != undefined) {
            found_alt = alts.find((alt) => { return alt.uuid == entry.uuid; })
            if (found_alt != undefined) {
                alt_score = Math.max(...found_alt?.data.map((d) => { return score(d); }));
            }
        }
        miss_score = 0.0;
        if (misses != undefined) {
            found_miss = misses.find((miss) => { return miss.uuid == entry.uuid; })
            if (found_miss != undefined) {
                miss_score = Math.max(...found_miss?.data.map((d) => { return score(d); }));
            }
        }
        return Math.max(score(entry.title), score(entry.title_short), score(entry.title_original), 0.75 * alt_score, 0.75 * miss_score);
    }

    found_resorts = resorts.filter((entry) =>
        entry.title.toLowerCase().includes(query_string) ||
        entry.title_short.toLowerCase().includes(query_string) ||
        entry.title_original.toLowerCase().includes(query_string) ||
        alts?.find((alt) => { return alt.uuid == entry.uuid })?.data.filter((d) => { return d.toLowerCase().includes(query_string) }).length > 0 ||
        misses?.find((alt) => { return alt.uuid == entry.uuid })?.data.filter((d) => { return d.toLowerCase().includes(query_string) }).length > 0
    );

    final_entries = found_resorts.map((entry) => entry = {
        uuid: entry.uuid,
        title: entry.title,
        title_short: entry.title_short,
        title_original: entry.title_original,
        region_en: entry.region_en,
        country_code: entry.country_code,
        score: getScore(entry)
    });

    function order_results(a, b) {
        a_title = a.title.toLowerCase();
        a_short = a.title_short.toLowerCase();
        a_orig = a.title_original.toLowerCase();
        b_title = b.title.toLowerCase();
        b_short = b.title_short.toLowerCase();
        b_orig = b.title_original.toLowerCase();

        a_startswith = a_title.startsWith(query_string) || a_short.startsWith(query_string) || a_orig.startsWith(query_string);
        b_startswith = b_title.startsWith(query_string) || b_short.startsWith(query_string) || b_orig.startsWith(query_string);
        if (a_startswith && !b_startswith) {
            return -1.0;
        }
        else if (!a_startswith && b_startswith) {
            return 1.0;
        }
        else {
            // Sort by higher score
            return b.score - a.score
        }
    }

    final_entries.sort(order_results);

    // Only display best 25 results
    final_entries.length = 25;

    close_resort_opts_list();

    a = document.createElement("div");
    a.setAttribute("class", "autocomplete-resort-items");
    document.getElementById("resort_search").appendChild(a);

    final_entries.forEach(resort => {
        b = document.createElement("div");
        b.innerHTML += resort['title'];
        b.innerHTML += "<br>";
        b.innerHTML += resort['region_en'] + " (" + resort['country_code'] + ")";

        b.addEventListener("click", function (e) {
            close_resort_opts_list();
            document.getElementById("resort_searchbar").value = ""
            call_endpoint('/display_resort/' + resort['uuid'])

            // "Display resort" sets to static display mode "0"
            // so unselect both of the radio button modes now.
            document.getElementById("Detail").checked = false;
            document.getElementById("Overview").checked = false;
        });

        a.appendChild(b);
    });
}

function close_all_ticker_lists() {
    var allitems = document.getElementsByClassName("autocomplete-ticker-items");

    for (let x of allitems) {
        document.getElementById("finance_div").removeChild(x)
    }
}

function get_tickers() {
    if (valid_tickers === null) {
        call_endpoint("/get_ticker_opts", function (value) {
            valid_tickers = JSON.parse(value)
            document.getElementById('finance_div').hidden = false
        });
    }
    else {
        document.getElementById('finance_div').hidden = false
    }
}

function get_possible_autofill_tickers(query_string) {

    if (valid_tickers === null) {
        // Might be nice to call get_tickers() here
        // but need to do some kind of async nonsense
        // to make it work
        return;
    }

    if (query_string == "") {
        close_all_ticker_lists();
        return;
    }

    query_string = query_string.toUpperCase();
    ls = query_string.length

    bn_regex = new RegExp(`^\\w*${RegExp.escape(query_string)}\\w*\/USDT$`, "i");
    cb_regex = new RegExp(`^COINBASE:\\w*${RegExp.escape(query_string)}\\w*-USD$`, "i");
    us_regex = us_regex = new RegExp(`${RegExp.escape(query_string)}`, "i");

    found_bn = Object.values(valid_tickers['bn']).filter((entry) => bn_regex.test(entry.displaySymbol));
    found_cb = Object.values(valid_tickers['cb']).filter((entry) => cb_regex.test(entry.symbol));
    found_us = Object.values(valid_tickers['us']).filter((entry) => entry.symbol.startsWith(query_string) || us_regex.test(entry.description));

    // Binance ticker similarity score
    function bn_similarity(entry) {

        // Remove "/USDT"
        lds = entry["displaySymbol"].slice(0, -5).length
        score = ls / lds
        if (lds > 2 * ls + 1) {
            score *= 0.75
        }
        if (entry["displaySymbol"].startsWith(query_string)) {
            score *= 1.5
        }

        return score
    }

    // Coinbase ticker similarity score
    function cb_similarity(entry) {

        // Remove "-USD"
        lds = entry["displaySymbol"].slice(0, -4).length
        score = ls / lds
        if (lds > 2 * ls + 1) {
            score *= 0.75
        }
        if (entry["displaySymbol"].startsWith(query_string)) {
            score *= 1.5
        }

        return score
    }

    repl = new RegExp("(?:\\s+(?:CO|CORP|LTD|LLC|PLC|INC|GRO|OPTION|ETF|EQ|INVT|TRUST))+(?:\\s+\\w{1,2})*$|[^a-zA-Z0-9]", "ig");

    // US Exchange ticker similarity score
    function us_similarity(entry) {

        if (entry["symbol"].startsWith(query_string)) {
            le = entry["symbol"].length
            symscore = ls / le
            if (le > 2 * ls + 1) {
                symscore *= 0.75
            }
            symscore *= 1.5
        }
        else {
            symscore = 0.0
        }

        if (us_regex.test(entry["description"])) {
            strippeddesc = entry["description"].replaceAll(repl, "")
            lds = strippeddesc.length
            ld = entry["description"].length
            descscore = ls / lds
            if (descscore > 1.0) {
                descscore = 1.0 - 0.02 * (ld - lds)
            }
            if (ls <= 3) {
                descscore *= ls / 4;
            }
            else if (lds > 3 * ls + 2) {
                descscore *= 0.75
            }
            if (entry["description"].startsWith(query_string)) {
                descscore *= 1.5
            }
        }
        else {
            descscore = 0.0
        }

        return Math.max(symscore, descscore)
    }

    function order_results(a, b) {
        diff = b["score"] - a["score"];
        if (diff != 0.0) {
            return diff;
        }
        else {
            // Tiebreak with matching start of ticker
            sa = a["displaySymbol"];
            sb = b["displaySymbol"];

            sa_start = sa.startsWith(query_string);
            sb_start = sb.startsWith(query_string);

            if (sa_start && !sb_start) {
                return -1.0;
            }
            else if (!sa_start && sb_start) {
                return 1.0;
            }
            else {
                // Tiebreak with shorter ticker length
                if (sa.length != sb.length) {
                    return sa.length - sb.length
                }
                else {
                    return 0.0;
                }
            }
        }
    }

    // Score search results
    found_bn.map((entry) => entry.score = bn_similarity(entry));
    found_cb.map((entry) => entry.score = cb_similarity(entry));
    found_us.map((entry) => entry.score = us_similarity(entry));

    found_tickers = found_us.concat(found_bn, found_cb);

    found_tickers.sort(order_results);

    // Only display best 25 results
    found_tickers.length = 25;

    close_all_ticker_lists();

    a = document.createElement("div");
    a.setAttribute("class", "autocomplete-ticker-items");
    document.getElementById("finance_div").appendChild(a);

    found_tickers.forEach(ticker => {
        b = document.createElement("div");

        if (ticker['description'].toUpperCase().startsWith("COINBASE ")) {
            start_desc = ticker['description'].slice(9).toUpperCase().search(query_string);
            if (start_desc > -1) {
                start_desc += 9;
            }
        } else if (ticker['description'].toUpperCase().startsWith("BINANCE ")) {
            start_desc = ticker['description'].slice(8).toUpperCase().search(query_string);
            if (start_desc > -1) {
                start_desc += 8;
            }
        }
        else {
            start_desc = ticker['description'].toUpperCase().search(query_string)
        }

        if (start_desc > -1) {
            b.innerHTML += ticker['description'].toUpperCase().substring(0, start_desc);
            b.innerHTML += "<strong>" + ticker['description'].toUpperCase().substr(start_desc, ls) + "</strong>";
            b.innerHTML += ticker['description'].toUpperCase().substr(start_desc + ls);
        }
        else {
            b.innerHTML += ticker['description'].toUpperCase();
        }

        b.innerHTML += "<br>";

        if (ticker['symbol'].toUpperCase().startsWith("COINBASE:")) {
            start_symb = ticker['symbol'].slice(9).toUpperCase().search(query_string);
            if (start_symb > -1) {
                start_symb += 9;
            }
        } else if (ticker['symbol'].toUpperCase().startsWith("BINANCE:")) {
            start_symb = ticker['symbol'].slice(8).toUpperCase().search(query_string);
            if (start_symb > -1) {
                start_symb += 8;
            }
        }
        else {
            start_symb = ticker['symbol'].toUpperCase().search(query_string)
        }

        if (start_symb > -1) {
            b.innerHTML += ticker['symbol'].substring(0, start_symb);
            b.innerHTML += "<strong>" + ticker['symbol'].substr(start_symb, ls) + "</strong>";
            b.innerHTML += ticker['symbol'].substr(start_symb + ls);
        }
        else {
            b.innerHTML += ticker['symbol'];
        }

        b.addEventListener("click", function (e) {
            close_all_ticker_lists();
            document.getElementById("ticker").value = ""//  ticker['symbol']
            call_endpoint('/submit_ticker/' + ticker['symbol'])
        });

        classname = "";
        if (ticker['symbol'].startsWith("COINBASE:")) {
            classname = " coinbase-ticker-item";
        } else if (ticker['symbol'].startsWith("BINANCE:")) {
            classname = " binance-ticker-item";
        }
        b.setAttribute("class", classname);
        a.appendChild(b);
    });
}

function update_brightness_slider() {
    call_endpoint("/get_brightness", function (value) {
        document.getElementById("brightness_slider").value = value;
    });
}

function play_selected_sound() {
    e = document.getElementById("sound-list");
    sound_id = e.options[e.selectedIndex].value;
    if (sound_id) {
        console.log("Sending request to play: " + sound_id)
        call_endpoint("/play_a_sound/" + sound_id);
    }
}

function play_a_sound(sound_id) {
    console.log("Sending request to play: " + sound_id)
    call_endpoint("/play_a_sound/" + sound_id);
}

function get_audio_support() {
    call_endpoint("/is_audio_supported", function (value) {
        console.log("Is audio supported? " + value);
        audio_supported = value;
        document.getElementById("mic_button").hidden = !value;
        document.getElementById("sounds_div").hidden = !value;
        if (value) {
            populate_sound_dropdown();

            if (window.location.protocol === 'http:') {
                // Mic recording requires HTTPS — replace mic button with link
                var micBtn = document.getElementById("mic_button");

                var wrapper = document.createElement("div");
                wrapper.className = "box4";
                wrapper.style.display = "flex";
                wrapper.style.justifyContent = "center";
                wrapper.style.alignItems = "center";

                var enableBtn = document.createElement("a");
                enableBtn.href = "https://" + window.location.host + window.location.pathname + window.location.search + window.location.hash;
                enableBtn.textContent = "Enable Mic";
                enableBtn.style.display = "flex";
                enableBtn.style.justifyContent = "center";
                enableBtn.style.alignItems = "center";
                enableBtn.style.width = "120px";
                enableBtn.style.height = "120px";
                enableBtn.style.borderRadius = "50%";
                enableBtn.style.backgroundColor = "#444";
                enableBtn.style.color = "#ccc";
                enableBtn.style.textDecoration = "none";
                enableBtn.style.fontSize = "14px";
                enableBtn.style.textAlign = "center";

                wrapper.appendChild(enableBtn);
                micBtn.parentNode.replaceChild(wrapper, micBtn);
                return;
            }

            try {
                // get audio stream from user's mic
                navigator.mediaDevices.getUserMedia({
                    audio: true
                })
                    .then(function (stream) {
                        recordButton.disabled = false;
                        recordButton.addEventListener('mousedown', start_recording);
                        recordButton.addEventListener('mouseup', stop_recording);
                        recordButton.addEventListener('touchstart', start_recording);
                        recordButton.addEventListener('touchend', stop_recording);
                        recorder = new MediaRecorder(stream);

                        // listen to dataavailable, which gets triggered whenever we have
                        // an audio blob available
                        recorder.addEventListener('dataavailable', on_recording_ready);
                    });
            } catch (e) {
                console.error(e)
            }
        }
    });
}

function populate_sound_dropdown() {
    var e = document.getElementById("sound-list");
    call_endpoint("/get_sounds", function (value) {
        console.log("Found files: " + value);

        var jsn = JSON.parse(value);

        for (let i = 0; i < jsn.length; i++) {
            var option = document.createElement("option");
            var fname = jsn[i].split("/");
            fname = fname[fname.length - 1];
            option.value = fname;
            fname = fname.split(".");
            fname = fname[0];
            option.text = fname;
            e.add(option);
        }
    });
}

function set_mode(mode) {
    if (global_current_mode) {
        document.getElementById(global_current_mode).style.backgroundColor = "black"; // Turn off current button
    }
    document.getElementById(mode).style.backgroundColor = "red"; // Turn on new button
    global_current_mode = mode;

    if (mode !== 'CUSTOM_MESSAGE') {
        document.getElementById('custom_message_div').hidden = true;
    }
    if (mode !== 'CGOL') {
        document.getElementById('cgol_div').hidden = true;
    }
    if (mode !== 'PONG') {
        document.getElementById('pong_div').hidden = true;
    }
    if (mode !== 'SNOW') {
        document.getElementById('snow_div').hidden = true;
    }
    if (mode !== 'FINANCE') {
        document.getElementById('finance_div').hidden = true;
    }
    if (mode !== 'LIGHTNING') {
        document.getElementById('lightning_div').hidden = true;
    }
    if (mode !== 'SATELLITE') {
        document.getElementById('satellite_div').hidden = true;
    }
    if (mode !== 'COUNTDOWN') {
        document.getElementById('countdown_div').hidden = true;
    }
    if (mode !== 'MANDELBROT') {
        document.getElementById('mandelbrot_div').hidden = true;
    }
    if (mode !== 'TRACK_A_FLIGHT') {
        document.getElementById('track-a-flight_div').hidden = true;
    }
    if (mode !== 'FREE_SKETCH') {
        close_free_sketch_modal();
    }
    if (mode == 'CGOL') {
        var ele = document.getElementsByName('cgolstyle');
        for (i = 0; i < ele.length; i++) {
            if (ele[i].checked)
                break;
        }
        call_endpoint("/set_mode/" + mode + "?style=" + ele[i].value);
    } else {
        call_endpoint("/set_mode/" + mode);
    }

    if (mode == 'FREE_SKETCH') {
        open_free_sketch_modal();
    }

}

function set_lightning_mode(mode) {
    call_endpoint("/lightning_mode/" + mode);
}

function set_snow_mode(mode) {
    call_endpoint("/snow_mode/" + mode);

    detail = document.getElementById("Detail");
    overview = document.getElementById("Overview");
    if (mode == detail.value) {
        detail.checked = true;
        overview.checked = false;
    }
    else if (mode == overview.value) {
        detail.checked = false;
        overview.checked = true;
    }
    else {
        detail.checked = false;
        overview.checked = false;
    }
}

function set_mandelbrot_color(mode) {
    call_endpoint("/mandelbrot_color/" + mode);
}

function set_satellite_mode(mode) {
    call_endpoint("/satellite_mode/" + mode);
}

function set_color_mode(color) {
    call_endpoint("/set_color_mode/" + color);
}

function set_countdown(datetime, msgstr) {
    call_endpoint("/set_countdown/" + datetime + "/" + msgstr);
}

function show_options() {
    read_conf()
    document.getElementById("optionsSidebar").style.display = "block";
}

function hide_options() {
    document.getElementById("optionsSidebar").style.display = "none";
}

function fill_location_from_browser() {
    var btn = document.getElementById("geolocate_button");
    if (!navigator.geolocation) {
        console.warn("[Geolocation] Browser does not support geolocation");
        alert("Geolocation is not supported by your browser.");
        return;
    }
    console.log("[Geolocation] Requesting position from browser…");
    btn.disabled = true;
    var originalHtml = btn.innerHTML;
    btn.textContent = "Locating…";
    navigator.geolocation.getCurrentPosition(
        function (position) {
            console.log("[Geolocation] Position acquired — lat: " + position.coords.latitude + ", lon: " + position.coords.longitude + ", accuracy: " + position.coords.accuracy + "m");
            var latField = document.getElementById("SENSOR_LAT");
            var lonField = document.getElementById("SENSOR_LON");
            if (latField) {
                latField.value = position.coords.latitude.toFixed(6);
                console.log("[Geolocation] Set SENSOR_LAT to " + latField.value);
            } else {
                console.warn("[Geolocation] SENSOR_LAT field not found in config form");
            }
            if (lonField) {
                lonField.value = position.coords.longitude.toFixed(6);
                console.log("[Geolocation] Set SENSOR_LON to " + lonField.value);
            } else {
                console.warn("[Geolocation] SENSOR_LON field not found in config form");
            }
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        },
        function (error) {
            console.error("[Geolocation] Error (" + error.code + "): " + error.message);
            alert("Unable to retrieve your location: " + error.message);
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        },
        { enableHighAccuracy: true, timeout: 10000 }
    );
}

function read_conf() {
    if (document.getElementById("config").childElementCount == 1 && document.getElementById("optionsSidebar").style.display == "none") {
        var xhr = new XMLHttpRequest()
        xhr.open("GET", "api/get_config", true);
        xhr.onreadystatechange = function () {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                var status = xhr.status;
                if (status === 0 || (status >= 200 && status < 400)) {
                    var value = xhr.responseText;

                    var data = JSON.parse(value);
                    var itm = document.getElementById("linetemplate");
                    for (let i = 0; i < Object.keys(data).length; i++) {
                        //console.log(Object.keys(data)[i]);
                        //console.log(data[Object.keys(data)[i]])
                        //Skip extra junk in read_static_airport_data() dictionary not loaded from config file
                        if (String(Object.keys(data)[i]) == "DATATYPES" || String(Object.keys(data)[i]) == "ENDPOINT" || String(Object.keys(data)[i]) == "WEATHER_ENDPOINT") {
                            continue
                        }

                        for (let j = 0; j < data.DATATYPES.length; j++) {
                            if (data.DATATYPES[j].id == String(Object.keys(data)[i])) {
                                form_type = data.DATATYPES[j].type;
                                if (data.DATATYPES[j].hasOwnProperty('min')) {
                                    form_min = data.DATATYPES[j].min
                                } else {
                                    form_min = null
                                }
                                if (data.DATATYPES[j].hasOwnProperty('max')) {
                                    form_max = data.DATATYPES[j].max
                                } else {
                                    form_max = null
                                }
                                if (data.DATATYPES[j].hasOwnProperty('step')) {
                                    form_step = data.DATATYPES[j].step
                                } else {
                                    form_step = null
                                }
                                break
                            } else {
                                form_type = "text";
                            }
                        }

                        var cln = itm.cloneNode(true);
                        //cln.style="display:block";
                        cln.removeAttribute("style")
                        cln.childNodes[1].textContent = String(Object.keys(data)[i]).replaceAll('_', ' ') + ": ";
                        cln.childNodes[1].for = String(Object.keys(data)[i]);
                        cln.childNodes[2].type = form_type;
                        cln.childNodes[2].name = String(Object.keys(data)[i]);
                        cln.childNodes[2].id = String(Object.keys(data)[i]);
                        if (form_type == "checkbox") {
                            cln.childNodes[2].removeAttribute("value")
                            cln.childNodes[2].checked = (String(data[Object.keys(data)[i]]).toLowerCase() === 'true');
                        } else if (form_type == "number" || form_type == "range") {
                            if (form_step != null) {
                                cln.childNodes[2].step = form_step;
                            } else {
                                if (form_type == "number") { cln.childNodes[2].step = "any"; }
                            }
                            if (form_min != null) {
                                cln.childNodes[2].min = form_min;
                            }
                            if (form_max != null) {
                                cln.childNodes[2].max = form_max;
                            }
                            cln.childNodes[2].value = String(data[Object.keys(data)[i]]);
                        } else {
                            cln.childNodes[2].value = String(data[Object.keys(data)[i]]);
                        }

                        document.getElementById("config").insertBefore(cln, document.getElementById("config").lastElementChild)
                    }


                    console.log(xhr.responseText);
                    // Show the geolocation button if SENSOR_LAT/LON fields exist
                    if (document.getElementById("SENSOR_LAT") && document.getElementById("SENSOR_LON")) {
                        document.getElementById("geolocate_button").style.display = "";
                        console.log("[Geolocation] SENSOR_LAT and SENSOR_LON fields detected — showing geolocation button");
                    }
                } else {
                    console.log(xhr.responseText);
                    // Oh no! There has been an error with the request!
                }
            }
        };
        xhr.send();
    }
}

function update_sign_status() {
    call_endpoint("/status", function (current_status) {
        if (current_status === "0") {
            document.getElementById("toggle_switch").checked = false;
        } else {
            document.getElementById("toggle_switch").checked = true;
        }
    });

    call_endpoint("/get_mode", function (current_mode) {
        if (current_mode && current_mode !== "0") {
            document.getElementById(current_mode).style.backgroundColor = "red";
            global_current_mode = current_mode;

            // Unhide any special options for this mode. These are all currently placed
            // as divs immediately after the mode button in the HTML
            sib = document.getElementById(global_current_mode).nextElementSibling;
            if (sib && sib.hidden) {
                sib.hidden = false;
            }

            // Hide Finance search bar based on if we have ticker data
            // yet or not
            if (global_current_mode == "FINANCE") {
                sib.hidden = (valid_tickers === null);
            }

            if (global_current_mode == "FREE_SKETCH") {
                open_free_sketch_modal();
            }
        }
    });
}
