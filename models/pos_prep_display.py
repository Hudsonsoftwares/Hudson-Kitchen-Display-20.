import uuid

from odoo import models, fields, api


class PosPrepDisplay(models.Model):
    _name = 'pos.prep.display'
    _description = 'Kitchen / Preparation Display'

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    pos_config_ids = fields.Many2many(
        'pos.config', string='Point of Sale',
        domain="[('company_id', '=', company_id)]",
        help='Orders from these Point of Sale configs will be pushed to this display. '
             'Leave empty to receive orders from every POS in this company.')
    category_ids = fields.Many2many(
        'pos.category', string='Product categories',
        help='Only order lines whose product belongs to one of these categories will '
             'show on this display. Leave empty to receive every product.')
    auto_clear = fields.Boolean(
        string='Auto clear',
        help='Automatically drop an order from the screen once it reaches the last stage.')
    auto_print = fields.Boolean(
        string='Auto Print on Stage',
        default=False,
        help='Automatically trigger ticket printing when an order moves to the designated stage.')
    print_stage_id = fields.Many2one(
        'pos.prep.display.stage',
        string='Print at Stage',
        domain="[('display_id', '=', id)]",
        help='Orders entering this stage will trigger ticket printing.')
    def _default_stage_ids(self):
        return [
            (0, 0, {'name': 'To cook', 'sequence': 1, 'color': '#C8C9CB', 'alert_timer': 10}),
            (0, 0, {'name': 'Ready', 'sequence': 2, 'color': '#4A90E2', 'alert_timer': 5}),
            (0, 0, {'name': 'Completed', 'sequence': 3, 'color': '#55BA53', 'alert_timer': 0}),
        ]

    stage_ids = fields.One2many(
        'pos.prep.display.stage', 'display_id', string='Stages',
        default=_default_stage_ids)
    stage_names = fields.Char(compute='_compute_stage_names')
    stage_names_list = fields.Json(compute='_compute_stage_names')
    access_token = fields.Char(default=lambda self: str(uuid.uuid4()), copy=False, readonly=True)
    order_count = fields.Integer(compute='_compute_order_count')
    in_progress_count = fields.Integer(compute='_compute_dashboard_stats', string='In Progress')
    average_time = fields.Integer(compute='_compute_dashboard_stats', string='Average Time (min)')

    @api.depends('stage_ids.name', 'stage_ids.sequence')
    def _compute_stage_names(self):
        for rec in self:
            names = rec.stage_ids.sorted('sequence').mapped('name')
            rec.stage_names = ' \u2022 '.join(names)
            rec.stage_names_list = names

    def _compute_order_count(self):
        for rec in self:
            rec.order_count = self.env['pos.kitchen.order'].search_count(
                [('display_id', '=', rec.id)])

    @api.depends('stage_ids')
    def _compute_dashboard_stats(self):
        for rec in self:
            stages = rec.stage_ids.sorted('sequence')
            last_stage = stages[-1:] if stages else False
            if last_stage:
                in_prog = self.env['pos.kitchen.order'].search_count([
                    ('display_id', '=', rec.id),
                    ('stage_id', '!=', last_stage.id),
                ])
            else:
                in_prog = self.env['pos.kitchen.order'].search_count([
                    ('display_id', '=', rec.id),
                ])
            rec.in_progress_count = in_prog

            completed = self.env['pos.kitchen.order'].search([
                ('display_id', '=', rec.id),
                ('done_date', '!=', False),
            ])
            if completed:
                avg = sum(completed.mapped('prep_duration')) / len(completed)
                rec.average_time = int(round(avg))
            else:
                rec.average_time = 0

    @api.model_create_multi
    def create(self, vals_list):
        displays = super().create(vals_list)
        for display in displays:
            if not display.stage_ids:
                display.write({'stage_ids': [
                    (0, 0, {'name': 'To cook', 'sequence': 1, 'color': '#C8C9CB', 'alert_timer': 10}),
                    (0, 0, {'name': 'Ready', 'sequence': 2, 'color': '#4A90E2', 'alert_timer': 5}),
                    (0, 0, {'name': 'Completed', 'sequence': 3, 'color': '#55BA53', 'alert_timer': 0}),
                ]})
        return displays

    def action_reset_all_orders(self):
        self.ensure_one()
        first_stage = self.stage_ids.sorted('sequence')[:1]
        if first_stage:
            orders = self.env['pos.kitchen.order'].search([('display_id', '=', self.id)])
            orders.write({'stage_id': first_stage.id, 'done_date': False, 'active': True})
            orders.mapped('line_ids').write({'is_done': False})
            orders._notify_display()
        return True

    def action_open_kitchen_screen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/hudson_kitchen_display/web?display_id={self.id}',
            'target': 'new',
        }

    def action_open_order_status_screen(self):
        self.ensure_one()
        url = f'/pos-order-tracking/?access_token={self.access_token}' if self.access_token else f'/hudson_kitchen_display/order_status?display_id={self.id}'
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_configure(self):
        self.ensure_one()
        return {
            'name': 'Preparation Display',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.prep.display',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }


class PosPrepDisplayStage(models.Model):
    _name = 'pos.prep.display.stage'
    _description = 'Kitchen Display Stage'
    _order = 'sequence, id'

    display_id = fields.Many2one('pos.prep.display', required=True, ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', string='Company', related='display_id.company_id',
        store=True, index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    color = fields.Char(string='Color', default='#C8C9CB', help='Color used for this stage on the kitchen screen.')
    alert_timer = fields.Integer(
        string='Alert time (minutes)',
        help='Highlight an order in red once it has stayed in this stage longer than this '
             'many minutes. Set to 0 to disable the alert for this stage.')
