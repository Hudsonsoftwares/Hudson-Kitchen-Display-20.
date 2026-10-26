/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setup() {
        super.setup(...arguments);
        this.kitchenSentQty = this.kitchenSentQty || {};
        this.isSendingToKitchen = false;
    },

    get preparationCategories() {
        const set = super.preparationCategories ? new Set(super.preparationCategories) : new Set();
        const categories = this.models ? this.models["pos.category"] : (this.pos && this.pos.models ? this.pos.models["pos.category"] : false);
        if (categories && typeof categories.getAll === "function") {
            for (const cat of categories.getAll()) {
                set.add(cat.id);
            }
        }
        return set;
    },

    get preparationChanges() {
        const changes = super.preparationChanges;
        if (!changes) return changes;

        // Ensure categoryCount is populated if there are unprinted/unprepared lines
        const catCountList = Array.isArray(changes.categoryCount) ? changes.categoryCount : Object.values(changes.categoryCount || {});
        if (catCountList.length === 0) {
            let uncounted = 0;
            const lines = this.lines || (this.get_orderlines ? this.get_orderlines() : []);
            for (const line of lines) {
                const qty = typeof line.get_quantity === "function" ? line.get_quantity() : (line.qty || 0);
                const prepQty = line.prepQty || 0;
                const diff = qty - prepQty;
                if (diff > 0) {
                    uncounted += diff;
                }
            }
            if (uncounted > 0) {
                const item = { name: "Food", count: uncounted };
                if (Array.isArray(changes.categoryCount)) {
                    changes.categoryCount.push(item);
                } else if (typeof changes.categoryCount === "object" && changes.categoryCount !== null) {
                    changes.categoryCount["food"] = item;
                }
                changes.quantity = (changes.quantity || 0) + uncounted;
            }
        }
        return changes;
    },

    async sendToKitchen() {
        if (this.isSendingToKitchen) {
            return { ok: false, message: "Order is already being sent" };
        }
        this.isSendingToKitchen = true;
        const lines = this.get_orderlines ? this.get_orderlines() : (this.lines || []);
        if (!lines || lines.length === 0) {
            this.isSendingToKitchen = false;
            return { ok: false, message: "Order is empty - please add items first" };
        }

        const orderLinesData = [];
        for (const line of lines) {
            const product = line.get_product ? line.get_product() : (line.product_id || line.product);
            if (!product) continue;
            const qty = typeof line.get_quantity === "function" ? line.get_quantity() : (line.qty || 1);
            const note = typeof line.get_customer_note === "function" ? line.get_customer_note() : (line.customer_note || line.note || "");
            const name = typeof line.get_full_product_name === "function" ? line.get_full_product_name() : (product.display_name || product.name || "Item");

            orderLinesData.push({
                product_id: product.id,
                name: name,
                qty: qty,
                note: note,
            });
        }

        let tableName = "";
        let tableId = false;
        const table = this.table || this.table_id || (typeof this.getTable === "function" ? this.getTable() : false);
        if (table) {
            tableId = typeof table === "object" ? table.id : (Array.isArray(table) ? table[0] : table);
            if (typeof table === "object") {
                tableName = (table.table_number !== undefined && table.table_number !== null && table.table_number !== 0) ? String(table.table_number) : (table.name || "");
            } else if (Array.isArray(table)) {
                tableName = table[1] || "";
            }
        }

        const customerCount = typeof this.get_customer_count === "function" ? this.get_customer_count() : (this.customer_count || (typeof this.getCustomerCount === "function" ? this.getCustomerCount() : 1));

        let fulfillment = "dine_in";
        if (tableId || tableName) {
            fulfillment = "dine_in";
        } else if (this.takeaway || this.is_takeaway) {
            fulfillment = "takeout";
        } else if (this.is_delivery_order || this.delivery_platform_id) {
            fulfillment = "delivery";
        } else {
            fulfillment = "dine_in";
        }

        let posReference = this.name || this.pos_reference || "";
        if (!posReference || posReference === "/") {
            if (this.tracking_number) {
                posReference = `Order ${this.tracking_number}`;
            } else if (this.floating_order_name) {
                posReference = this.floating_order_name;
            } else if (tableName) {
                posReference = `Table ${tableName}`;
            } else if (this.uuid) {
                posReference = `Draft-${this.uuid.slice(-6)}`;
            } else {
                posReference = "/";
            }
        }

        const serverId = (this.server_id && typeof this.server_id === "number") ? this.server_id : ((this.backendId && typeof this.backendId === "number") ? this.backendId : false);

        // Robust resolution across Odoo 20 / 18 / 17
        const config = this.config || (this.pos && this.pos.config) || (this.models && this.models["pos.config"] && typeof odoo !== "undefined" ? this.models["pos.config"].get(odoo.pos_config_id) : false);
        const configId = (config && config.id) || (this.config_id ? (this.config_id.id || this.config_id) : false) || (typeof odoo !== "undefined" ? odoo.pos_config_id : false) || false;

        const session = this.session || this.session_id || (this.pos ? (this.pos.pos_session || this.pos.session) : false) || (this.models && this.models["pos.session"] && typeof odoo !== "undefined" ? this.models["pos.session"].get(odoo.pos_session_id) : false);
        const sessionId = (session && session.id) || (typeof odoo !== "undefined" ? odoo.pos_session_id : false) || false;

        const company = this.company || (config && config.company_id) || (session && session.company_id) || false;
        const companyId = company ? (typeof company === "object" ? company.id : company) : false;

        const payload = {
            pos_reference: posReference,
            server_id: serverId,
            session_id: sessionId,
            config_id: configId,
            company_id: companyId,
            order_uid: this.uuid || "",
            table_name: tableName,
            table_id: tableId,
            customer_count: customerCount,
            fulfillment_type: fulfillment,
            lines: orderLinesData,
        };
        try {
            const res = await fetch("/hudson_kitchen_display/send_to_kitchen", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "call",
                    params: { order_data: payload },
                    id: Date.now(),
                }),
            });
            const data = await res.json();
            if (data.result && data.result.ok) {
                if (data.result.pos_order_id) {
                    this.server_id = data.result.pos_order_id;
                    this.backendId = data.result.pos_order_id;
                }
                for (const line of lines) {
                    const qty = typeof line.get_quantity === "function" ? line.get_quantity() : (line.qty || 1);
                    line._kitchen_sent_qty = qty;
                    line.prepQty = qty;
                    line.kitchen_sent = true;
                    if ("mp_dirty" in line) line.mp_dirty = false;
                }
                return { ok: true, message: data.result.message || "Order sent to kitchen!" };
            } else {
                return { ok: false, message: (data.result && data.result.message) || (data.error && data.error.message) || "Failed to send order" };
            }
        } catch (e) {
            console.error("Error sending order to kitchen:", e);
            return { ok: false, message: "Connection error while sending to kitchen" };
        } finally {
            this.isSendingToKitchen = false;
        }
    }
});
