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

    _isNonKitchenLine(line, productObj = null) {
        if (!line) return true;
        const product = productObj || (line.get_product ? line.get_product() : (line.product_id || line.product));
        if (!product) return true;

        const qty =
            typeof line.getQuantity === "function"
                ? line.getQuantity()
                : (typeof line.get_quantity === "function" ? line.get_quantity() : (line.qty ?? 0));
        if (qty <= 0) return true;

        // Exclude loyalty discount / eWallet / gift-card reward lines (keep free product rewards)
        if (line.is_reward_line && line.reward_id?.reward_type !== "product") {
            return true;
        }
        // Exclude gift card / eWallet top-up trigger lines and payment-program card lines
        if (line.payment_program_id || line.gift_card_vals) {
            return true;
        }
        if (typeof line.isTipLine === "function" && line.isTipLine()) {
            return true;
        }
        if (typeof line.isServiceFeeLine === "function" && line.isServiceFeeLine()) {
            return true;
        }

        const config = this.config || (this.pos && this.pos.config) || false;
        const tipProdId = config?.tip_product_id?.id ?? config?.tip_product_id;
        const discProdId = config?.discount_product_id?.id ?? config?.discount_product_id;
        const downPayProdId = config?.down_payment_product_id?.id ?? config?.down_payment_product_id;
        const serviceFeeProdId = this.preset_id?.service_fee_product_id?.id ?? this.preset_id?.service_fee_product_id;
        const deliveryFeeProdId = config?.self_ordering_delivery_fee_product_id?.id ?? config?.self_ordering_delivery_fee_product_id;

        if (
            (tipProdId && product.id === tipProdId) ||
            (discProdId && product.id === discProdId) ||
            (downPayProdId && product.id === downPayProdId) ||
            (serviceFeeProdId && product.id === serviceFeeProdId) ||
            (deliveryFeeProdId && product.id === deliveryFeeProdId)
        ) {
            return true;
        }

        const presetModel = this.models?.["pos.preset"] || this.pos?.models?.["pos.preset"];
        if (presetModel && typeof presetModel.getAll === "function") {
            for (const preset of presetModel.getAll()) {
                const sfProdId = preset.service_fee_product_id?.id ?? preset.service_fee_product_id;
                if (sfProdId && product.id === sfProdId) {
                    return true;
                }
            }
        }

        const rewardModel = this.models?.["loyalty.reward"] || this.pos?.models?.["loyalty.reward"];
        if (rewardModel && typeof rewardModel.getAll === "function") {
            for (const reward of rewardModel.getAll()) {
                const discLineProdId = reward.discount_line_product_id?.id ?? reward.discount_line_product_id;
                if (discLineProdId && product.id === discLineProdId) {
                    return true;
                }
            }
        }

        const programModel = this.models?.["loyalty.program"] || this.pos?.models?.["loyalty.program"];
        if (programModel && typeof programModel.getAll === "function") {
            for (const prog of programModel.getAll()) {
                if (["gift_card", "ewallet"].includes(prog.program_type) && prog.trigger_product_ids) {
                    for (const trigProd of prog.trigger_product_ids) {
                        if ((trigProd?.id ?? trigProd) === product.id) {
                            return true;
                        }
                    }
                }
            }
        }

        const unitPrice =
            typeof line.getUnitPrice === "function"
                ? line.getUnitPrice()
                : (typeof line.get_unit_price === "function" ? line.get_unit_price() : (line.price_unit ?? 0));
        const priceIncl = line.priceIncl ?? line.price_subtotal_incl;
        if (unitPrice < 0 || (typeof priceIncl === "number" && priceIncl < 0)) {
            return true;
        }

        return false;
    },

    get preparationChanges() {
        const changes = super.preparationChanges;
        if (!changes) return changes;

        const filterChangeList = (list) => {
            if (!Array.isArray(list) || list.length === 0) return { kept: list || [], removedCount: 0, removedByCat: {} };
            const kept = [];
            let removedCount = 0;
            const removedByCat = {};
            for (const item of list) {
                const line = item?.line;
                if (line && this._isNonKitchenLine(line)) {
                    if (typeof line.setHasChange === "function") {
                        line.setHasChange(false);
                    }
                    const qty = Math.abs(item?.data?.quantity ?? item?.quantity ?? 0);
                    removedCount += qty;
                    const product = line.get_product ? line.get_product() : (line.product_id || line.product);
                    const categ = product?.pos_categ_ids?.find((c) => this.preparationCategories.has(c.id));
                    if (categ) {
                        removedByCat[categ.id] = (removedByCat[categ.id] || 0) + qty;
                    }
                } else {
                    kept.push(item);
                }
            }
            return { kept, removedCount, removedByCat };
        };

        const addRes = filterChangeList(changes.addedQuantity);
        const remRes = filterChangeList(changes.removedQuantity);
        const noteRes = filterChangeList(changes.noteUpdate);

        if (addRes.removedCount > 0 || remRes.removedCount > 0 || (changes.noteUpdate && noteRes.kept.length !== changes.noteUpdate.length)) {
            changes.addedQuantity = addRes.kept;
            changes.removedQuantity = remRes.kept;
            changes.noteUpdate = noteRes.kept;
            changes.quantity = Math.max(0, (changes.quantity || 0) - addRes.removedCount - remRes.removedCount);

            if (Array.isArray(changes.categoryCount)) {
                const validLines = [...addRes.kept, ...remRes.kept];
                const catCounts = {};
                for (const item of validLines) {
                    const line = item?.line;
                    const product = line?.get_product ? line.get_product() : (line?.product_id || line?.product);
                    const categ = product?.pos_categ_ids?.find((c) => this.preparationCategories.has(c.id));
                    if (categ && !line?.combo_line_ids?.length) {
                        if (!catCounts[categ.id]) {
                            catCounts[categ.id] = { name: categ.name, count: 0 };
                        }
                        catCounts[categ.id].count += item?.data?.quantity ?? 0;
                    }
                }
                const preservedMeta = changes.categoryCount.filter(
                    (c) => c && (c.name === "Note" || c.name === "Message")
                );
                changes.categoryCount = [...Object.values(catCounts).filter((c) => c.count !== 0), ...preservedMeta];
            }
        }

        // Ensure categoryCount is populated if there are unprinted/unprepared kitchen lines without POS category
        const catCountList = Array.isArray(changes.categoryCount) ? changes.categoryCount : Object.values(changes.categoryCount || {});
        if (catCountList.length === 0) {
            let uncounted = 0;
            const lines = this.lines || (this.get_orderlines ? this.get_orderlines() : []);
            for (const line of lines) {
                if (this._isNonKitchenLine(line)) {
                    if (typeof line.setHasChange === "function") {
                        line.setHasChange(false);
                    }
                    continue;
                }
                const qty =
                    typeof line.getQuantity === "function"
                        ? line.getQuantity()
                        : (typeof line.get_quantity === "function" ? line.get_quantity() : (line.qty || 0));
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
            const qty =
                typeof line.getQuantity === "function"
                    ? line.getQuantity()
                    : (typeof line.get_quantity === "function" ? line.get_quantity() : (line.qty || 1));
            if (this._isNonKitchenLine(line, product)) {
                line._kitchen_sent_qty = qty;
                line.prepQty = qty;
                if ("mp_dirty" in line) line.mp_dirty = false;
                continue;
            }
            const note =
                typeof line.getCustomerNote === "function"
                    ? line.getCustomerNote()
                    : (typeof line.get_customer_note === "function" ? line.get_customer_note() : (line.customer_note || line.note || ""));
            const name =
                typeof line.getFullProductName === "function"
                    ? line.getFullProductName()
                    : (typeof line.get_full_product_name === "function" ? line.get_full_product_name() : (product.display_name || product.name || "Item"));
            const courseName =
                line.course?.name ||
                line.course_id?.name ||
                (typeof line.getCourseName === "function" ? line.getCourseName() : "") ||
                (typeof line.get_course_name === "function" ? line.get_course_name() : "") ||
                "";
            const unitPrice =
                typeof line.getUnitPrice === "function"
                    ? line.getUnitPrice()
                    : (typeof line.get_unit_price === "function" ? line.get_unit_price() : (line.price_unit ?? 0));

            orderLinesData.push({
                product_id: product.id,
                name: name,
                qty: qty,
                note: note,
                course_name: courseName,
                is_reward_line: Boolean(line.is_reward_line),
                reward_type: line.reward_id?.reward_type || "",
                is_tip_line: Boolean(typeof line.isTipLine === "function" ? line.isTipLine() : false),
                is_payment_program: Boolean(line.payment_program_id || line.gift_card_vals),
                price_unit: unitPrice,
            });
        }
        if (orderLinesData.length === 0) {
            this.isSendingToKitchen = false;
            return { ok: true, skipped: true, message: "No kitchen items to send" };
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
        const explicitConfigId = this.config_id ? (this.config_id.id || this.config_id) : false;
        const config = this.config || (this.pos && this.pos.config) || (this.models && this.models["pos.config"] && typeof odoo !== "undefined" ? this.models["pos.config"].get(odoo.pos_config_id) : false);
        const configId = explicitConfigId || (config && config.id) || (typeof odoo !== "undefined" ? odoo.pos_config_id : false) || false;

        const explicitSessionId = this.session_id ? (this.session_id.id || this.session_id) : false;
        const session = this.session || this.session_id || (this.pos ? (this.pos.pos_session || this.pos.session) : false) || (this.models && this.models["pos.session"] && typeof odoo !== "undefined" ? this.models["pos.session"].get(odoo.pos_session_id) : false);
        const sessionId = explicitSessionId || (session && session.id) || (typeof odoo !== "undefined" ? odoo.pos_session_id : false) || false;

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
                    const qty =
                        typeof line.getQuantity === "function"
                            ? line.getQuantity()
                            : (typeof line.get_quantity === "function" ? line.get_quantity() : (line.qty || 1));
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
