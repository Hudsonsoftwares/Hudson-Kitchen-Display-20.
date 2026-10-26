"""Small helpers to smooth over field-name differences across Odoo versions
(17/18/19 vs older Community releases). Import these instead of accessing
the raw fields directly so a single place needs updating if your version
differs."""


def get_pos_categories(product):
    """product.product / product.template -> recordset of pos.category"""
    if not product:
        return product
    tmpl = product.product_tmpl_id if 'product_tmpl_id' in product._fields else product
    if 'pos_categ_ids' in tmpl._fields:
        return tmpl.pos_categ_ids
    if 'pos_categ_id' in tmpl._fields:
        return tmpl.pos_categ_id
    return tmpl.env['pos.category']


def get_table_number(table):
    """restaurant.table -> display string, whichever field name your version uses"""
    if not table:
        return False
    val = getattr(table, 'table_number', False)
    if val is not False and val is not None:
        return val
    return getattr(table, 'name', False) or getattr(table, 'display_name', False) or False


import json


def get_line_note(line):
    """pos.order.line -> customer/kitchen note, handling plain string or JSON list"""
    raw = getattr(line, 'note', False) or getattr(line, 'customer_note', False) or False
    if not raw:
        return False
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return ", ".join(item.get('text', str(item)) if isinstance(item, dict) else str(item) for item in parsed)
            if isinstance(parsed, dict):
                return parsed.get('text', str(parsed))
        except Exception:
            pass
    return str(raw).strip()


def get_fulfillment_type(order):
    """Best-effort guess of dine_in / takeout / delivery from whatever fields
    are present (pos_restaurant tables, self-order kiosk fields, delivery
    integrations). Defaults to 'takeout' when nothing indicates otherwise."""
    if 'table_id' in order._fields and order.table_id:
        return 'dine_in'
    # Self-Order / Kiosk modules commonly add a field like this:
    if 'takeaway' in order._fields and order.takeaway:
        return 'takeout'
    for delivery_field in ('delivery_provider_id', 'delivery_carrier_id', 'is_delivery_order', 'delivery_platform_id'):
        if delivery_field in order._fields and getattr(order, delivery_field):
            return 'delivery'
    return 'takeout'
