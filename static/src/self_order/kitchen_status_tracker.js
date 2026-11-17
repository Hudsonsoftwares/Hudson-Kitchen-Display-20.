import { Component, onMounted, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { serializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { SelfOrder } from "@pos_self_order/app/services/self_order_service";
import { LandingPage } from "@pos_self_order/app/pages/landing_page/landing_page";
import { OrdersHistoryPage } from "@pos_self_order/app/pages/order_history_page/order_history_page";
import { CartPage } from "@pos_self_order/app/pages/cart_page/cart_page";
import { ConfirmationPage } from "@pos_self_order/app/pages/confirmation_page/confirmation_page";

export class KitchenOrderStatusCard extends Component {
    static template = "hudson_kitchen_display.KitchenOrderStatusCard";

    props = useProps({
        orderAccessToken: t.string(),
        showRefreshHint: t.boolean().optional(),
    });

    setup() {
        this.selfOrder = this.env.services.self_order;
        // Open by default so food items and stepper are directly visible
        this.state = proxy({ collapsedTickets: {} });
    }

    toggleBatch(ticketId) {
        this.state.collapsedTickets[ticketId] = !this.state.collapsedTickets[ticketId];
    }

    isBatchExpanded(batch) {
        return !this.state.collapsedTickets[batch.ticket_id];
    }

    get status() {
        return this.selfOrder.kitchenStatusByToken?.[this.props.orderAccessToken] || null;
    }

    get hasDisplays() {
        const s = this.status;
        return Boolean(
            s &&
            !s.is_cancelled &&
            s.has_kitchen &&
            !s.is_served_done &&
            s.summary_state !== "completed" &&
            ((s.batches && s.batches.length) || (s.displays && s.displays.length))
        );
    }

    get batches() {
        const s = this.status;
        if (!s || s.is_cancelled || !s.has_kitchen || s.is_served_done || s.summary_state === "completed") {
            return [];
        }
        if (s.batches && s.batches.length) {
            // One block per kitchen station (Kitchen, Bar, Desserts...) of every unfinished round,
            // so items going to different stations each show their own live KDS stage.
            const blocks = [];
            for (const batch of s.batches) {
                if (batch.is_completed) {
                    continue;
                }
                const stations = batch.stations && batch.stations.length ? batch.stations : [batch];
                for (const station of stations) {
                    blocks.push({
                        ...station,
                        ticket_id: `${batch.round_key || batch.ticket_id}_${station.display_id || 0}`,
                        created_at: batch.created_at,
                    });
                }
            }
            return blocks;
        }
        return (s.displays || []).map((d, idx) => ({
            ...d,
            ticket_id: d.display_id || idx + 1,
            batch_number: idx + 1,
            categories: [],
        }));
    }

    get hasMultipleBatches() {
        return this.batches.length > 1;
    }

    get summaryPillClass() {
        const s = this.status;
        if (!s) return "hkd_self_status_pill--cook";
        if (s.is_served_done || s.summary_state === "completed") {
            return "hkd_self_status_pill--done";
        }
        if ((s.summary_label || "").toLowerCase().includes("ready")) {
            return "hkd_self_status_pill--ready";
        }
        return "hkd_self_status_pill--cook";
    }

    getBatchTitle(batch) {
        if (batch.display_name) {
            return batch.display_name;
        }
        return _t("Current Kitchen Order");
    }

    /** In the KDS's last stage ("Completed"), waiting for the kitchen to press Done. */
    isFinalStage(disp) {
        return Boolean(disp && disp.total_stages && disp.current_stage_index === disp.total_stages - 1);
    }

    getStationThemeClass(batch) {
        if (batch.is_served_done || batch.is_completed || this.isFinalStage(batch)) {
            return "hkd_self_status_station--completed";
        }
        const name = (batch.current_stage_name || "").toLowerCase();
        if (name.includes("ready")) {
            return "hkd_self_status_station--ready";
        }
        return "hkd_self_status_station--cook";
    }

    formatBatchTime(createdAt) {
        if (!createdAt) return "";
        try {
            const iso = createdAt.replace(" ", "T") + "Z";
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return "";
            return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        } catch {
            return "";
        }
    }

    getPillClass(disp) {
        if (disp.is_served_done || disp.is_completed || this.isFinalStage(disp)) {
            return "hkd_self_status_pill--done";
        }
        const name = (disp.current_stage_name || "").toLowerCase();
        if (name.includes("ready")) {
            return "hkd_self_status_pill--ready";
        }
        return "hkd_self_status_pill--cook";
    }

    getStepClasses(disp, stage, idx) {
        const classes = [];
        if (stage.state === "done") {
            classes.push("hkd_self_step--done");
        } else if (stage.state === "active") {
            classes.push("hkd_self_step--active");
        } else {
            classes.push("hkd_self_step--pending");
        }
        if (idx === (disp.stages?.length || 0) - 1) {
            classes.push("hkd_self_step--last");
        }
        return classes.join(" ");
    }

    isLeftLineFilled(disp, idx) {
        if (idx === 0) {
            return false;
        }
        const prev = disp.stages?.[idx - 1];
        return prev?.state === "done";
    }

    isRightLineFilled(disp, idx) {
        const stages = disp.stages || [];
        if (idx >= stages.length - 1) {
            return false;
        }
        const curr = stages[idx];
        return curr?.state === "done";
    }
}

patch(SelfOrder.prototype, {
    setup() {
        super.setup(...arguments);
        this.kitchenStatusByToken = proxy({});
        this._kitchenTrackingCount = 0;
        this._kitchenTrackingTimer = null;
        this._kitchenRefreshDebounce = null;
        this._kitchenFetchInFlight = false;
        this._kitchenFetchQueued = false;
        this._kitchenQueuedOrders = null;

        this.data.connectWebSocket("KITCHEN_STATUS_CHANGED", () => {
            if (this._kitchenTrackingCount > 0) {
                this.scheduleKitchenStatusRefresh(100);
            }
        });
        this.data.connectWebSocket("ORDER_STATE_CHANGED", () => {
            if (this._kitchenTrackingCount > 0) {
                this.scheduleKitchenStatusRefresh(350);
            }
        });
    },

    /**
     * When an order has already been sent/synced to the server, do not reuse
     * it for new cart items. Each new submission creates an individual order.
     */
    isOrderAvailable(order) {
        if (this.config?.self_ordering_mode === "mobile" && order?.isSynced) {
            return false;
        }
        return super.isOrderAvailable(...arguments);
    },

    async confirmationPage(screen_mode, device, access_token) {
        await super.confirmationPage(...arguments);
        // Reset selected order UUID so the next order placed by customer is a completely fresh order
        this.selectedOrderUuid = null;
    },

    /**
     * Same as Odoo's refresh, WITHOUT the "pay after meal" merge: Odoo picks the table's
     * open order and deletes every other open order (moving its lines into it). Here every
     * order stays separate; only the cart selection is kept valid.
     */
    async _getUserDataFromServer(tokens = [], opts = {}) {
        if (this.config?.self_ordering_mode !== "mobile") {
            return super._getUserDataFromServer(...arguments);
        }
        const tableIdentifier = this.currentTableIdentifier;
        const dbAccessToken = this.models["pos.order"]
            .filter((o) => o.state === "draft" && o.isSynced && o.access_token)
            .map((order) => ({
                access_token: order.access_token,
                state: order.state,
                write_date: serializeDateTime(order.write_date.plus({ seconds: 1 })),
            }));
        const argTokens = tokens.map((token) => ({
            access_token: token,
            write_date: "1970-01-01 00:00:00",
        }));
        const accessTokens = [...dbAccessToken, ...argTokens];
        if (accessTokens.length === 0 && !tableIdentifier) {
            return;
        }
        const pendingDeltas = this._computePendingDeltas();
        try {
            const data = await rpc(`/pos-self-order/get-user-data/`, {
                access_token: this.access_token,
                order_access_tokens: accessTokens,
                table_identifier: tableIdentifier,
            });
            const result = this.models.connectNewData(data);
            for (const order of result["pos.order"] || []) {
                if (order.state === "draft") {
                    this._reapplyPendingDeltas(order, pendingDeltas);
                }
            }
            // Never reopen an order already sent to the kitchen as the cart
            const selected = this.selectedOrderUuid
                ? this.models["pos.order"].getBy("uuid", this.selectedOrderUuid)
                : null;
            if (selected && !this.isOrderAvailable(selected)) {
                this.selectedOrderUuid = null;
            }
            this.data.debouncedSynchronizeLocalDataInIndexedDB();
        } catch (error) {
            this.handleErrorNotification(
                error,
                this.models["pos.order"].map((order) => order.access_token)
            );
        }
    },

    /** Download Receipt on every order sent to the restaurant (unpaid ones get a provisional bill). */
    showDownloadButton(order) {
        if (this.config?.self_ordering_mode !== "mobile") {
            return super.showDownloadButton(...arguments);
        }
        return Boolean(order && typeof order.id === "number" && order.access_token && order.state !== "cancel");
    },

    async downloadReceipt(order) {
        if (this.config?.self_ordering_mode !== "mobile") {
            return super.downloadReceipt(...arguments);
        }
        // All states use our route: it falls back to a PDF when the server has no wkhtmltoimage
        // (Odoo's own /pos-self-order/receipt then fails with "422 Unprocessable Entity").
        if (!order?.id || typeof order.id !== "number") {
            return;
        }
        const link = document.createElement("a");
        link.href = `/pos-self-order/hkd-receipt/${order.id}?access_token=${encodeURIComponent(order.access_token)}`;
        link.click();
    },

    /** True while the kitchen is still working on the order this status belongs to. */
    isKitchenStatusActive(status) {
        return Boolean(
            status &&
            !status.is_cancelled &&
            status.has_kitchen &&
            !status.is_served_done &&
            status.summary_state !== "completed" &&
            ((status.batches && status.batches.length) || (status.displays && status.displays.length))
        );
    },

    /**
     * Orders whose kitchen status must be (re)fetched:
     * - orders not fetched yet,
     * - orders the kitchen is still working on,
     * - draft orders.
     */
    getActiveKitchenOrders(orders = null) {
        let candidates = orders;
        if (!candidates || !candidates.length) {
            candidates = (this.models["pos.order"] || [])
                .filter((o) => o && o.access_token)
                .sort((a, b) => (b.id || 0) - (a.id || 0))
                .slice(0, 20);
        }
        return (candidates || []).filter((o) => {
            if (!o || !o.access_token || o.state === "cancel") {
                return false;
            }
            const status = this.kitchenStatusByToken?.[o.access_token];
            if (!status || o.state === "draft") {
                return true;
            }
            return this.isKitchenStatusActive(status);
        });
    },

    _ensureKitchenTimer() {
        if (this._kitchenTrackingTimer || this._kitchenTrackingCount <= 0) {
            return;
        }
        this._kitchenTrackingTimer = setInterval(() => {
            if (this._kitchenTrackingCount > 0) {
                this.fetchKitchenStatus();
            } else if (this._kitchenTrackingTimer) {
                clearInterval(this._kitchenTrackingTimer);
                this._kitchenTrackingTimer = null;
            }
        }, 3500);
    },

    async fetchKitchenStatus(orders = null) {
        if (this.config?.self_ordering_mode !== "mobile") {
            return;
        }
        if (this._kitchenFetchInFlight) {
            this._kitchenFetchQueued = true;
            if (orders && orders.length) {
                this._kitchenQueuedOrders = orders;
            }
            return;
        }
        const activeOrders = this.getActiveKitchenOrders(orders);
        if (!activeOrders.length) {
            if (this._kitchenTrackingTimer) {
                clearInterval(this._kitchenTrackingTimer);
                this._kitchenTrackingTimer = null;
            }
            return;
        }
        const seenTokens = new Set();
        const payload = [];
        for (const o of activeOrders) {
            if (!seenTokens.has(o.access_token)) {
                seenTokens.add(o.access_token);
                payload.push({ id: o.id, access_token: o.access_token });
            }
        }
        if (!payload.length) {
            if (this._kitchenTrackingTimer) {
                clearInterval(this._kitchenTrackingTimer);
                this._kitchenTrackingTimer = null;
            }
            return;
        }
        this._kitchenFetchInFlight = true;
        try {
            const res = await rpc("/pos-self-order/kitchen-status", {
                access_token: this.access_token,
                orders: payload,
            });
            const statuses = res?.statuses || {};
            for (const [token, nextStatus] of Object.entries(statuses)) {
                const prev = this.kitchenStatusByToken[token];
                if (JSON.stringify(prev) !== JSON.stringify(nextStatus)) {
                    this.kitchenStatusByToken[token] = nextStatus;
                }
            }
            const remaining = this.getActiveKitchenOrders();
            if (!remaining.length && this._kitchenTrackingTimer) {
                clearInterval(this._kitchenTrackingTimer);
                this._kitchenTrackingTimer = null;
            } else if (remaining.length) {
                this._ensureKitchenTimer();
            }
        } catch {
            // Keep last known state on transient error
        } finally {
            this._kitchenFetchInFlight = false;
            if (this._kitchenFetchQueued) {
                const nextOrders = this._kitchenQueuedOrders;
                this._kitchenFetchQueued = false;
                this._kitchenQueuedOrders = null;
                this.fetchKitchenStatus(nextOrders);
            }
        }
    },

    scheduleKitchenStatusRefresh(delayMs = 150) {
        clearTimeout(this._kitchenRefreshDebounce);
        this._kitchenRefreshDebounce = setTimeout(() => {
            this.fetchKitchenStatus();
        }, delayMs);
    },

    startKitchenTracking(orders = null) {
        this._kitchenTrackingCount += 1;
        const activeOrders = this.getActiveKitchenOrders(orders);
        if (!activeOrders.length) {
            return;
        }
        this.fetchKitchenStatus(activeOrders);
        this._ensureKitchenTimer();
    },

    stopKitchenTracking() {
        this._kitchenTrackingCount = Math.max(0, this._kitchenTrackingCount - 1);
        if (this._kitchenTrackingCount === 0 && this._kitchenTrackingTimer) {
            clearInterval(this._kitchenTrackingTimer);
            this._kitchenTrackingTimer = null;
        }
    },
});

patch(LandingPage.prototype, {
    clickMyOrder() {
        this.router.navigate("orderHistory");
    },
});

OrdersHistoryPage.components = {
    ...(OrdersHistoryPage.components || {}),
    KitchenOrderStatusCard,
};

patch(OrdersHistoryPage.prototype, {
    setup() {
        super.setup(...arguments);
        this._historyKitchenStarted = false;
        this._historyUnmounted = false;
        onMounted(async () => {
            if (this.selfOrder.config?.self_ordering_mode === "mobile") {
                if (!this._historyUnmounted && !this._historyKitchenStarted) {
                    this._historyKitchenStarted = true;
                    this.selfOrder.startKitchenTracking(this.orders);
                }
                try {
                    await this.selfOrder.getUserDataFromServer();
                    if (!this._historyUnmounted && this.orders?.length) {
                        this.selfOrder.fetchKitchenStatus(this.orders);
                    }
                } catch {
                    // Fallback
                }
            }
        });
        onWillUnmount(() => {
            this._historyUnmounted = true;
            if (this._historyKitchenStarted) {
                this.selfOrder.stopKitchenTracking();
                this._historyKitchenStarted = false;
            }
        });
    },

    /**
     * Checks if this specific order is active in the kitchen.
     * When completed, it returns false, causing the KDS card to disappear.
     */
    isOrderActive(order) {
        if (!order || !order.access_token || order.state === "cancel") {
            return false;
        }
        const status = this.selfOrder.kitchenStatusByToken?.[order.access_token];
        return Boolean(
            status &&
            !status.is_cancelled &&
            status.has_kitchen &&
            !status.is_served_done &&
            status.summary_state !== "completed" &&
            ((status.batches && status.batches.length) || (status.displays && status.displays.length))
        );
    },

    /** Every order is its own card: orders still in the kitchen first, then newest first. */
    get orders() {
        const orders = super.orders;
        if (this.selfOrder.config?.self_ordering_mode !== "mobile") {
            return orders;
        }
        return [...orders].sort(
            (a, b) =>
                Number(this.isOrderActive(b)) - Number(this.isOrderActive(a)) || (b.id || 0) - (a.id || 0)
        );
    },

    /** Badge text: latest KDS stage while cooking, then Served / Paid. */
    getOrderStatusLabel(order) {
        if (order.state === "cancel") {
            return _t("Cancelled");
        }
        const status = this.selfOrder.kitchenStatusByToken?.[order.access_token];
        if (this.isOrderActive(order)) {
            return status.summary_label || _t("Preparing");
        }
        if (["paid", "done", "invoiced"].includes(order.state)) {
            return _t("Paid");
        }
        if (status && status.summary_state === "completed") {
            return _t("Served");
        }
        if (typeof order.id !== "number") {
            return _t("Not sent");
        }
        return _t("Ordered");
    },

    getOrderBadgeClass(order) {
        const status = this.selfOrder.kitchenStatusByToken?.[order.access_token];
        const label = (status?.summary_label || "").toLowerCase();
        if (this.isOrderActive(order)) {
            const lead = status?.batches?.[0];
            if (lead && lead.total_stages && lead.current_stage_index === lead.total_stages - 1) {
                return "text-bg-success"; // last KDS stage, waiting for "Done"
            }
            return label.includes("ready") ? "text-bg-info" : "text-bg-warning";
        }
        return ["paid", "done", "invoiced"].includes(order.state) ? "text-bg-success" : "text-bg-primary";
    },

    editOrder(order) {
        // Do not navigate away when clicking the order header
        return;
    },
});

CartPage.components = {
    ...(CartPage.components || {}),
    KitchenOrderStatusCard,
};

patch(CartPage.prototype, {
    setup() {
        super.setup(...arguments);
        this._cartKitchenStarted = false;
        this._cartUnmounted = false;
        onMounted(async () => {
            if (this.selfOrder.config?.self_ordering_mode === "mobile" && !this.isCheckout) {
                if (this.showKitchenStatusBanner && !this._cartUnmounted && !this._cartKitchenStarted) {
                    this._cartKitchenStarted = true;
                    this.selfOrder.startKitchenTracking([this.selfOrder.currentOrder]);
                }
                try {
                    await this.selfOrder.getUserDataFromServer();
                    if (this.showKitchenStatusBanner && !this._cartUnmounted) {
                        if (!this._cartKitchenStarted) {
                            this._cartKitchenStarted = true;
                            this.selfOrder.startKitchenTracking([this.selfOrder.currentOrder]);
                        } else {
                            this.selfOrder.fetchKitchenStatus([this.selfOrder.currentOrder]);
                        }
                    }
                } catch {
                    // Fallback polling still handles updates.
                }
            }
        });
        onWillUnmount(() => {
            this._cartUnmounted = true;
            if (this._cartKitchenStarted) {
                this.selfOrder.stopKitchenTracking();
                this._cartKitchenStarted = false;
            }
        });
    },

    get showKitchenStatusBanner() {
        const order = this.selfOrder.currentOrder;
        return Boolean(
            this.selfOrder.config?.self_ordering_mode === "mobile" &&
            !this.isCheckout &&
            order &&
            order.isSynced &&
            order.access_token &&
            order.state !== "cancel"
        );
    },

    openMyOrders() {
        this.router.navigate("orderHistory");
    },
});

ConfirmationPage.components = {
    ...(ConfirmationPage.components || {}),
    KitchenOrderStatusCard,
};

patch(ConfirmationPage.prototype, {
    setup() {
        super.setup(...arguments);
        this._confirmationKitchenStarted = false;
        onMounted(() => {
            if (this.selfOrder.config?.self_ordering_mode === "mobile") {
                const token = this.props.orderAccessToken;
                const order = this.selfOrder.models["pos.order"].find((o) => o.access_token === token);
                this._confirmationKitchenStarted = true;
                this.selfOrder.startKitchenTracking(order ? [order] : null);
            }
        });
        onWillUnmount(() => {
            if (this._confirmationKitchenStarted) {
                this.selfOrder.stopKitchenTracking();
                this._confirmationKitchenStarted = false;
            }
        });
    },

    /**
     * Mobile mode clears selectedOrderUuid once an order is sent (so the next cart is a fresh
     * order). Odoo's getter only looks at selectedOrderUuid, which then returns undefined and
     * the page crashes ("reading 'preset_id'") with a blank screen. Fall back to the order of
     * this page's access token.
     */
    get confirmedOrder() {
        return (
            super.confirmedOrder ||
            this.selfOrder.models["pos.order"].find(
                (o) => o.access_token === this.props.orderAccessToken
            )
        );
    },

    async initOrder() {
        await super.initOrder(...arguments);
        if (this.selfOrder.config?.self_ordering_mode === "mobile" && this.confirmedOrder?.access_token) {
            await this.selfOrder.fetchKitchenStatus([this.confirmedOrder]);
        }
    },

    get showMobileKitchenStatus() {
        return Boolean(
            this.selfOrder.config?.self_ordering_mode === "mobile" &&
            this.confirmedOrder?.access_token
        );
    },

    openMyOrders() {
        this.router.navigate("orderHistory");
    },
});
