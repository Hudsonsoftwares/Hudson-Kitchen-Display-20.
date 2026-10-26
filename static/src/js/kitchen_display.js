(function () {
    "use strict";

    const root = document.getElementById("kitchen_display_root");
    if (!root) {
        return; // Not on the kitchen display page
    }

    const displayId = root.dataset.displayId;
    let stages = [];
    let orders = [];
    let categories = [];
    let currentFilter = "all";
    let currentTimeFilter = "all";
    let currentPreset = "all";
    let currentCategory = "all";
    let zoomLevel = 0;
    let highContrast = localStorage.getItem("hkd_high_contrast") === "1";
    let soundOn = localStorage.getItem("hkd_sound") !== "0";
    let knownOrderIds = new Set();
    let audioCtx = null;

    async function rpc(route, params) {
        const res = await fetch(route, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {}, id: Date.now() }),
        });
        const data = await res.json();
        if (data.error) {
            console.error("Kitchen display RPC error:", data.error);
            throw new Error(data.error.data ? data.error.data.message : "RPC Error");
        }
        return data.result;
    }

    function playTone(freq, duration, type, delay, gainLevel) {
        if (!soundOn) return;
        try {
            audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
            const now = audioCtx.currentTime + (delay || 0);
            const osc = audioCtx.createOscillator();
            const gain = audioCtx.createGain();
            osc.type = type || "sine";
            osc.frequency.setValueAtTime(freq, now);
            gain.gain.setValueAtTime(gainLevel || 0.15, now);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.start(now);
            osc.stop(now + duration);
        } catch (e) {}
    }

    function getAudioContext() {
        if (!audioCtx) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {
                audioCtx = new AudioContext();
            }
        }
        if (audioCtx && audioCtx.state === "suspended") {
            audioCtx.resume();
        }
        return audioCtx;
    }

    // 1. New Order (To cook): Ding-Dong Chime (Warm, resonant two-tone chime)
    function playDingDongChime() {
        if (!soundOn) return;
        try {
            const ctx = getAudioContext();
            if (!ctx) return;
            const now = ctx.currentTime;

            // Tone 1 ("Ding" at t=0): High resonant tubular chime
            const dingPartials = [
                { freq: 659.25, gain: 0.28, decay: 0.9 },   // E5 fundamental
                { freq: 1318.5, gain: 0.12, decay: 0.5 },   // E6 harmonic
                { freq: 1977.7, gain: 0.06, decay: 0.25 }   // B6 shimmer
            ];
            dingPartials.forEach(p => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "sine";
                osc.frequency.setValueAtTime(p.freq, now);
                gain.gain.setValueAtTime(p.gain, now);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + p.decay);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now);
                osc.stop(now + p.decay);
            });

            // Tone 2 ("Dong" at t=0.32s): Deep, warm lower bell resonance
            const dongPartials = [
                { freq: 523.25, gain: 0.32, decay: 1.3 },   // C5 fundamental
                { freq: 1046.5, gain: 0.14, decay: 0.8 },   // C6 harmonic
                { freq: 1569.7, gain: 0.05, decay: 0.35 }   // G6 shimmer
            ];
            dongPartials.forEach(p => {
                const t = now + 0.32;
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "sine";
                osc.frequency.setValueAtTime(p.freq, t);
                gain.gain.setValueAtTime(p.gain, t);
                gain.gain.exponentialRampToValueAtTime(0.0001, t + p.decay);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(t);
                osc.stop(t + p.decay);
            });
        } catch (e) {}
    }

    // 2. Order Ready: Bright Double-Bell (Crisp double strike waiter/service bell: Ting-Ting!)
    function playBrightDoubleBell() {
        if (!soundOn) return;
        try {
            const ctx = getAudioContext();
            if (!ctx) return;
            const now = ctx.currentTime;

            // Strike 1 (t = 0): Crisp metallic bell tap
            const strike1 = [1567.98, 2351.97, 3135.96];
            strike1.forEach((f, idx) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "triangle";
                osc.frequency.setValueAtTime(f, now);
                const g = (idx === 0 ? 0.30 : 0.12 / idx);
                gain.gain.setValueAtTime(g, now);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.22);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(now);
                osc.stop(now + 0.22);
            });

            // Strike 2 (t = 0.14s): Higher, bright ringing bell tap
            const strike2 = [1760.00, 2640.00, 3520.00, 5280.00];
            strike2.forEach((f, idx) => {
                const t = now + 0.14;
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "sine";
                osc.frequency.setValueAtTime(f, t);
                const g = (idx === 0 ? 0.34 : 0.15 / idx);
                gain.gain.setValueAtTime(g, t);
                gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.70);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(t);
                osc.stop(t + 0.70);
            });
        } catch (e) {}
    }

    // 3. Completed / Done: Ascending Celebration Chime (4-Note Fanfare Chime: C5 -> E5 -> G5 -> C6)
    function playAscendingCelebrationChime() {
        if (!soundOn) return;
        try {
            const ctx = getAudioContext();
            if (!ctx) return;
            const now = ctx.currentTime;

            const notes = [
                { freq: 523.25, time: 0.00, decay: 0.38, gain: 0.24 }, // C5 (Do)
                { freq: 659.25, time: 0.12, decay: 0.38, gain: 0.26 }, // E5 (Mi)
                { freq: 783.99, time: 0.24, decay: 0.45, gain: 0.28 }, // G5 (Sol)
                { freq: 1046.50, time: 0.38, decay: 1.20, gain: 0.35 } // High C6 (High Do - triumphant sustained shimmer!)
            ];

            notes.forEach((n, idx) => {
                const t = now + n.time;
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.type = "sine";
                osc.frequency.setValueAtTime(n.freq, t);
                gain.gain.setValueAtTime(n.gain, t);
                gain.gain.exponentialRampToValueAtTime(0.0001, t + n.decay);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(t);
                osc.stop(t + n.decay);

                // Warm harmonic overtone for celebratory richness
                const oscHarm = ctx.createOscillator();
                const gainHarm = ctx.createGain();
                oscHarm.type = "sine";
                oscHarm.frequency.setValueAtTime(n.freq * 2, t);
                gainHarm.gain.setValueAtTime(n.gain * 0.35, t);
                gainHarm.gain.exponentialRampToValueAtTime(0.0001, t + (idx === 3 ? 0.95 : 0.28));
                oscHarm.connect(gainHarm);
                gainHarm.connect(ctx.destination);
                oscHarm.start(t);
                oscHarm.stop(t + (idx === 3 ? 0.95 : 0.28));
            });
        } catch (e) {}
    }

    function playSound(type) {
        if (!soundOn) return;
        try {
            getAudioContext();
            switch(type) {
                case "new_order":
                    // 1. Ding-Dong Chime (New order in To cook)
                    playDingDongChime();
                    break;
                case "ready":
                    // 2. Bright Double-Bell (Ready stage)
                    playBrightDoubleBell();
                    break;
                case "completed":
                case "done":
                    // 3. Ascending Celebration Chime (Completed / Done)
                    playAscendingCelebrationChime();
                    break;
                case "reset":
                    // Gentle descending two-tone for Undo / Reset (C5 -> G4)
                    playTone(523.25, 0.16, "sine", 0, 0.18);
                    playTone(392.00, 0.30, "sine", 0.12, 0.18);
                    break;
                case "line_done":
                    // Subtle clean tick for checking an item
                    playTone(880.00, 0.08, "sine", 0, 0.12);
                    break;
                case "late":
                    // Warning alert double-beep
                    playTone(880.00, 0.14, "sawtooth", 0, 0.16);
                    playTone(880.00, 0.14, "sawtooth", 0.18, 0.16);
                    break;
            }
        } catch (e) {}
    }

    function beep(freq, duration) {
        playSound("late");
    }

    function stageColor(idx) {
        if (typeof idx === "string" && (idx.startsWith("#") || idx.startsWith("rgb"))) {
            return idx;
        }
        const palette = ["#8d8d8d", "#e57373", "#f2c94c", "#4a90d9", "#7ed957", "#9b59b6", "#e67e22", "#1abc9c"];
        return palette[(idx || 0) % palette.length];
    }

    function minutesAgo(dateStr) {
        const created = new Date(dateStr.replace(" ", "T") + "Z");
        return Math.max(0, Math.floor((Date.now() - created.getTime()) / 60000));
    }

    function applyTheme() {
        root.classList.toggle("hkd-contrast", highContrast);
        const btn = document.getElementById("kd-contrast");
        if (btn) btn.classList.toggle("active", highContrast);
        const soundBtn = document.getElementById("kd-sound");
        if (soundBtn) soundBtn.textContent = soundOn ? "\uD83D\uDD0A" : "\uD83D\uDD07";
    }

    function buildLayout() {
        root.innerHTML = `
        <div class="kd-app">
            <div class="kd-header">
                <button class="kd-icon-btn" id="kd-close-x" title="Close">&#10005;</button>
                <div class="kd-tabs" id="kd-tabs"></div>
                <div class="kd-actions">
                    <button class="kd-icon-btn" id="kd-sound" title="Toggle sound">\uD83D\uDD0A</button>
                    <button class="kd-btn" id="kd-contrast" title="High contrast mode">Contrast</button>
                    <button class="kd-btn kd-has-tooltip" id="kd-recall" title="Undoes the last stage move you just made — e.g. moves an order back if it was accidentally marked Ready or Completed. Only works on the most recent move within the current stage." data-tooltip="Undoes the last stage move you just made — e.g. moves an order back if it was accidentally marked Ready or Completed. Only works on the most recent move within the current stage.">&#8634; Recall <span class="kd-help-icon">?</span></button>
                    <button class="kd-btn kd-btn-primary" id="kd-close-btn">Close &#8594;</button>
                </div>
            </div>
            <div class="kd-body">
                <div class="kd-sidebar">
                    <div class="kd-side-title">Time</div>
                    <div class="kd-side-item active" data-time="all">All</div>
                    <div class="kd-side-item" data-time="now">Now</div>
                    <div class="kd-side-item" data-time="today">Today</div>
                    <div class="kd-side-item" data-time="tomorrow">Tomorrow</div>
                    <div class="kd-side-item" data-time="next">Next days</div>
                    <div class="kd-side-title">Preset</div>
                    <div class="kd-side-item active" data-preset="all">All</div>
                    <div class="kd-side-item" data-preset="dine_in">Dine In</div>
                    <div class="kd-side-item" data-preset="takeout">Takeout</div>
                    <div class="kd-side-item" data-preset="delivery">Delivery</div>
                    <div class="kd-zoom">
                        <button class="kd-btn" id="kd-zoom-out">-</button>
                        <button class="kd-btn" id="kd-zoom-in">+</button>
                    </div>
                </div>
                <div class="kd-orders" id="kd-orders"></div>
            </div>
        </div>`;

        document.getElementById("kd-close-x").onclick = () => window.close();
        document.getElementById("kd-close-btn").onclick = () => window.close();
        document.getElementById("kd-recall").onclick = onRecallLast;
        document.getElementById("kd-zoom-in").onclick = () => adjustZoom(1);
        document.getElementById("kd-zoom-out").onclick = () => adjustZoom(-1);
        document.getElementById("kd-contrast").onclick = () => {
            highContrast = !highContrast;
            localStorage.setItem("hkd_high_contrast", highContrast ? "1" : "0");
            applyTheme();
        };
        document.getElementById("kd-sound").onclick = () => {
            soundOn = !soundOn;
            localStorage.setItem("hkd_sound", soundOn ? "1" : "0");
            applyTheme();
            if (soundOn) beep(880, 0.1);
        };

        root.querySelectorAll(".kd-has-tooltip .kd-help-icon").forEach((icon) => {
            icon.addEventListener("click", (e) => {
                e.stopPropagation();
                const parent = icon.closest(".kd-has-tooltip");
                if (parent) {
                    parent.classList.toggle("touch-tooltip-active");
                    setTimeout(() => parent.classList.remove("touch-tooltip-active"), 4000);
                }
            });
        });

        root.querySelectorAll("[data-time]").forEach((el) => {
            el.onclick = () => {
                root.querySelectorAll("[data-time]").forEach((e) => e.classList.remove("active"));
                el.classList.add("active");
                currentTimeFilter = el.dataset.time;
                renderOrders();
            };
        });
        root.querySelectorAll("[data-preset]").forEach((el) => {
            el.onclick = () => {
                root.querySelectorAll("[data-preset]").forEach((e) => e.classList.remove("active"));
                el.classList.add("active");
                currentPreset = el.dataset.preset;
                renderOrders();
            };
        });

        applyTheme();
    }

    function adjustZoom(delta) {
        zoomLevel = Math.max(-2, Math.min(3, zoomLevel + delta));
        document.getElementById("kd-orders").style.fontSize = 14 + zoomLevel * 2 + "px";
    }

    function renderTabs() {
        const tabsEl = document.getElementById("kd-tabs");
        const counts = { all: orders.length };
        stages.forEach((s) => (counts[s.id] = orders.filter((o) => o.stage_id === s.id).length));
        let html = `<button class="kd-tab ${currentFilter === "all" ? "active" : ""}" data-filter="all">All <b>${counts.all}</b></button>`;
        stages.forEach((s) => {
            html += `<button class="kd-tab ${currentFilter == s.id ? "active" : ""}" style="--kd-tab-color:${stageColor(s.color)}" data-filter="${s.id}">${s.name} <b>${counts[s.id] || 0}</b></button>`;
        });
        tabsEl.innerHTML = html;
        tabsEl.querySelectorAll(".kd-tab").forEach((btn) => {
            btn.onclick = () => {
                currentFilter = btn.dataset.filter;
                renderTabs();
                renderOrders();
            };
        });
    }

    function passesTimeFilter(order) {
        if (currentTimeFilter === "all") return true;
        const created = new Date(order.create_date.replace(" ", "T") + "Z");
        const now = new Date();
        const tomorrow = new Date(now);
        tomorrow.setDate(now.getDate() + 1);
        if (currentTimeFilter === "now") return minutesAgo(order.create_date) < 30;
        if (currentTimeFilter === "today") return created.toDateString() === now.toDateString();
        if (currentTimeFilter === "tomorrow") return created.toDateString() === tomorrow.toDateString();
        if (currentTimeFilter === "next") return created > tomorrow;
        return true;
    }

    function renderOrders() {
        const container = document.getElementById("kd-orders");
        const filtered = orders.filter((o) => {
            if (currentFilter !== "all" && String(o.stage_id) !== String(currentFilter)) return false;
            if (currentPreset !== "all" && o.fulfillment_type !== currentPreset) return false;
            if (currentCategory !== "all" && (!o.category_ids || !o.category_ids.includes(Number(currentCategory)))) return false;
            if (!passesTimeFilter(o)) return false;
            return true;
        });

        if (!filtered.length) {
            container.innerHTML = `<div class="kd-empty">No orders here right now.</div>`;
            return;
        }

        let anyLateNew = false;
        container.innerHTML = filtered
            .map((o) => {
                const stage = stages.find((s) => s.id === o.stage_id);
                const stageIdx = stages.indexOf(stage);
                const age = minutesAgo(o.create_date);
                const late = stage && stage.alert_timer > 0 && age >= stage.alert_timer;
                const isLastStage = (stageIdx === stages.length - 1) || (stage && stage.name && stage.name.toLowerCase().includes("complete"));
                const next = stages[stageIdx + 1];

                let actionsHtml = "";
                if (isLastStage) {
                    actionsHtml = `
                        <button class="kd-reset" data-order="${o.id}">
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>Reset
                        </button>
                        <button class="kd-done kd-has-tooltip" data-order="${o.id}" title="Clears all completed orders from the last stage (e.g. Completed) at once, instead of removing them one by one." data-tooltip="Clears all completed orders from the last stage (e.g. Completed) at once, instead of removing them one by one.">Done <span class="kd-help-icon">?</span></button>
                    `;
                }

                return `
            <div class="kd-card ${late ? "kd-late" : ""}" style="--kd-stage-color:${stageColor(stage ? stage.color : 0)}">
                <div class="kd-card-head">
                    <span>#${o.pos_reference || o.id}</span>
                    <span class="kd-age">${age}'</span>
                </div>
                <div class="kd-card-sub">${o.table_number ? "Table " + o.table_number : (o.fulfillment_type || "").replace("_", " ")}</div>
                <ul class="kd-lines">
                    ${o.lines
                        .map(
                            (l) =>
                                `<li>${l.qty} &times; ${l.name}${l.note ? ' <i class="kd-note">- ' + l.note + "</i>" : ""}</li>`
                        )
                        .join("")}
                </ul>
                <div class="kd-card-actions">
                    ${actionsHtml}
                </div>
            </div>`;
            })
            .join("");

        if (anyLateNew) {
            beep(440, 0.25);
        }

        container.querySelectorAll(".kd-advance").forEach((btn) => {
            btn.onclick = async () => {
                const order = orders.find((o) => o.id == btn.dataset.order);
                const stage = stages.find((s) => s.id === order.stage_id);
                const idx = stages.indexOf(stage);
                const next = stages[idx + 1];
                if (next) {
                    btn.disabled = true;
                    if (next.name.toLowerCase().includes("complete")) playSound("completed");
                    else playSound("ready");
                    await rpc("/hudson_kitchen_display/change_stage", { order_id: order.id, stage_id: next.id });
                    fetchAndRender();
                }
            };
        });
        container.querySelectorAll(".kd-reset").forEach((btn) => {
            btn.onclick = async () => {
                btn.disabled = true;
                playSound("reset");
                await rpc("/hudson_kitchen_display/reset_order", { order_id: btn.dataset.order });
                fetchAndRender();
            };
        });
        container.querySelectorAll(".kd-done").forEach((btn) => {
            btn.onclick = async () => {
                btn.disabled = true;
                playSound("done");
                await rpc("/hudson_kitchen_display/mark_done", { order_id: btn.dataset.order });
                fetchAndRender();
            };
        });
    }

    async function onRecallLast() {
        try {
            playSound("reset");
            await rpc("/hudson_kitchen_display/recall", { display_id: displayId });
            await fetchAndRender();
        } catch (e) {
            console.error("Recall error:", e);
        }
    }

    async function fetchAndRender() {
        try {
            const data = await rpc("/hudson_kitchen_display/get_orders", { display_id: displayId });
            const newIds = new Set(data.orders.map((o) => o.id));
            let hasNew = false;
            newIds.forEach((id) => {
                if (!knownOrderIds.has(id)) hasNew = true;
            });
            if (knownOrderIds.size && hasNew) {
                beep(660, 0.2);
            }
            knownOrderIds = newIds;
            stages = data.stages;
            orders = data.orders;
            renderTabs();
            renderOrders();
        } catch (e) {
            const container = document.getElementById("kd-orders");
            if (container) {
                container.innerHTML = `<div class="kd-empty">Could not load orders. Check the display is configured and you are logged in.</div>`;
            }
        }
    }

    function connectRealtime() {
        // Best-effort websocket push for near-instant refresh. Falls back to
        // plain polling (below) if this fails to connect for any reason -
        // websocket path/protocol can differ slightly across Odoo versions.
        try {
            const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
            const ws = new WebSocket(proto + window.location.host + "/websocket");
            ws.onopen = () => {
                ws.send(JSON.stringify({
                    event_name: "subscribe",
                    data: { channels: [`pos_prep_display-${displayId}`], last: 0 },
                }));
            };
            ws.onmessage = () => fetchAndRender();
            ws.onerror = () => {};
        } catch (e) {
            // no websocket support / blocked - polling below still covers us
        }
    }

    buildLayout();
    fetchAndRender();
    connectRealtime();
    setInterval(fetchAndRender, 8000); // safety-net poll even if websocket is connected
})();
