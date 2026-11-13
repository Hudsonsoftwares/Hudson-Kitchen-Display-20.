import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";

/**
 * Ensure the Course button is always displayed on the POS interface
 * in Restaurant & Cafe mode, allowing users to manually create Course 1, Course 2,
 * etc. and assign food items to each course.
 */
patch(ControlButtons.prototype, {
    get showAddCourse() {
        return (
            this.pos.config.module_pos_restaurant &&
            !this.props.showRemainingButtons &&
            !this.pos.getOrder()?.isRefund
        );
    },
});

