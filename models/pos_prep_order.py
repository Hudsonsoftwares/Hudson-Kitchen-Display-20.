from odoo import models, fields, api


class PosKitchenOrder(models.Model):
    _name = 'pos.kitchen.order'
    _description = 'Kitchen Preparation Order'
    _order = 'create_date asc'

    pos_order_id = fields.Many2one('pos.order', string='POS Order', required=False, ondelete='cascade', index=True)
    pos_reference = fields.Char(string='POS Reference', index=True)
    order_uid = fields.Char(string='Order UUID', index=True)
    config_id = fields.Many2one('pos.config', string='Point of Sale')
    session_id = fields.Many2one('pos.session', string='POS Session')
    display_id = fields.Many2one('pos.prep.display', required=True, ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
        compute='_compute_company_id', store=True, readonly=False)
    stage_id = fields.Many2one('pos.prep.display.stage', required=True)
    stage_sequence = fields.Integer(related='stage_id.sequence', store=True)
    line_ids = fields.One2many('pos.kitchen.order.line', 'prep_order_id', string='Lines')
    stage_log_ids = fields.One2many('pos.kitchen.order.stage.log', 'prep_order_id', string='Stage history')

    @api.depends('display_id', 'pos_order_id', 'config_id')
    def _compute_company_id(self):
        for rec in self:
            if rec.pos_order_id and rec.pos_order_id.company_id:
                rec.company_id = rec.pos_order_id.company_id
            elif rec.config_id and rec.config_id.company_id:
                rec.company_id = rec.config_id.company_id
            elif rec.display_id and rec.display_id.company_id:
                rec.company_id = rec.display_id.company_id
            elif not rec.company_id:
                rec.company_id = self.env.company

    table_name = fields.Char(string='Table Name')
    customer_count = fields.Integer(string='Guests', default=2)
    table_number = fields.Char(compute='_compute_table_number')
    active = fields.Boolean(default=True)
    fulfillment_type = fields.Selection([
        ('dine_in', 'Dine In'),
        ('takeout', 'Takeout'),
        ('delivery', 'Delivery'),
    ], default='dine_in', required=True)

    done_date = fields.Datetime(string='Completed on')
    prep_duration = fields.Float(
        string='Prep duration (min)', compute='_compute_prep_duration', store=True,
        help='Minutes between the order reaching the kitchen and reaching its last stage.')
    barcode = fields.Char(string='Barcode', compute='_compute_barcode', search='_search_barcode')

    def _compute_barcode(self):
        for rec in self:
            rec_id = rec.id or getattr(rec, '_origin', rec).id
            rec.barcode = f"KDS{rec_id:06d}" if rec_id else False

    def _search_barcode(self, operator, value):
        if operator in ('=', 'ilike', '=ilike', 'like') and value:
            clean = str(value).upper().replace('KDS', '').strip().lstrip('0')
            if clean.isdigit():
                return [('id', '=', int(clean))]
        return [('id', operator, value)]

    def _compute_table_number(self):
        from ..utils import get_table_number
        for rec in self:
            if rec.table_name:
                rec.table_number = rec.table_name
                continue
            table = rec.pos_order_id.table_id if (rec.pos_order_id and 'table_id' in rec.pos_order_id._fields) else False
            num = get_table_number(table)
            if num:
                rec.table_number = f"T{num}" if str(num).isdigit() else str(num)
            else:
                ref = (rec.pos_order_id.pos_reference if rec.pos_order_id else '') or rec.pos_reference or ''
                rec.table_number = ref.split()[-1] if ref else ''

    @api.depends('create_date', 'done_date')
    def _compute_prep_duration(self):
        for rec in self:
            if rec.create_date and rec.done_date:
                rec.prep_duration = round((rec.done_date - rec.create_date).total_seconds() / 60.0, 1)
            else:
                rec.prep_duration = 0.0

    def write(self, vals):
        # Log every stage change for the manager reporting view / audit trail
        if 'stage_id' in vals:
            for order in self:
                if order.stage_id.id != vals['stage_id']:
                    self.env['pos.kitchen.order.stage.log'].sudo().create({
                        'prep_order_id': order.id,
                        'stage_id': vals['stage_id'],
                    })
                    # Trigger auto-print on reaching designated stage
                    disp = order.display_id
                    if disp.auto_print and disp.print_stage_id and disp.print_stage_id.id == vals['stage_id']:
                        try:
                            self.env['bus.bus']._sendone(
                                f'pos_prep_display-{disp.id}', 'pos_prep_print_ticket', {'order_id': order.id}
                            )
                        except Exception:
                            pass
        res = super().write(vals)
        if 'stage_id' in vals:
            for order in self:
                stages = order.display_id.stage_ids.sorted('sequence')
                if stages and order.stage_id.id == stages[-1].id and not order.done_date:
                    order.done_date = fields.Datetime.now()
                elif stages and order.stage_id.id != stages[-1].id and order.done_date:
                    order.done_date = False
        return res

    def action_next_stage(self):
        for order in self:
            stages = list(order.display_id.stage_ids.sorted('sequence'))
            if order.stage_id in stages:
                idx = stages.index(order.stage_id)
                if idx + 1 < len(stages):
                    order.write({'stage_id': stages[idx + 1].id})
                    order._notify_display()

    def action_previous_stage(self):
        """Undo: move an order back one stage. If in the completed / last stage,
        the Reset action moves the order back to the initial (first) stage."""
        for order in self:
            stages = list(order.display_id.stage_ids.sorted('sequence'))
            if order.stage_id in stages:
                idx = stages.index(order.stage_id)
                s_name = (order.stage_id.name or '').lower()
                is_completed = (idx == len(stages) - 1) or any(w in s_name for w in ['complete', 'finish'])
                if is_completed:
                    order.action_reset_to_initial_stage()
                elif idx - 1 >= 0:
                    order.write({'stage_id': stages[idx - 1].id})
                    order.line_ids.write({'is_done': False})
                    order._notify_display()

    def action_reset_to_initial_stage(self):
        """Reset an order from completed or any stage back to the initial (first) stage."""
        for order in self:
            stages = list(order.display_id.stage_ids.sorted('sequence'))
            if stages:
                order.write({
                    'stage_id': stages[0].id,
                    'done_date': False,
                    'active': True,
                })
                order.line_ids.write({'is_done': False})
                order._notify_display()

    def action_reset(self):
        return self.action_reset_to_initial_stage()

    def action_mark_done(self):
        for order in self:
            stages = order.display_id.stage_ids.sorted('sequence')
            last_stage = stages[-1:] if stages else False
            vals = {'active': False}
            if not order.done_date:
                vals['done_date'] = fields.Datetime.now()
            if last_stage and order.stage_id != last_stage:
                vals['stage_id'] = last_stage.id
            order.write(vals)
            order._notify_display()

    def action_recall(self):
        for order in self:
            stages = list(order.display_id.stage_ids.sorted('sequence'))
            vals = {'active': True}
            if order.done_date:
                vals['done_date'] = False
            if stages:
                if order.stage_id in stages:
                    idx = stages.index(order.stage_id)
                    if not order.active:
                        # If order was marked done / cleared, restore it to the last stage (Completed)
                        vals['stage_id'] = stages[-1].id
                    elif idx > 0:
                        # If order was active, undo by moving back one stage
                        vals['stage_id'] = stages[idx - 1].id
                    else:
                        vals['stage_id'] = stages[0].id
                else:
                    vals['stage_id'] = stages[-1].id
            order.write(vals)
            order._notify_display()

    @api.model
    def action_scan_advance(self, barcode, display_id=False):
        """Finds an order by its barcode (e.g. KDS000042 or raw ID) and advances it to the next stage.
        If in the last stage, marks the order as Done."""
        barcode_clean = str(barcode or '').strip().upper()
        if not barcode_clean:
            return {'success': False, 'message': 'Empty barcode'}

        raw_id = False
        clean_digits = barcode_clean.replace('KDS', '').lstrip('0')
        if clean_digits.isdigit():
            raw_id = int(clean_digits)
        elif barcode_clean.isdigit():
            raw_id = int(barcode_clean)

        domain = []
        if raw_id:
            domain = [('id', '=', raw_id)]
        else:
            domain = [
                '|', '|',
                ('table_name', '=ilike', barcode_clean),
                ('pos_reference', '=ilike', barcode_clean),
                ('pos_order_id.pos_reference', '=ilike', barcode_clean),
            ]

        if display_id:
            domain = [('display_id', '=', int(display_id))] + domain

        # Find active order first
        order = self.search(domain + [('active', '=', True)], order='id desc', limit=1)
        if not order:
            order = self.with_context(active_test=False).search(domain, order='id desc', limit=1)

        if not order:
            return {'success': False, 'message': f'No order found matching barcode {barcode_clean}'}

        stages = list(order.display_id.stage_ids.sorted('sequence'))
        if not stages:
            order.action_mark_done()
            return {'success': True, 'order_id': order.id, 'action': 'done', 'table': order.table_number}

        if order.stage_id in stages:
            idx = stages.index(order.stage_id)
            if idx + 1 < len(stages):
                next_stage = stages[idx + 1]
                order.write({'stage_id': next_stage.id})
                order._notify_display()
                return {
                    'success': True,
                    'order_id': order.id,
                    'action': 'advanced',
                    'stage_name': next_stage.name,
                    'table': order.table_number,
                    'barcode': order.barcode,
                }
            else:
                order.action_mark_done()
                return {
                    'success': True,
                    'order_id': order.id,
                    'action': 'done',
                    'stage_name': 'Completed',
                    'table': order.table_number,
                    'barcode': order.barcode,
                }
        else:
            order.write({'stage_id': stages[0].id})
            order._notify_display()
            return {
                'success': True,
                'order_id': order.id,
                'action': 'advanced',
                'stage_name': stages[0].name,
                'table': order.table_number,
                'barcode': order.barcode,
            }

    @api.model
    def action_batch_advance_stage(self, stage_id, display_id=False):
        """Moves all active orders currently in the specified stage to the next stage
        (or completes them if it is the last stage)."""
        stage = self.env['pos.prep.display.stage'].browse(int(stage_id))
        if not stage.exists():
            return {'success': False, 'message': 'Stage not found'}

        display = stage.display_id
        stages = list(display.stage_ids.sorted('sequence'))
        if stage not in stages:
            return {'success': False, 'message': 'Invalid stage'}

        orders = self.search([
            ('display_id', '=', display.id),
            ('stage_id', '=', stage.id),
            ('active', '=', True),
        ])
        if not orders:
            return {'success': True, 'count': 0, 'message': 'No orders to advance'}

        idx = stages.index(stage)
        count = len(orders)
        if idx + 1 < len(stages):
            next_stage = stages[idx + 1]
            orders.write({'stage_id': next_stage.id})
            for o in orders:
                o._notify_display()
            return {'success': True, 'count': count, 'next_stage_name': next_stage.name}
        else:
            orders.action_mark_done()
            return {'success': True, 'count': count, 'next_stage_name': 'Completed'}

    def _notify_display(self):
        """Push a lightweight ping on the display's bus channel so every open
        kitchen screen for that display refreshes near-instantly instead of
        waiting for the next poll. Also pings the customer status page for
        this specific order."""
        for order in self:
            try:
                self.env['bus.bus']._sendone(
                    f'pos_prep_display-{order.display_id.id}', 'pos_prep_order_update', {'order_id': order.id})
                total = len(order.display_id.stage_ids)
                if order.pos_order_id:
                    self.env['bus.bus']._sendone(
                        f'pos_prep_order_status-{order.pos_order_id.id}', 'pos_prep_order_status', {
                            'stage_name': order.stage_id.name,
                            'sequence': order.stage_id.sequence,
                            'total_stages': total,
                        })
            except Exception:
                pass  # bus is best-effort; polling is the safety net

    # kept for backwards compatibility with earlier controller code
    def _notify_customer_screen(self):
        self._notify_display()


class PosKitchenOrderLine(models.Model):
    _name = 'pos.kitchen.order.line'
    _description = 'Kitchen Preparation Order Line'

    prep_order_id = fields.Many2one('pos.kitchen.order', required=True, ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', string='Company', related='prep_order_id.company_id',
        store=True, index=True)
    product_id = fields.Many2one('product.product', required=True)
    name = fields.Char()
    qty = fields.Float(default=1.0)
    note = fields.Char()
    is_done = fields.Boolean(string='Done', default=False)

    def action_toggle_done(self):
        for line in self:
            line.is_done = not line.is_done
            order = line.prep_order_id
            if order and all(l.is_done for l in order.line_ids):
                order.action_next_stage()
                order.line_ids.write({'is_done': False})
            elif order:
                order._notify_display()

    def action_advance_line(self):
        for line in self:
            order = line.prep_order_id
            stages = list(order.display_id.stage_ids.sorted('sequence'))
            if not stages or order.stage_id not in stages:
                continue
            idx = stages.index(order.stage_id)
            if idx + 1 >= len(stages):
                line.is_done = True
                continue
            next_stage = stages[idx + 1]

            if len(order.line_ids) <= 1:
                order.write({'stage_id': next_stage.id})
                line.write({'is_done': False})
                order._notify_display()
                continue

            domain_next = [
                ('display_id', '=', order.display_id.id),
                ('stage_id', '=', next_stage.id),
            ]
            if order.pos_order_id:
                domain_next.append(('pos_order_id', '=', order.pos_order_id.id))
            elif order.pos_reference:
                domain_next.append(('pos_reference', '=', order.pos_reference))
            else:
                domain_next.append(('id', '=', order.id))

            existing_next = self.env['pos.kitchen.order'].search(domain_next, limit=1)

            if not existing_next:
                existing_next = self.env['pos.kitchen.order'].create({
                    'pos_order_id': order.pos_order_id.id if order.pos_order_id else False,
                    'pos_reference': order.pos_reference,
                    'config_id': order.config_id.id if order.config_id else False,
                    'session_id': order.session_id.id if order.session_id else False,
                    'company_id': order.company_id.id if order.company_id else self.env.company.id,
                    'display_id': order.display_id.id,
                    'stage_id': next_stage.id,
                    'table_name': order.table_name,
                    'customer_count': order.customer_count,
                    'fulfillment_type': order.fulfillment_type,
                })

            line.write({
                'prep_order_id': existing_next.id,
                'is_done': False,
            })
            order._notify_display()
            existing_next._notify_display()


class PosKitchenOrderStageLog(models.Model):
    _name = 'pos.kitchen.order.stage.log'
    _description = 'Kitchen Order Stage History (audit trail)'
    _order = 'create_date asc'

    prep_order_id = fields.Many2one('pos.kitchen.order', required=True, ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', string='Company', related='prep_order_id.company_id',
        store=True, index=True)
    stage_id = fields.Many2one('pos.prep.display.stage', required=True)
    display_id = fields.Many2one(related='prep_order_id.display_id', store=True)
