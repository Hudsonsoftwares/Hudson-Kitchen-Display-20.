/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async sendOrderInPreparation(order, opts = {}) {
        try {
            if (order && typeof order.sendToKitchen === "function") {
                await order.sendToKitchen();
            }
        } catch (err) {
            console.error("Error sending order to kitchen display:", err);
        }
        return await super.sendOrderInPreparation(...arguments);
    },
});
