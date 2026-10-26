import uuid

from odoo import models, fields, api
from ..utils import get_pos_categories, get_fulfillment_type, get_line_note, get_table_number


class PosOrder(models.Model):
    _inherit = 'pos.order'

    kitchen_order_ids = fields.One2many('pos.kitchen.order', 'pos_order_id', string='Kitchen Orders')
    kitchen_order_count = fields.Integer(compute='_compute_kitchen_order_count', string='Kitchen Orders Count')
    kitchen_access_token = fields.Char(default=lambda self: str(uuid.uuid4()), copy=False)

    def _compute_kitchen_order_count(self):
        for order in self:
            count = len(order.kitchen_order_ids)
            if not count and order.pos_reference:
                count = self.env['pos.kitchen.order'].sudo().search_count([('pos_reference', '=', order.pos_reference)])
            order.kitchen_order_count = count

    def action_view_kitchen_orders(self):
        self.ensure_one()
        domain = ['|', ('pos_order_id', '=', self.id), ('pos_reference', '=', self.pos_reference)] if self.pos_reference else [('pos_order_id', '=', self.id)]
        return {
            'name': 'Kitchen Orders',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.kitchen.order',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'default_pos_order_id': self.id, 'default_pos_reference': self.pos_reference},
        }

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._send_to_kitchen_displays()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if 'lines' in vals or 'state' in vals:
            self._send_to_kitchen_displays(force=True)
        return res

    def action_manual_send_to_kitchen(self):
        """Manual re-send: pushes any order lines that haven't reached a
        display yet (e.g. items added after the initial send, or a kiosk/
        self-order flow that bypassed the normal create hook). Safe to call
        repeatedly - it never duplicates a line that's already on a display."""
        for order in self:
            order._send_to_kitchen_displays(force=True)
        return True

    def _send_to_kitchen_displays(self, force=False, lines_data=None):
        PrepDisplay = self.env['pos.prep.display'].sudo()
        for order in self:
            config = order.config_id if ('config_id' in order._fields and order.config_id) else (order.session_id.config_id if ('session_id' in order._fields and order.session_id) else False)
            company = order.company_id or (config.company_id if config and config.company_id else self.env.company)
            display_domain = [('company_id', '=', company.id)]
            if config:
                display_domain.extend(['|', ('pos_config_ids', '=', False), ('pos_config_ids', 'in', config.id)])
            displays = PrepDisplay.search(display_domain)
            if not displays:
                displays = PrepDisplay.search([('company_id', '=', company.id)])
            if not displays:
                continue

            table = order.table_id if 'table_id' in order._fields else False
            num = get_table_number(table)
            if num is not False and num is not None and str(num).strip():
                tbl_name = f"T{num}" if str(num).isdigit() else str(num)
            else:
                tbl_name = order.pos_reference.split()[-1] if order.pos_reference else ''
            cust_count = getattr(order, 'customer_count', 0) or getattr(table, 'seats', 0) or 1
            fulfillment = get_fulfillment_type(order)

            # Link any existing unlinked prep orders matching this order
            # Match by: uuid, tracking_number, or pos_reference
            match_conds = []
            if getattr(order, 'uuid', False):
                match_conds.append(('order_uid', '=', order.uuid))
            if order.pos_reference and order.pos_reference != '/':
                match_conds.append(('pos_reference', '=', order.pos_reference))
            if getattr(order, 'tracking_number', False):
                match_conds.append(('pos_reference', '=', f"Order {order.tracking_number}"))
                match_conds.append(('pos_reference', '=', str(order.tracking_number)))

            if match_conds:
                unlinked_domain = [
                    ('pos_order_id', '=', False),
                    ('company_id', '=', company.id),
                ]
                if len(match_conds) > 1:
                    unlinked_domain += ['|'] * (len(match_conds) - 1)
                unlinked_domain += match_conds
                unlinked_preps = self.env['pos.kitchen.order'].sudo().search(unlinked_domain)
                if unlinked_preps:
                    unlinked_preps.write({
                        'pos_order_id': order.id,
                        'pos_reference': order.pos_reference,
                        'fulfillment_type': fulfillment,
                        'table_name': tbl_name if tbl_name else (unlinked_preps[0].table_name or ''),
                    })

            # Invalidate cached relations on order
            order.invalidate_recordset(['kitchen_order_ids'])

            # Find all existing prep orders for this order, across pos_order_id, order_uid, or pos_reference
            find_conds = [('pos_order_id', '=', order.id)]
            if getattr(order, 'uuid', False):
                find_conds.append(('order_uid', '=', order.uuid))
            if order.pos_reference and order.pos_reference != '/':
                find_conds.append(('pos_reference', '=', order.pos_reference))
            if getattr(order, 'tracking_number', False):
                find_conds.append(('pos_reference', '=', f"Order {order.tracking_number}"))
                find_conds.append(('pos_reference', '=', str(order.tracking_number)))

            existing_domain = [('company_id', '=', company.id)]
            if len(find_conds) > 1:
                existing_domain += ['|'] * (len(find_conds) - 1)
            existing_domain += find_conds
            existing_preps = self.env['pos.kitchen.order'].sudo().search(existing_domain)

            # Link any unlinked preps found
            unlinked = existing_preps.filtered(lambda p: not p.pos_order_id)
            if unlinked:
                unlinked.write({
                    'pos_order_id': order.id,
                    'pos_reference': order.pos_reference,
                    'fulfillment_type': fulfillment,
                    'table_name': tbl_name if tbl_name else (unlinked[0].table_name or ''),
                })

            sent_qty_per_product = {}
            for prep in existing_preps:
                for pl in prep.line_ids:
                    pid = pl.product_id.id
                    sent_qty_per_product[pid] = sent_qty_per_product.get(pid, 0.0) + pl.qty

            for display in displays:
                lines = []
                if lines_data:
                    for ldata in lines_data:
                        pid = ldata.get('product_id')
                        qty = float(ldata.get('qty', 1))
                        sent_qty = sent_qty_per_product.get(pid, 0.0)
                        qty_to_send = qty - sent_qty
                        if qty_to_send <= 0:
                            continue
                        product = self.env['product.product'].sudo().browse(pid)
                        if not product.exists():
                            continue
                        categs = get_pos_categories(product)
                        if display.category_ids and not (display.category_ids & categs):
                            continue
                        lines.append((0, 0, {
                            'product_id': pid,
                            'name': ldata.get('name') or product.display_name,
                            'qty': qty_to_send,
                            'note': ldata.get('note', '') or '',
                        }))
                        sent_qty_per_product[pid] = sent_qty + qty_to_send
                else:
                    for line in order.lines:
                        pid = line.product_id.id
                        sent_qty = sent_qty_per_product.get(pid, 0.0)
                        qty_to_send = line.qty - sent_qty
                        if qty_to_send <= 0:
                            continue
                        categs = get_pos_categories(line.product_id)
                        if display.category_ids and not (display.category_ids & categs):
                            continue
                        product_name = getattr(line, 'full_product_name', False) or line.product_id.display_name or getattr(line, 'name', 'Item')
                        lines.append((0, 0, {
                            'product_id': pid,
                            'name': product_name,
                            'qty': qty_to_send,
                            'note': get_line_note(line),
                        }))
                        sent_qty_per_product[pid] = sent_qty + qty_to_send

                if not lines:
                    continue
                first_stage = display.stage_ids.sorted('sequence')[:1]
                if not first_stage:
                    continue
                prep_order = self.env['pos.kitchen.order'].sudo().create({
                    'pos_order_id': order.id,
                    'pos_reference': order.pos_reference,
                    'order_uid': getattr(order, 'uuid', False) or False,
                    'config_id': config.id if config else False,
                    'session_id': order.session_id.id if 'session_id' in order._fields and order.session_id else False,
                    'company_id': company.id,
                    'display_id': display.id,
                    'stage_id': first_stage.id,
                    'fulfillment_type': fulfillment,
                    'table_name': tbl_name,
                    'customer_count': cust_count,
                    'line_ids': lines,
                })
                prep_order._notify_display()
