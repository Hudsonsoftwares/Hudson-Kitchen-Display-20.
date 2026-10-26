(function () {
    "use strict";

    const root = document.getElementById("order_status_root");
    if (!root) {
        return; // Not on the order-status page
    }

    const orderId = root.dataset.orderId;

    async function rpc(route, params) {
        const res = await fetch(route, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {}, id: Date.now() }),
        });
        const data = await res.json();
        return data.result;
    }

    let lastRenderedKey = null;

    function render(status) {
        if (!status) return;
        const pct = status.total_stages > 1 ? Math.round((status.sequence / (status.total_stages - 1)) * 100) : 100;
        const finished = status.sequence >= status.total_stages - 1;
        const stateKey = `${status.stage_name}|${pct}|${finished}`;
        if (stateKey === lastRenderedKey) {
            return; // State unchanged: skip re-rendering to prevent any DOM blinking
        }
        lastRenderedKey = stateKey;

        root.innerHTML = `
        <div class="os-wrap ${finished ? "os-done" : ""}">
            <div class="os-stage">${status.stage_name}</div>
            <div class="os-bar"><div class="os-bar-fill" style="width:${Math.min(100, pct)}%"></div></div>
            <div class="os-sub">${finished ? "Enjoy your meal!" : "Almost there"}</div>
        </div>`;
    }

    async function poll() {
        try {
            const status = await rpc("/hudson_kitchen_display/get_order_status", { order_id: orderId });
            render(status);
        } catch (e) {
            // keep last rendered state on transient network errors
        }
    }

    poll();
    setInterval(poll, 4000);
})();
