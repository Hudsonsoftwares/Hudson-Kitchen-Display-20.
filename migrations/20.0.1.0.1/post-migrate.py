# -*- coding: utf-8 -*-
import logging
from odoo import api, SUPERUSER_ID
from odoo.addons.hudson_kitchen_display.utils import get_non_kitchen_product_ids, is_non_kitchen_line

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Remove non-kitchen billing/discount/tip lines from existing kitchen orders."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'pos.kitchen.order.line' not in env or 'pos.kitchen.order' not in env:
        return

    KitchenOrder = env['pos.kitchen.order'].sudo().with_context(active_test=False)
    KitchenLine = env['pos.kitchen.order.line'].sudo().with_context(active_test=False)
    StageLog = env['pos.kitchen.order.stage.log'].sudo() if 'pos.kitchen.order.stage.log' in env else False

    non_kitchen_pids = get_non_kitchen_product_ids(env)
    lines_to_remove = KitchenLine.search([('product_id', 'in', list(non_kitchen_pids))]) if non_kitchen_pids else KitchenLine.browse()

    # Also check linked pos.order lines for reward/negative/fee lines not directly in non_kitchen_pids
    remaining_lines = KitchenLine.search([('id', 'not in', lines_to_remove.ids)]) if lines_to_remove else KitchenLine.search([])
    extra_ids = []
    for kline in remaining_lines:
        pos_order = kline.prep_order_id.pos_order_id
        if not pos_order:
            continue
        matching_pols = pos_order.lines.filtered(lambda l: l.product_id.id == kline.product_id.id)
        if matching_pols and all(
            is_non_kitchen_line(
                env,
                line=pol,
                non_kitchen_product_ids=non_kitchen_pids,
                config=pos_order.config_id,
                order=pos_order,
            )
            for pol in matching_pols
        ):
            extra_ids.append(kline.id)

    if extra_ids:
        lines_to_remove |= KitchenLine.browse(extra_ids)

    if not lines_to_remove:
        return

    affected_order_ids = lines_to_remove.mapped('prep_order_id').ids
    removed_count = len(lines_to_remove)
    lines_to_remove.unlink()

    empty_orders = KitchenOrder.browse(affected_order_ids).exists().filtered(lambda o: not o.line_ids)
    if empty_orders:
        if StageLog:
            StageLog.search([('prep_order_id', 'in', empty_orders.ids)]).unlink()
        empty_orders.unlink()

    _logger.info(
        "Hudson Kitchen Display: Removed %d non-kitchen line(s) and %d empty ticket(s).",
        removed_count,
        len(empty_orders),
    )

