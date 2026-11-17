import uuid

from odoo import models, fields, api
from odoo.exceptions import UserError
from ..utils import (
    get_pos_categories,
    get_fulfillment_type,
    get_line_note,
    get_table_number,
    get_non_kitchen_product_ids,
    is_non_kitchen_line,
)


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
        if vals.get('state') == 'cancel':
            self._cancel_kitchen_orders()
        elif 'lines' in vals:
            self._send_to_kitchen_displays(force=True)
        elif 'state' in vals:
            self._send_to_kitchen_displays(force=True, skip_new_displays=True)
        return res

    def _check_combo_lines(self):
        """Auto-heal and sanitize combo parent/child links to prevent 'Invalid combo line'
        UserError when self-order routes recompute prices on open orders."""
        for line in self.lines:
            parent = line.combo_parent_id
            combo_item = line.combo_item_id

            # Case 1: combo_item is set on a standalone item without combo_parent_id
            if combo_item and not parent:
                line.combo_item_id = False
                combo_item = False

            # Case 2: parent is set without combo_item
            if parent and not combo_item:
                found_item = False
                for combo in parent.product_id.combo_ids:
                    matching = combo.combo_item_ids.filtered(lambda i: i.product_id == line.product_id)
                    if matching:
                        line.combo_item_id = matching[0].id
                        combo_item = matching[0]
                        found_item = True
                        break
                if not found_item:
                    line.combo_parent_id = False
                    parent = False

            # Case 3: parent belongs to another order or parent product is not a combo
            if parent and (parent.order_id != self or parent.product_id.type != 'combo'):
                line.combo_parent_id = False
                line.combo_item_id = False
                parent = False
                combo_item = False

            # Case 4: combo_item does not match parent's combo_ids or line's product
            if parent and combo_item:
                if combo_item.combo_id not in parent.product_id.combo_ids or combo_item.product_id != line.product_id:
                    found = False
                    for combo in parent.product_id.combo_ids:
                        matching = combo.combo_item_ids.filtered(lambda i: i.product_id == line.product_id)
                        if matching:
                            line.combo_item_id = matching[0].id
                            found = True
                            break
                    if not found:
                        line.combo_parent_id = False
                        line.combo_item_id = False

            # Case 5: child in combo_line_ids points to wrong parent or order
            for child in line.combo_line_ids:
                if child.order_id != self or child.combo_parent_id != line:
                    child.combo_parent_id = False

        try:
            return super()._check_combo_lines()
        except UserError:
            # Fallback: detach any non-conforming combo linkages so order completes safely
            for line in self.lines:
                if line.combo_parent_id and (
                    line.combo_parent_id.order_id != self
                    or line.combo_parent_id.product_id.type != 'combo'
                    or not line.combo_item_id
                    or line.combo_item_id.combo_id not in line.combo_parent_id.product_id.combo_ids
                    or line.combo_item_id.product_id != line.product_id
                ):
                    line.combo_parent_id = False
                    line.combo_item_id = False
                for child in line.combo_line_ids:
                    if child.order_id != self or child.combo_parent_id != line:
                        child.combo_parent_id = False
            return super()._check_combo_lines()

    def _cancel_kitchen_orders(self):
        KitchenOrder = self.env['pos.kitchen.order'].sudo().with_context(active_test=False)
        for order in self:
            company = order.company_id or (
                order.config_id.company_id if order.config_id and order.config_id.company_id else self.env.company
            )
            conds = [('pos_order_id', '=', order.id)]
            if getattr(order, 'uuid', False):
                conds.append(('order_uid', '=', order.uuid))
            domain = [('company_id', '=', company.id), ('active', '=', True)]
            if len(conds) > 1:
                domain += ['|'] + conds
            else:
                domain += conds
            active_tickets = KitchenOrder.search(domain)
            if active_tickets:
                active_tickets.write({'active': False})
                active_tickets._notify_display()
            elif order.config_id and getattr(order.config_id, 'self_ordering_mode', False) in ('mobile', 'kiosk'):
                if hasattr(order.config_id, '_notify'):
                    try:
                        order.config_id._notify('KITCHEN_STATUS_CHANGED', {})
                    except Exception:
                        pass

    def _get_self_order_kitchen_status(self):
        """Return strictly scoped Kitchen Display 3-stage progress for this single POS order."""
        self.ensure_one()
        finalized_payload = {
            'order_id': self.id,
            'order_access_token': self.access_token or '',
            'is_cancelled': (self.state == 'cancel'),
            'has_kitchen': False,
            'summary_state': 'cancelled' if self.state == 'cancel' else 'completed',
            'summary_label': 'Cancelled' if self.state == 'cancel' else 'Completed',
            'is_served_done': self.state != 'cancel',
            'displays': [],
            'batches': [],
            'categories': [],
        }
        if self.state == 'cancel':
            return finalized_payload
        # Paid/done orders can still be cooking (pay-first self ordering), so their
        # kitchen tickets decide whether they are still active.
        is_finalized = self.state in ('paid', 'done')

        company = self.company_id or (
            self.config_id.company_id if self.config_id and self.config_id.company_id else self.env.company
        )
        KitchenOrder = self.env['pos.kitchen.order'].sudo().with_context(active_test=False)
        conds = [('pos_order_id', '=', self.id)]
        if getattr(self, 'uuid', False):
            conds.append(('order_uid', '=', self.uuid))
        if self.pos_reference and self.pos_reference != '/':
            conds.append(('pos_reference', '=', self.pos_reference))
        domain = [
            ('company_id', '=', company.id),
            '|', ('pos_order_id', '=', self.id), ('pos_order_id', '=', False),
        ]
        if len(conds) > 1:
            domain += ['|'] * (len(conds) - 1) + conds
        else:
            domain += conds

        tickets = KitchenOrder.search(domain, order='display_id asc, id asc')
        # Extra guard: if unlinked fallback matched another config's order, keep only matching config when set
        if self.config_id:
            tickets = tickets.filtered(lambda t: not t.config_id or t.config_id.id == self.config_id.id)

        if not tickets and is_finalized:
            return finalized_payload
        if not tickets:
            config = self.config_id
            configured_displays = self.env['pos.prep.display'].sudo().search([
                ('company_id', '=', company.id),
                ('pos_config_ids', 'in', [config.id]),
            ], order='id asc') if config else self.env['pos.prep.display']
            non_kitchen_ids = get_non_kitchen_product_ids(self.env, config=config, order=self)
            kitchen_lines = [
                line for line in self.lines
                if not is_non_kitchen_line(
                    self.env,
                    line=line,
                    non_kitchen_product_ids=non_kitchen_ids,
                    config=config,
                    order=self,
                )
            ]
            if configured_displays and kitchen_lines:
                # Filter to displays whose configured POS Categories match at least one item in this order
                matching_displays = self.env['pos.prep.display']
                matched_lines = []
                for disp in configured_displays:
                    disp_lines = []
                    for line in kitchen_lines:
                        if not disp.category_ids:
                            disp_lines.append(line)
                        elif line.product_id and (disp.category_ids & get_pos_categories(line.product_id)):
                            disp_lines.append(line)
                    if disp_lines:
                        matching_displays |= disp
                        if not matched_lines:
                            matched_lines = disp_lines

                primary_disp = matching_displays[:1]
                stages = list(primary_disp.stage_ids.sorted('sequence')) if primary_disp else []
                if primary_disp and stages and matched_lines:
                    stage_items = [{
                        'id': st.id,
                        'name': st.name,
                        'sequence': st.sequence,
                        'color': st.color or '#C8C9CB',
                        'state': 'active' if idx == 0 else 'pending',
                    } for idx, st in enumerate(stages)]
                    cat_groups = {}
                    for line in matched_lines:
                        categs = get_pos_categories(line.product_id) if line.product_id else False
                        cat = categs[:1] if categs else False
                        cat_id = cat.id if cat else 0
                        cat_name = (cat.name or 'Other') if cat else 'Other'
                        grp = cat_groups.setdefault(cat_id, {
                            'category_id': cat_id,
                            'category_name': cat_name,
                            'total_qty': 0,
                            'done_count': 0,
                            'total_count': 0,
                            'lines': [],
                        })
                        qty_val = int(line.qty) if float(line.qty).is_integer() else line.qty
                        grp['total_qty'] += qty_val
                        grp['total_count'] += 1
                        grp['lines'].append({
                            'id': line.id,
                            'product_id': line.product_id.id if line.product_id else 0,
                            'name': getattr(line, 'full_product_name', False) or (line.product_id.display_name if line.product_id else 'Item'),
                            'qty': qty_val,
                            'note': get_line_note(line) or '',
                            'is_done': False,
                        })
                    categories_list = sorted(cat_groups.values(), key=lambda c: (c['category_id'] == 0, c['category_name']))
                    pos_ref = self.pos_reference or self.name or ''
                    tracking_num = self.tracking_number or ''
                    return {
                        'order_id': self.id,
                        'pos_reference': pos_ref,
                        'tracking_number': tracking_num,
                        'order_access_token': self.access_token or '',
                        'is_cancelled': False,
                        'has_kitchen': True,
                        'summary_state': 'in_progress',
                        'summary_label': stages[0].name,
                        'is_served_done': False,
                        'displays': [{
                            'display_id': primary_disp.id,
                            'display_name': primary_disp.name,
                            'current_stage_id': stages[0].id,
                            'current_stage_name': stages[0].name,
                            'current_stage_color': stages[0].color or '#C8C9CB',
                            'current_stage_index': 0,
                            'total_stages': len(stages),
                            'is_completed': False,
                            'is_served_done': False,
                            'stages': stage_items,
                        }],
                        'batches': [{
                            'ticket_id': 0,
                            'batch_number': 1,
                            'barcode': '',
                            'created_at': fields.Datetime.to_string(self.create_date) if self.create_date else '',
                            'display_id': primary_disp.id,
                            'display_name': primary_disp.name,
                            'current_stage_id': stages[0].id,
                            'current_stage_name': stages[0].name,
                            'current_stage_color': stages[0].color or '#C8C9CB',
                            'current_stage_index': 0,
                            'total_stages': len(stages),
                            'is_completed': False,
                            'is_served_done': False,
                            'title': pos_ref or _('Current Order'),
                            'pos_reference': pos_ref,
                            'tracking_number': tracking_num,
                            'kds_reference': f"#{tracking_num}" if tracking_num else pos_ref,
                            'stages': stage_items,
                            'categories': categories_list,
                        }],
                        'categories': [{
                            **cat,
                            'current_stage_name': stages[0].name,
                            'current_stage_index': 0,
                            'is_completed': False,
                            'is_served_done': False,
                            'stages': stage_items,
                        } for cat in categories_list],
                    }

            return {
                'order_id': self.id,
                'order_access_token': self.access_token or '',
                'is_cancelled': False,
                'has_kitchen': False,
                'summary_state': 'none',
                'summary_label': '',
                'is_served_done': False,
                'displays': [],
                'batches': [],
                'categories': [],
            }

        # Sort all tickets chronologically by creation date and id
        all_ordered_tickets = sorted(tickets, key=lambda t: (t.create_date or fields.Datetime.now(), t.id))
        if not all_ordered_tickets:
            return {
                'order_id': self.id,
                'order_access_token': self.access_token or '',
                'is_cancelled': False,
                'has_kitchen': False,
                'summary_state': 'none',
                'summary_label': '',
                'is_served_done': False,
                'displays': [],
                'batches': [],
                'categories': [],
            }

        def _is_ticket_completed(t):
            # A ticket is finished only when the kitchen pressed "Done" (which archives it).
            # Reaching the last stage ("Completed") alone keeps it visible on the guest's
            # phone - showing "Completed" - until Done is clicked on the KDS.
            return not t.active

        # Group tickets into distinct dining rounds based on send timestamp (<= 20s difference)
        rounds = []
        for t in all_ordered_tickets:
            if not rounds:
                rounds.append([t])
            else:
                prev_time = rounds[-1][-1].create_date
                if t.create_date and prev_time and abs((t.create_date - prev_time).total_seconds()) <= 20:
                    rounds[-1].append(t)
                else:
                    rounds.append([t])

        total_rounds = len(rounds)
        batches = []

        def _stage_items(stages, cur_idx, completed):
            items = []
            for s_idx, st in enumerate(stages):
                if completed or s_idx < cur_idx:
                    st_state = 'done'
                elif s_idx == cur_idx:
                    st_state = 'active'
                else:
                    st_state = 'pending'
                items.append({
                    'id': st.id,
                    'name': st.name,
                    'sequence': st.sequence,
                    'color': st.color or '#C8C9CB',
                    'state': st_state,
                })
            return items

        def _station_payload(disp, disp_tickets, idx_r):
            """Live status of ONE kitchen station (KDS display) for this order:
            its own stage, stepper and items, independent of the other stations."""
            stages = list(disp.stage_ids.sorted('sequence'))
            active = [t for t in disp_tickets if not _is_ticket_completed(t)]
            if active:
                # least advanced ticket of this station drives its status
                cur_idx = min(stages.index(t.stage_id) if t.stage_id in stages else 0 for t in active)
                completed = False
            else:
                cur_idx = len(stages) - 1
                completed = True
            cur_stage = stages[cur_idx]
            cats = {}
            total_qty = 0
            for t in disp_tickets:
                t_completed = _is_ticket_completed(t)
                for kl in t.line_ids.sorted('id'):
                    categs = get_pos_categories(kl.product_id) if kl.product_id else False
                    cat = categs[:1] if categs else False
                    cat_id = cat.id if cat else 0
                    qty_val = int(kl.qty) if float(kl.qty).is_integer() else kl.qty
                    line_done = bool(t_completed or kl.is_done)
                    b_cat = cats.setdefault(cat_id, {
                        'category_id': cat_id,
                        'category_name': (cat.name or 'Other') if cat else 'Other',
                        'total_qty': 0,
                        'done_count': 0,
                        'total_count': 0,
                        'lines': [],
                    })
                    b_cat['total_qty'] += qty_val
                    b_cat['total_count'] += 1
                    b_cat['done_count'] += 1 if line_done else 0
                    b_cat['lines'].append({
                        'id': kl.id,
                        'product_id': kl.product_id.id if kl.product_id else 0,
                        'name': kl.name or (kl.product_id.display_name if kl.product_id else 'Item'),
                        'qty': qty_val,
                        'note': kl.note or '',
                        'is_done': line_done,
                        'stage_name': cur_stage.name,
                        'station_name': disp.name,
                        'batch_number': idx_r,
                    })
                    total_qty += qty_val
            return {
                'display_id': disp.id,
                'display_name': disp.name,
                'ticket_ids': [t.id for t in disp_tickets],
                'current_stage_id': cur_stage.id,
                'current_stage_name': cur_stage.name,
                'current_stage_color': cur_stage.color or '#C8C9CB',
                'current_stage_index': cur_idx,
                'total_stages': len(stages),
                'progress': (cur_idx + (1 if completed else 0)) / (len(stages) or 1),
                'is_completed': completed,
                'is_served_done': completed,
                'stages': _stage_items(stages, cur_idx, completed),
                'categories': sorted(cats.values(), key=lambda c: (c['category_id'] == 0, c['category_name'])),
                'total_qty': total_qty,
            }

        for idx_r, r_tickets in enumerate(rounds, start=1):
            is_current = (idx_r == total_rounds)
            primary_ticket = r_tickets[-1]

            # One status per kitchen station (e.g. Kitchen, Bar, Desserts) in this round
            by_display = {}
            for t in r_tickets:
                if t.display_id and t.display_id.stage_ids:
                    by_display.setdefault(t.display_id, []).append(t)
            stations = [_station_payload(d, d_tickets, idx_r) for d, d_tickets in by_display.items()]
            if not stations:
                continue

            # Round status = slowest station still working (or the last one when all are done)
            working = [s for s in stations if not s['is_completed']]
            lead_station = min(working, key=lambda s: s['progress']) if working else stations[-1]
            r_idx = lead_station['current_stage_index']
            r_completed = not working
            r_stage_items = lead_station['stages']

            # Aggregate all lines ordered in this round (all stations together)
            merged = {}
            for s in stations:
                for c in s['categories']:
                    m = merged.setdefault(c['category_id'], {**c, 'lines': [], 'total_qty': 0,
                                                             'done_count': 0, 'total_count': 0})
                    m['lines'] += c['lines']
                    m['total_qty'] += c['total_qty']
                    m['done_count'] += c['done_count']
                    m['total_count'] += c['total_count']
            batch_cats = merged
            r_total_qty = sum(s['total_qty'] for s in stations)

            pos_ref = self.pos_reference or self.name or ''
            tracking_num = self.tracking_number or ''
            round_title = pos_ref or (f"Current Order (Order #{idx_r})" if is_current else f"Order #{idx_r}")
            batches.append({
                'ticket_id': primary_ticket.id,
                'ticket_ids': [t.id for t in r_tickets],
                'batch_number': idx_r,
                'round_key': f"round_{idx_r}_{primary_ticket.id}",
                'is_current': is_current,
                'title': round_title,
                'pos_reference': pos_ref,
                'tracking_number': tracking_num,
                'kds_reference': f"#{tracking_num}" if tracking_num else pos_ref,
                'barcode': primary_ticket.barcode or f'KDS{primary_ticket.id:06d}',
                'created_at': fields.Datetime.to_string(r_tickets[0].create_date) if r_tickets[0].create_date else '',
                'display_id': lead_station['display_id'],
                'display_name': lead_station['display_name'],
                'current_stage_id': lead_station['current_stage_id'],
                'current_stage_name': lead_station['current_stage_name'],
                'current_stage_color': lead_station['current_stage_color'],
                'current_stage_index': r_idx,
                'total_stages': lead_station['total_stages'],
                'is_completed': r_completed,
                'is_served_done': r_completed,
                'stages': r_stage_items,
                'stations': stations,
                'categories': sorted(batch_cats.values(), key=lambda c: (c['category_id'] == 0, c['category_name'])),
                'total_qty': r_total_qty,
                'total_items': sum(len(c['lines']) for c in batch_cats.values()),
            })

        # Reverse so Current Order is top, followed by newest to oldest previous orders
        batches_reversed = list(reversed(batches))
        current_batch = batches_reversed[0] if batches_reversed else False
        if is_finalized and not current_batch:
            return finalized_payload

        primary_disp = all_ordered_tickets[-1].display_id
        disp_stages = list(primary_disp.stage_ids.sorted('sequence')) if primary_disp else []
        current_stage_name = current_batch['current_stage_name'] if current_batch else (disp_stages[0].name if disp_stages else '')
        current_stage_color = current_batch['current_stage_color'] if current_batch else (disp_stages[0].color if disp_stages else '#C8C9CB')
        current_stage_idx = current_batch['current_stage_index'] if current_batch else 0
        current_completed = current_batch['is_completed'] if current_batch else False

        display_statuses = [{
            'display_id': primary_disp.id,
            'display_name': primary_disp.name,
            'current_stage_id': current_batch['current_stage_id'] if current_batch else (disp_stages[0].id if disp_stages else 0),
            'current_stage_name': current_stage_name,
            'current_stage_color': current_stage_color,
            'current_stage_index': current_stage_idx,
            'total_stages': len(disp_stages),
            'is_completed': current_completed,
            'is_served_done': current_completed,
            'stages': current_batch['stages'] if current_batch else [],
        }] if primary_disp else []

        summary_label = current_stage_name
        summary_state = 'completed' if current_completed else 'in_progress'

        pos_ref = self.pos_reference or self.name or ''
        tracking_num = self.tracking_number or ''

        return {
            'order_id': self.id,
            'pos_reference': pos_ref,
            'tracking_number': tracking_num,
            'order_access_token': self.access_token or '',
            'is_cancelled': False,
            'has_kitchen': True,
            'summary_state': summary_state,
            'summary_label': summary_label,
            'is_served_done': current_completed,
            'displays': display_statuses,
            'batches': batches_reversed,
            'stations': current_batch['stations'] if current_batch else [],
            'categories': current_batch['categories'] if current_batch else [],
        }

    @api.model
    def _get_open_order(self, order):
        """Keep every self-order (QR / mobile) as its own POS order.

        pos_restaurant attaches an incoming draft order to ANY open draft order of the
        same table, which merged a guest's second order into the first one. Self-orders
        are matched on their own uuid only; staff POS orders keep the table behaviour.
        """
        if order.get('source') in ('mobile', 'kiosk'):
            return self.search([('uuid', '=', order.get('uuid'))], limit=1, order='id desc')
        return super()._get_open_order(order)

    def action_manual_send_to_kitchen(self):
        """Manual re-send: pushes any order lines that haven't reached a
        display yet (e.g. items added after the initial send, or a kiosk/
        self-order flow that bypassed the normal create hook). Safe to call
        repeatedly - it never duplicates a line that's already on a display."""
        for order in self:
            order._send_to_kitchen_displays(force=True)
        return True

    def _send_to_kitchen_displays(self, force=False, lines_data=None, skip_new_displays=False):
        PrepDisplay = self.env['pos.prep.display'].sudo()
        KitchenOrder = self.env['pos.kitchen.order'].sudo()
        for order in self:
            if getattr(order, 'state', False) == 'cancel':
                continue
            config = order.config_id if ('config_id' in order._fields and order.config_id) else (order.session_id.config_id if ('session_id' in order._fields and order.session_id) else False)
            company = order.company_id or (config.company_id if config and config.company_id else self.env.company)

            lock_ident = (
                getattr(order, 'uuid', False)
                or (order.pos_reference if order.pos_reference and order.pos_reference != '/' else False)
                or f"pos_order_{order.id}"
            )
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                [f"hkd:{company.id}:{lock_ident}"],
            )
            KitchenOrder.invalidate_model()

            if not config:
                continue
            displays = PrepDisplay.search([
                ('company_id', '=', company.id),
                ('pos_config_ids', 'in', [config.id]),
            ])
            if not displays:
                continue

            table = (
                order.table_id
                if ('table_id' in order._fields and order.table_id)
                else (
                    order.self_ordering_table_id
                    if ('self_ordering_table_id' in order._fields and order.self_ordering_table_id)
                    else False
                )
            )
            num = get_table_number(table)
            if num is not False and num is not None and str(num).strip():
                tbl_name = f"T{num}" if str(num).isdigit() else str(num)
            else:
                tbl_name = order.pos_reference.split()[-1] if order.pos_reference else ''
            cust_count = getattr(order, 'customer_count', 0) or getattr(table, 'seats', 0) or 1
            fulfillment = get_fulfillment_type(order)

            # Link any existing unlinked prep orders matching this order (including archived/Done)
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
                unlinked_preps = KitchenOrder.with_context(active_test=False).search(unlinked_domain)
                if unlinked_preps:
                    unlinked_preps.write({
                        'pos_order_id': order.id,
                        'pos_reference': order.pos_reference,
                        'fulfillment_type': fulfillment,
                        'table_name': tbl_name if tbl_name else (unlinked_preps[0].table_name or ''),
                    })

            # Invalidate cached relations on order
            order.invalidate_recordset(['kitchen_order_ids'])

            # Find all existing prep orders for this order (including archived/Done), across pos_order_id, order_uid, or pos_reference
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
            existing_preps = KitchenOrder.with_context(active_test=False).search(existing_domain)

            # Link any unlinked preps found
            unlinked = existing_preps.filtered(lambda p: not p.pos_order_id)
            if unlinked:
                unlinked.write({
                    'pos_order_id': order.id,
                    'pos_reference': order.pos_reference,
                    'fulfillment_type': fulfillment,
                    'table_name': tbl_name if tbl_name else (unlinked[0].table_name or ''),
                })

            # Track already-sent quantities independently per display so one display
            # never consumes products meant for another display (and repeat lines work).
            sent_qty_by_display = {}
            for prep in existing_preps:
                disp_sent = sent_qty_by_display.setdefault(prep.display_id.id, {})
                for pl in prep.line_ids:
                    pid = pl.product_id.id
                    disp_sent[pid] = disp_sent.get(pid, 0.0) + pl.qty

            non_kitchen_product_ids = get_non_kitchen_product_ids(self.env, config=config, order=order)
            latest_prep_create = max(
                (p.create_date for p in existing_preps if p.create_date),
                default=False,
            )

            for display in displays:
                if (
                    skip_new_displays
                    and existing_preps
                    and display.id not in sent_qty_by_display
                    and latest_prep_create
                    and display.create_date
                    and display.create_date > latest_prep_create
                ):
                    continue
                remaining_sent = dict(sent_qty_by_display.get(display.id, {}))
                lines = []
                if lines_data:
                    for ldata in lines_data:
                        if is_non_kitchen_line(
                            self.env,
                            line_data=ldata,
                            non_kitchen_product_ids=non_kitchen_product_ids,
                            config=config,
                            order=order,
                        ):
                            continue
                        pid = ldata.get('product_id')
                        line_qty = float(ldata.get('qty', 1))
                        product = self.env['product.product'].sudo().browse(pid)
                        if not product.exists():
                            continue
                        categs = get_pos_categories(product)
                        if display.category_ids and not (display.category_ids & categs):
                            continue
                        prev_sent = remaining_sent.get(pid, 0.0)
                        if prev_sent >= line_qty:
                            remaining_sent[pid] = prev_sent - line_qty
                            continue
                        qty_to_send = line_qty - prev_sent
                        remaining_sent[pid] = 0.0
                        lines.append((0, 0, {
                            'product_id': pid,
                            'name': ldata.get('name') or product.display_name,
                            'qty': qty_to_send,
                            'note': ldata.get('note', '') or '',
                            'course_name': ldata.get('course_name', '') or '',
                        }))
                else:
                    for line in order.lines:
                        if is_non_kitchen_line(
                            self.env,
                            line=line,
                            non_kitchen_product_ids=non_kitchen_product_ids,
                            config=config,
                            order=order,
                        ):
                            continue
                        pid = line.product_id.id
                        line_qty = float(line.qty or 0.0)
                        categs = get_pos_categories(line.product_id)
                        if display.category_ids and not (display.category_ids & categs):
                            continue
                        prev_sent = remaining_sent.get(pid, 0.0)
                        if prev_sent >= line_qty:
                            remaining_sent[pid] = prev_sent - line_qty
                            continue
                        qty_to_send = line_qty - prev_sent
                        remaining_sent[pid] = 0.0
                        product_name = getattr(line, 'full_product_name', False) or line.product_id.display_name or getattr(line, 'name', 'Item')
                        course_name = ''
                        if hasattr(line, 'course_id') and line.course_id:
                            course_name = getattr(line.course_id, 'name', '') or (line.course_id.course_id.name if hasattr(line.course_id, 'course_id') and line.course_id.course_id else '')
                        lines.append((0, 0, {
                            'product_id': pid,
                            'name': product_name,
                            'qty': qty_to_send,
                            'note': get_line_note(line),
                            'course_name': course_name,
                        }))

                if not lines:
                    continue
                first_stage = display.stage_ids.sorted('sequence')[:1]
                if not first_stage:
                    continue
                prep_order = KitchenOrder.create({
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
