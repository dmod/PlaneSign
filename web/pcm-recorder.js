class PcmRecorderProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.recording = false;
        this.port.onmessage = ({ data }) => {
            if (data.type === "start") {
                this.channels = 0;
                this.bytes = 0;
                this.offset = 0;
                this.maxBytes = data.maxBytes;
                this.recording = true;
            } else if (data.type === "stop" && this.recording) {
                this.recording = false;
                this.flush();
                this.port.postMessage({ type: "stop", channels: this.channels, sampleRate });
            } else if (data.type === "cancel") {
                this.recording = false;
            }
        };
    }

    flush() {
        if (this.offset) {
            const buffer = this.buffer.slice(0, this.offset);
            this.port.postMessage({ type: "data", buffer }, [buffer]);
            this.offset = 0;
        }
    }

    fail(message) {
        this.recording = false;
        this.port.postMessage({ type: "error", message });
    }

    process(inputs) {
        const input = inputs[0];
        if (!this.recording || !input.length) {
            return true;
        }
        if (!this.channels) {
            this.channels = input.length;
            this.buffer = new ArrayBuffer(4096 * this.channels * 2);
            this.view = new DataView(this.buffer);
        }
        if (input.length !== this.channels || this.channels > 2) {
            this.fail("Microphone recording requires a stable mono or stereo input.");
            return true;
        }
        this.bytes += input[0].length * this.channels * 2;
        if (this.bytes + 44 > this.maxBytes) {
            this.fail("Microphone recordings must not exceed 32 MiB. Please record a shorter message.");
            return true;
        }
        for (let frame = 0; frame < input[0].length; frame++) {
            for (let channel = 0; channel < this.channels; channel++) {
                const sample = Math.max(-1, Math.min(1, input[channel][frame]));
                this.view.setInt16(this.offset, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
                this.offset += 2;
            }
            if (this.offset === this.buffer.byteLength) {
                this.flush();
            }
        }
        return true;
    }
}

registerProcessor("planesign-pcm-recorder", PcmRecorderProcessor);
