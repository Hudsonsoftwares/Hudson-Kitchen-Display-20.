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
    are present (pos_restaurant tables, self-order tables/presets, delivery
    integrations). Defaults to 'takeout' when nothing indicates otherwise."""
    if 'preset_id' in order._fields and order.preset_id:
        service_at = getattr(order.preset_id, 'service_at', False)
        if service_at == 'delivery':
            return 'delivery'
        if service_at == 'table':
            return 'dine_in'
        if service_at == 'counter':
            return 'takeout'
    if ('table_id' in order._fields and order.table_id) or (
        'self_ordering_table_id' in order._fields and order.self_ordering_table_id
    ):
        return 'dine_in'
    # Self-Order / Kiosk modules commonly add a field like this:
    if 'takeaway' in order._fields and order.takeaway:
        return 'takeout'
    for delivery_field in ('delivery_provider_id', 'delivery_carrier_id', 'is_delivery_order', 'delivery_platform_id'):
        if delivery_field in order._fields and getattr(order, delivery_field):
            return 'delivery'
    return 'takeout'


def get_non_kitchen_product_ids(env, config=None, order=None):
    """Return product.product IDs that represent billing adjustments rather than
    kitchen items (tips, loyalty/global discounts, service/delivery fees,
    down payments, and gift card / eWallet top-ups)."""
    product_ids = set()

    if config:
        for fname in (
            'tip_product_id',
            'discount_product_id',
            'down_payment_product_id',
            'self_ordering_delivery_fee_product_id',
        ):
            if fname in config._fields and getattr(config, fname, False):
                product_ids.add(config[fname].id)

    if order and 'preset_id' in order._fields and order.preset_id:
        preset = order.preset_id
        if 'service_fee_product_id' in preset._fields and preset.service_fee_product_id:
            product_ids.add(preset.service_fee_product_id.id)
    if 'pos.preset' in env:
        presets = env['pos.preset'].sudo().search([])
        for preset in presets:
            if 'service_fee_product_id' in preset._fields and preset.service_fee_product_id:
                product_ids.add(preset.service_fee_product_id.id)
    if not config and 'pos.config' in env:
        configs = env['pos.config'].sudo().with_context(active_test=False).search([])
        for cfg in configs:
            for fname in (
                'tip_product_id',
                'discount_product_id',
                'down_payment_product_id',
                'self_ordering_delivery_fee_product_id',
            ):
                if fname in cfg._fields and getattr(cfg, fname, False):
                    product_ids.add(cfg[fname].id)

    for xml_id in (
        'point_of_sale.product_product_tip',
        'point_of_sale.product_product_service_fee',
        'pos_discount.product_product_consumable',
        'pos_self_order.product_delivery',
    ):
        rec = env.ref(xml_id, raise_if_not_found=False)
        if rec and rec.exists() and rec._name == 'product.product':
            product_ids.add(rec.id)

    if 'loyalty.reward' in env:
        rewards = env['loyalty.reward'].sudo().with_context(active_test=False).search([])
        for reward in rewards:
            if getattr(reward, 'discount_line_product_id', False):
                product_ids.add(reward.discount_line_product_id.id)

    if 'loyalty.program' in env:
        programs = env['loyalty.program'].sudo().with_context(active_test=False).search([
            ('program_type', 'in', ('gift_card', 'ewallet')),
        ])
        for prog in programs:
            if getattr(prog, 'trigger_product_ids', False):
                product_ids.update(prog.trigger_product_ids.ids)

    return product_ids


def is_non_kitchen_line(env, line=None, line_data=None, product=None, non_kitchen_product_ids=None, config=None, order=None):
    """Return True when a POS line / payload dict is a non-kitchen financial line
    (discount, reward deduction, tip, service fee, down payment, gift card, eWallet)."""
    if non_kitchen_product_ids is None:
        non_kitchen_product_ids = get_non_kitchen_product_ids(env, config=config, order=order)

    if line is not None:
        product = product or getattr(line, 'product_id', False)
        if not product:
            return True
        if float(getattr(line, 'qty', 0.0) or 0.0) <= 0:
            return True
        if getattr(line, 'is_reward_line', False):
            reward = getattr(line, 'reward_id', False)
            if not (reward and getattr(reward, 'reward_type', False) == 'product'):
                return True
        if getattr(line, 'gift_card_vals', False):
            return True
        if hasattr(line, '_is_tip_line') and line._is_tip_line():
            return True
        if product.id in non_kitchen_product_ids:
            return True
        if float(getattr(line, 'price_unit', 0.0) or 0.0) < 0 or float(getattr(line, 'price_subtotal_incl', 0.0) or 0.0) < 0:
            return True
        return False

    if line_data is not None:
        pid = line_data.get('product_id')
        if not pid:
            return True
        if float(line_data.get('qty', 1) or 0.0) <= 0:
            return True
        if line_data.get('is_reward_line') and line_data.get('reward_type') != 'product':
            return True
        if line_data.get('is_tip_line') or line_data.get('is_payment_program'):
            return True
        if int(pid) in non_kitchen_product_ids:
            return True
        if float(line_data.get('price_unit', 0.0) or 0.0) < 0:
            return True
        return False

    return bool(product and product.id in non_kitchen_product_ids)
