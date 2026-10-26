from odoo import models, fields, tools


class PosPreparationTimeReport(models.Model):
    _name = 'pos.preparation.time.report'
    _description = 'Preparation Time Report'
    _auto = False
    _order = 'date desc'

    prep_order_id = fields.Many2one('pos.kitchen.order', string='Kitchen Order', readonly=True)
    pos_order_id = fields.Many2one('pos.order', string='POS Order', readonly=True)
    pos_reference = fields.Char(string='Receipt Number', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    display_id = fields.Many2one('pos.prep.display', string='Preparation Display', readonly=True)
    stage_id = fields.Many2one('pos.prep.display.stage', string='Stage', readonly=True)
    fulfillment_type = fields.Selection([
        ('dine_in', 'Dine In'),
        ('takeout', 'Takeout'),
        ('delivery', 'Delivery'),
    ], string='Fulfillment', readonly=True)
    table_name = fields.Char(string='Table', readonly=True)
    customer_count = fields.Integer(string='Guests', readonly=True)
    date = fields.Datetime(string='Date', readonly=True)
    create_date = fields.Datetime(string='Received on', readonly=True)
    done_date = fields.Datetime(string='Completed on', readonly=True)
    is_done = fields.Boolean(string='Completed', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    pos_category_id = fields.Many2one('pos.category', string='POS Category', readonly=True)
    categ_id = fields.Many2one('product.category', string='Product Category', readonly=True)

    # Measures
    quantity = fields.Float(string='Quantity', readonly=True, aggregator='sum')
    prep_duration = fields.Float(string='Preparation Time', readonly=True, aggregator='sum')
    avg_prep_duration = fields.Float(string='Average Preparation Time', readonly=True, aggregator='avg')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY o.id, COALESCE(l.id, 0)) AS id,
                    o.id AS prep_order_id,
                    o.pos_order_id AS pos_order_id,
                    COALESCE(o.pos_reference, o.table_name, '') AS pos_reference,
                    o.company_id AS company_id,
                    o.display_id AS display_id,
                    o.stage_id AS stage_id,
                    o.fulfillment_type AS fulfillment_type,
                    o.table_name AS table_name,
                    o.customer_count AS customer_count,
                    o.create_date AS date,
                    o.create_date AS create_date,
                    o.done_date AS done_date,
                    (o.done_date IS NOT NULL) AS is_done,
                    l.product_id AS product_id,
                    pt.categ_id AS categ_id,
                    pos_rel.pos_category_id AS pos_category_id,
                    COALESCE(l.qty, 1.0) AS quantity,
                    CASE 
                        WHEN o.done_date IS NOT NULL AND o.done_date >= o.create_date 
                        THEN ROUND(EXTRACT(EPOCH FROM (o.done_date - o.create_date)))
                        WHEN o.active = TRUE AND o.create_date IS NOT NULL AND o.done_date IS NULL
                        THEN ROUND(EXTRACT(EPOCH FROM (NOW() - o.create_date)))
                        ELSE 0
                    END AS prep_duration,
                    CASE 
                        WHEN o.done_date IS NOT NULL AND o.done_date >= o.create_date 
                        THEN ROUND(EXTRACT(EPOCH FROM (o.done_date - o.create_date)))
                        WHEN o.active = TRUE AND o.create_date IS NOT NULL AND o.done_date IS NULL
                        THEN ROUND(EXTRACT(EPOCH FROM (NOW() - o.create_date)))
                        ELSE 0
                    END AS avg_prep_duration
                FROM pos_kitchen_order o
                LEFT JOIN pos_kitchen_order_line l ON l.prep_order_id = o.id
                LEFT JOIN product_product p ON p.id = l.product_id
                LEFT JOIN product_template pt ON pt.id = p.product_tmpl_id
                LEFT JOIN LATERAL (
                    SELECT rel.pos_category_id 
                    FROM pos_category_product_template_rel rel 
                    WHERE rel.product_template_id = pt.id 
                    LIMIT 1
                ) pos_rel ON TRUE
            )
        """)
