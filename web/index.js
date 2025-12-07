var global_current_mode;
var recordButton, recorder;
var valid_tickers = null;

window.onload = function () {
    update_sign_status();
    update_brightness_slider();
    set_version();
    get_audio_support();

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

        call_endpoint("/write_config?" + str);
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
            document.getElementById("ticker").value = ticker['symbol']
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

}

function set_lightning_mode(mode) {
    call_endpoint("/lightning_mode/" + mode);
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
        }
    });
}
