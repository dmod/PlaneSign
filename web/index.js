var global_current_mode;
var recordButton, recorder;

window.onload = function () {
    update_sign_status();
    update_brightness_slider();
    get_audio_support();

    recordButton = document.getElementById('mic_button');

    try {
        // get audio stream from user's mic
        navigator.mediaDevices.getUserMedia({
            audio: true
        })
            .then(function (stream) {
                recordButton.disabled = false;
                recordButton.addEventListener('mousedown', startRecording);
                recordButton.addEventListener('mouseup', stopRecording);
                recorder = new MediaRecorder(stream);

                // listen to dataavailable, which gets triggered whenever we have
                // an audio blob available
                recorder.addEventListener('dataavailable', onRecordingReady);
            });
    } catch (e) {
        console.error(e)
    }

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

        call_endpoint("/write_config?" + str);
    }

    document.getElementById("brightness_slider").oninput = function () {
        call_endpoint("/set_brightness/" + this.value);
    }

    document.getElementById("custom_message").oninput = function () {
        call_endpoint("/set_custom_message/" + encodeURIComponent(this.value));
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
        } else {
            call_endpoint('/turn_off')
        }
    }

}

function startRecording() {
    console.log("Starting recording...")

    var mic = document.getElementById("mic-icon");
    mic.style.fill = "red"

    recorder.start();
}

function stopRecording() {
    console.log("Stopping recording...")

    var mic = document.getElementById("mic-icon");
    mic.style.fill = "#1E2D70"

    // Stopping the recorder will eventually trigger the `dataavailable` event and we can complete the recording process
    recorder.stop();
}

function onRecordingReady(e) {
    fetch('api/play_audio', {
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
        document.getElementById("mic_button").hidden = ~value;
        document.getElementById("sounds_div").hidden = ~value;
        if (value) {
            populate_sound_dropdown();
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
    document.getElementById(global_current_mode).style.backgroundColor = "black"; // Turn off current button
    document.getElementById(mode).style.backgroundColor = "red"; // Turn on new button
    global_current_mode = mode;

    if (mode !== 8) {
        document.getElementById('custom_message_div').hidden = true;
    }
    if (mode !== 10) {
        document.getElementById('cgol_div').hidden = true;
    }
    if (mode !== 11) {
        document.getElementById('pong_div').hidden = true;
    }
    if (mode !== 13) {
        document.getElementById('finance_div').hidden = true;
    }
    if (mode !== 15) {
        document.getElementById('lightning_div').hidden = true;
    }
    if (mode !== 17) {
        document.getElementById('satellite_div').hidden = true;
    }
    if (mode !== 99) {
        document.getElementById('track-a-flight_div').hidden = true;
    }
    if (mode == 10) {
        var ele = document.getElementsByName('cgolstyle');
        for (i = 0; i < ele.length; i++) {
            if (ele[i].checked)
                break;
        }
        call_endpoint("/set_mode/" + mode + "?style=" + ele[i].value);
    } else {
        call_endpoint("/set_mode/" + mode);
    }

}

function set_lightning_mode(mode) {
    call_endpoint("/lightning_mode/" + mode);
}

function set_satellite_mode(mode) {
    call_endpoint("/satellite_mode/" + mode);
}

function set_color_mode(color) {
    call_endpoint("/set_color_mode/" + color);
}

function showoptions() {
    read_conf()
    document.getElementById("optionsSidebar").style.display = "block";
}

function hideoptions() {
    document.getElementById("optionsSidebar").style.display = "none";
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
                } else {
                    console.log(xhr.responseText);
                    // Oh no! There has been an error with the request!
                }
            }
        };
        xhr.send();
    }
}

function update_sign() {
    if (confirm('Are you sure you want to update?\n(Uncommitted sign updates will be lost)')) {
        call_endpoint("/update");
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
        }
    });
}
