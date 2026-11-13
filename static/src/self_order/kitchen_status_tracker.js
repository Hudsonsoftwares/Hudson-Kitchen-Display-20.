import { Component, onMounted, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
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
        this.state = proxy({ expandedRounds: {} });
    }

    get order() {
        return (this.selfOrder.models["pos.order"] || []).find((o) => o && o.access_token === this.props.orderAccessToken) || null;
    }

    get orderPosReference() {
        return this.order?.pos_reference || this.status?.pos_reference || _t("Current Order");
    }

    get orderSubmeta() {
        const order = this.order;
        const trackingNum = order?.tracking_number || this.status?.tracking_number;
        let dateStr = "";
        if (order?.date_order) {
            try {
                dateStr = typeof order.date_order.toFormat === "function" ? order.date_order.toFormat("dd/MM/yyyy") : String(order.date_order);
            } catch {
                dateStr = "";
            }
        }
        if (!dateStr && this.batches.length && this.batches[0].created_at) {
            dateStr = this.formatBatchDate(this.batches[0].created_at);
        }
        if (trackingNum && dateStr) {
            return `#${trackingNum} - ${dateStr}`;
        } else if (trackingNum) {
            return `#${trackingNum}`;
        } else if (dateStr) {
            return dateStr;
        }
        return "";
    }

    formatBatchDate(createdAt) {
        if (!createdAt) return "";
        try {
            const iso = createdAt.replace(" ", "T") + "Z";
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return "";
            const day = String(d.getDate()).padStart(2, "0");
            const month = String(d.getMonth() + 1).padStart(2, "0");
            const year = d.getFullYear();
            return `${day}/${month}/${year}`;
        } catch {
            return "";
        }
    }

    toggleBatch(batch) {
        if (batch && batch.is_current) {
            return;
        }
        const key = batch ? (batch.round_key || batch.ticket_id) : null;
        if (key) {
            this.state.expandedRounds[key] = !this.state.expandedRounds[key];
        }
    }

    isBatchExpanded(batch) {
        if (batch && batch.is_current) {
            // Current Order is always open and directly displays its foods & stepper
            return true;
        }
        const key = batch ? (batch.round_key || batch.ticket_id) : null;
        return Boolean(key && this.state.expandedRounds[key]);
    }

    get status() {
        return this.selfOrder.kitchenStatusByToken?.[this.props.orderAccessToken] || null;
    }

    get hasDisplays() {
        const s = this.status;
        if (!s || s.is_cancelled || !s.has_kitchen || s.is_served_done || s.summary_state === "completed") {
            return false;
        }
        return Boolean(this.batches.length);
    }

    get batches() {
        const s = this.status;
        if (!s || s.is_cancelled || !s.has_kitchen || s.is_served_done || s.summary_state === "completed") {
            return [];
        }
        const allBatches = (s.batches && s.batches.length) ? s.batches : (s.displays || []).map((d, idx) => ({
            ...d,
            ticket_id: d.display_id || idx + 1,
            batch_number: idx + 1,
            round_key: `disp_${idx + 1}`,
            is_current: true,
            title: _t("Current Order"),
            categories: [],
        }));
        // Show strictly the current active order in the KDS tracker card
        const current = allBatches.filter((b) => b.is_current && !b.is_completed && !b.is_served_done);
        return current.length ? current : (allBatches.length && !allBatches[allBatches.length - 1].is_completed && !allBatches[allBatches.length - 1].is_served_done ? [allBatches[allBatches.length - 1]] : []);
    }

    get hasMultipleBatches() {
        return false;
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
        if (batch.title) {
            return batch.title;
        }
        if (batch.is_current) {
            return _t("Current Order");
        }
        return batch.display_name || _t("Order");
    }

    getStationThemeClass(batch) {
        if (batch.is_served_done || batch.is_completed) {
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
        if (disp.is_served_done || disp.is_completed) {
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

    getActiveKitchenOrders(orders = null) {
        let candidates = orders;
        if (!candidates || !candidates.length) {
            const all = this.models["pos.order"]
                .filter((o) => o && typeof o.id === "number" && o.access_token && o.state !== "cancel" && o.state !== "paid" && o.state !== "done")
                .sort((a, b) => (b.id || 0) - (a.id || 0));
            const cur = this.currentOrder;
            if (cur && typeof cur.id === "number" && cur.access_token && cur.state !== "cancel" && cur.state !== "paid" && cur.state !== "done") {
                candidates = [cur, ...all.filter((o) => o.id !== cur.id)];
            } else {
                candidates = all;
            }
        }
        return (candidates || []).filter((o) => {
            if (!o || typeof o.id !== "number" || !o.access_token || o.state === "cancel" || o.state === "paid" || o.state === "done") {
                return false;
            }
            const status = this.kitchenStatusByToken?.[o.access_token];
            if (status && (status.is_served_done || status.summary_state === "completed" || status.is_cancelled || !status.has_kitchen)) {
                return false;
            }
            return true;
        });
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
        const seenIds = new Set();
        const payload = [];
        for (const o of activeOrders) {
            if (!seenIds.has(o.id)) {
                seenIds.add(o.id);
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
            }
        } catch {
            // Transient network error: keep last shown kitchen stage and let next poll/WS recover.
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
        if (!this._kitchenTrackingTimer) {
            this._kitchenTrackingTimer = setInterval(() => {
                if (this._kitchenTrackingCount > 0) {
                    this.fetchKitchenStatus();
                } else if (this._kitchenTrackingTimer) {
                    clearInterval(this._kitchenTrackingTimer);
                    this._kitchenTrackingTimer = null;
                }
            }, 3500);
        }
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
        onMounted(() => {
            if (this.selfOrder.config?.self_ordering_mode === "mobile") {
                const active = this.activeOrder;
                if (active) {
                    this._historyKitchenStarted = true;
                    this.selfOrder.startKitchenTracking([active]);
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

    isOrderActive(order) {
        if (!order || !order.access_token) {
            return false;
        }
        if (order.state === "cancel" || order.state === "paid" || order.state === "done") {
            return false;
        }
        const status = this.selfOrder.kitchenStatusByToken?.[order.access_token];
        if (status) {
            if (status.is_cancelled || status.is_served_done || status.summary_state === "completed" || !status.has_kitchen) {
                return false;
            }
            return true;
        }
        return order.state === "draft" && Boolean(order.isSynced);
    },

    get allOrders() {
        return this.selfOrder.models["pos.order"]
            .filter((o) => o && o.access_token)
            .sort((a, b) => (b.id || 0) - (a.id || 0));
    },

    get activeOrder() {
        const cur = this.selfOrder.currentOrder;
        if (cur && cur.access_token && this.isOrderActive(cur)) {
            return cur;
        }
        return this.allOrders.find((o) => this.isOrderActive(o)) || null;
    },

    get currentOrderAccessToken() {
        return this.activeOrder?.access_token || null;
    },

    get orders() {
        // Return strictly previous orders for the default list below
        const activeToken = this.currentOrderAccessToken;
        if (!activeToken) {
            return this.allOrders;
        }
        return this.allOrders.filter((o) => o.access_token !== activeToken);
    },

    get hasAnyOrders() {
        return this.allOrders.length > 0;
    },

    get hasNoOrders() {
        return this.allOrders.length === 0;
    },

    editOrder(order) {
        // Do nothing when clicking order header or status pill - user requested not clickable
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
        if (!order || !order.isSynced || !order.access_token) return false;
        if (order.state === "cancel" || order.state === "paid" || order.state === "done") {
            return false;
        }
        const status = this.selfOrder.kitchenStatusByToken?.[order.access_token];
        if (status && (status.is_served_done || status.summary_state === "completed" || status.is_cancelled || !status.has_kitchen)) {
            return false;
        }
        return Boolean(
            this.selfOrder.config?.self_ordering_mode === "mobile" &&
            !this.isCheckout
        );
    },

    get hasDraftLines() {
        const order = this.selfOrder.currentOrder;
        if (!order) return false;
        const changesCount = Object.keys(order.changes || {}).length;
        const unsentCount = (order.unsentLines || []).length;
        return changesCount > 0 || unsentCount > 0;
    },

    get showOrderBox() {
        if (!this.showKitchenStatusBanner) {
            return true;
        }
        return this.hasDraftLines;
    },

    openMyOrders() {
        this.router.navigate("orderHistory");
    },

    get orderNote() {
        if (this.selfOrder?.currentOrder?.unsentLines?.length > 0) {
            return this.state?.orderNoteValue || "";
        }
        return this.selfOrder?.currentOrder?.general_customer_note || this.state?.orderNoteValue || "";
    },

    async pay() {
        const noteText = (this.state?.orderNoteValue || "").trim();
        if (this.selfOrder?.currentOrder && noteText) {
            this.selfOrder.currentOrder.general_customer_note = noteText;
        }
        await super.pay(...arguments);
        if (this.state) {
            this.state.orderNoteValue = "";
        }
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

    async initOrder() {
        await super.initOrder(...arguments);
        if (this.selfOrder.config?.self_ordering_mode === "mobile" && this.confirmedOrder?.access_token) {
            await this.selfOrder.fetchKitchenStatus([this.confirmedOrder]);
        }
    },

    get showMobileKitchenStatus() {
        const order = this.confirmedOrder;
        if (!order || !order.access_token) return false;
        if (order.state === "cancel" || order.state === "paid" || order.state === "done") {
            return false;
        }
        return Boolean(
            this.selfOrder.config?.self_ordering_mode === "mobile"
        );
    },

    openMyOrders() {
        this.router.navigate("orderHistory");
    },
});
