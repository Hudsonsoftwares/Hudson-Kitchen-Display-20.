/** @odoo-module */

import { PosConfig } from "@point_of_sale/app/models/pos_config";
import { patch } from "@web/core/utils/patch";

patch(PosConfig.prototype, {
    get preparationCategories() {
        const set = super.preparationCategories ? new Set(super.preparationCategories) : new Set();
        // In POS Community with Kitchen Display, hardware printers are not required.
        // Include all categories so products are tracked for kitchen preparation changes.
        const categories = this.models ? this.models["pos.category"] : false;
        if (categories && typeof categories.getAll === "function") {
            for (const cat of categories.getAll()) {
                set.add(cat.id);
            }
        }
        return set;
    },
});
