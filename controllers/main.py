from datetime import timedelta

from werkzeug.exceptions import Forbidden

from odoo import http, fields
from odoo.http import request


def _has_kitchen_access(env):
    user = env.user
    if not user:
        return False
    if getattr(user, '_is_internal', lambda: False)() or getattr(user, '_is_admin', lambda: False)():
        return True
    if user.has_group('point_of_sale.group_pos_user') or user.has_group('point_of_sale.group_pos_manager') or user.has_group('base.group_user'):
        return True
    return bool(getattr(user, 'kitchen_screen_access', False))


def _safe_int(val, default=0):
    try:
        if val is None or val == '' or str(val).lower() == 'undefined':
            return default
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_display_number(prep_order):
    po = prep_order.pos_order_id
    if po:
        if getattr(po, 'tracking_number', False):
            return str(po.tracking_number).strip()
        if getattr(po, 'table_id', False):
            from ..utils import get_table_number
            t_num = get_table_number(po.table_id)
            if t_num:
                return str(t_num)
        if po.pos_reference:
            ref = po.pos_reference
            parts = ref.replace('-', ' ').split()
            last = parts[-1].lstrip('0')
            return last or parts[-1]
    if prep_order.pos_reference:
        parts = prep_order.pos_reference.replace('-', ' ').split()
        last = parts[-1].lstrip('0')
        if last:
            return last
    if prep_order.table_name:
        parts = prep_order.table_name.replace('-', ' ').split()
        last = parts[-1].lstrip('0')
        if last:
            return last
        return str(prep_order.table_name).lstrip('T').strip()
    return str(prep_order.id)


class KitchenDisplayController(http.Controller):

    # ------------------------------------------------------------------
    # Kitchen (internal, staff-facing) screen
    # ------------------------------------------------------------------
    @http.route('/hudson_kitchen_display/web', type='http', auth='user')
    def kitchen_display_page(self, display_id=None, **kwargs):
        if not _has_kitchen_access(request.env):
            raise Forbidden()
        d_id = _safe_int(display_id)
        display = request.env['pos.prep.display'].browse(d_id) if d_id else None
        if not display or not display.exists():
            company_ids = request.env.companies.ids if request.env.user and not request.env.user._is_public() else [request.env.company.id]
            display = request.env['pos.prep.display'].search([('company_id', 'in', company_ids)], limit=1)
        if not display or not display.exists():
            display = request.env['pos.prep.display'].search([], limit=1)
        return request.render('hudson_kitchen_display.kitchen_display_page', {
            'display_id': display.id if display else '',
            'display_name': display.name if display else 'Kitchen Display',
            'access_token': display.access_token if display else '',
        })

    @http.route('/hudson_kitchen_display/get_orders', type='json', auth='user')
    def get_orders(self, display_id=None):
        if not _has_kitchen_access(request.env):
            return {'error': 'access_denied'}
        d_id = _safe_int(display_id)
        display = request.env['pos.prep.display'].browse(d_id) if d_id else None
        if not display or not display.exists():
            company_ids = request.env.companies.ids if request.env.user and not request.env.user._is_public() else [request.env.company.id]
            display = request.env['pos.prep.display'].search([('company_id', 'in', company_ids)], limit=1)
        if not display or not display.exists():
            display = request.env['pos.prep.display'].search([], limit=1)
        if not display or not display.exists():
            return {'display_name': 'Kitchen Display', 'stages': [], 'categories': [], 'orders': []}

        # Multi-company safety check
        if display.company_id and display.company_id not in request.env.companies and not request.env.is_admin():
            return {'error': 'access_denied'}

        orders = request.env['pos.kitchen.order'].search([
            ('display_id', '=', display.id),
            ('company_id', '=', display.company_id.id),
        ])

        from ..utils import get_pos_categories

        # Determine restricted categories from display or POS config settings for this company
        categories = display.category_ids
        if not categories:
            configs = display.pos_config_ids or request.env['pos.config'].search([('company_id', '=', display.company_id.id)])
            for cfg in configs:
                if getattr(cfg, 'iface_available_categ_ids', False):
                    categories |= cfg.iface_available_categ_ids
        if not categories:
            categories = request.env['pos.category'].search([])

        def _get_order_category_ids(o):
            cat_ids = set()
            for l in o.line_ids:
                if l.product_id:
                    for c in get_pos_categories(l.product_id):
                        cat_ids.add(c.id)
            return list(cat_ids)

        return {
            'display_name': display.name,
            'stages': [
                {'id': s.id, 'name': s.name, 'sequence': s.sequence,
                 'color': s.color, 'alert_timer': s.alert_timer}
                for s in display.stage_ids.sorted('sequence')
            ],
            'categories': [
                {'id': c.id, 'name': c.name}
                for c in categories.sorted('name')
            ],
            'orders': [{
                'id': o.id,
                'pos_order_id': o.pos_order_id.id if o.pos_order_id else False,
                'pos_reference': (o.pos_order_id.pos_reference if o.pos_order_id else '') or o.pos_reference or f'#{o.id}',
                'display_number': _get_display_number(o),
                'tracking_number': str(o.pos_order_id.tracking_number).strip() if (o.pos_order_id and getattr(o.pos_order_id, 'tracking_number', False)) else '',
                'table_number': _get_display_number(o),
                'customer_count': o.customer_count or (getattr(o.pos_order_id, 'customer_count', 1) if o.pos_order_id else 1) or 1,
                'fulfillment_type': o.fulfillment_type or 'dine_in',
                'stage_id': o.stage_id.id,
                'category_ids': _get_order_category_ids(o),
                'create_date': fields.Datetime.to_string(o.create_date),
                'minutes_ago': int(round((fields.Datetime.now() - o.create_date).total_seconds() / 60)) if o.create_date else 0,
                'barcode': o.barcode or f'KDS{o.id:06d}',
                'lines': [{'id': l.id, 'name': l.name, 'qty': int(l.qty) if float(l.qty).is_integer() else l.qty, 'note': l.note, 'is_done': bool(l.is_done)} for l in o.line_ids],
            } for o in orders],
        }

    @http.route('/hudson_kitchen_display/scan_barcode', type='json', auth='user')
    def scan_barcode(self, barcode, display_id=None):
        if not _has_kitchen_access(request.env):
            return {'success': False, 'message': 'Access denied'}
        return request.env['pos.kitchen.order'].action_scan_advance(barcode, display_id=display_id)

    @http.route('/hudson_kitchen_display/batch_advance', type='json', auth='user')
    def batch_advance(self, stage_id, display_id=None):
        if not _has_kitchen_access(request.env):
            return {'success': False, 'message': 'Access denied'}
        return request.env['pos.kitchen.order'].action_batch_advance_stage(stage_id, display_id=display_id)

    @http.route('/hudson_kitchen_display/ticket_html/<int:order_id>', type='http', auth='user')
    def ticket_html(self, order_id):
        if not _has_kitchen_access(request.env):
            raise Forbidden()
        order = request.env['pos.kitchen.order'].browse(order_id)
        if not order.exists():
            return request.not_found()

        barcode = order.barcode or f"KDS{order.id:06d}"
        lines = order.line_ids
        table = order.table_number or (order.pos_order_id.pos_reference.split()[-1] if order.pos_order_id and order.pos_order_id.pos_reference else (order.pos_reference.split()[-1] if order.pos_reference else f"#{order.id}"))
        fulfillment = (order.fulfillment_type or 'dine_in').replace('_', ' ').title()
        time_str = fields.Datetime.to_string(order.create_date) or ''

        # Render 80mm/58mm Kitchen Preparation Ticket with barcode
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>Kitchen Ticket - {barcode}</title>
    <style>
        @page {{
            size: 80mm auto;
            margin: 0;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: 'Courier New', Courier, monospace, sans-serif;
            width: 76mm;
            margin: 0 auto;
            padding: 8px 4px;
            color: #000000;
            background: #ffffff;
            font-size: 14px;
            line-height: 1.3;
        }}
        .ticket-header {{
            text-align: center;
            border-bottom: 2px dashed #000;
            padding-bottom: 8px;
            margin-bottom: 8px;
        }}
        .ticket-title {{
            font-size: 22px;
            font-weight: 900;
            letter-spacing: 1px;
        }}
        .ticket-sub {{
            font-size: 14px;
            font-weight: 700;
            margin-top: 2px;
        }}
        .ticket-meta {{
            display: flex;
            justify-content: space-between;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 6px;
        }}
        .ticket-items {{
            border-bottom: 2px dashed #000;
            padding-bottom: 8px;
            margin-bottom: 8px;
        }}
        .ticket-item {{
            margin-bottom: 6px;
        }}
        .ticket-item-row {{
            display: flex;
            justify-content: space-between;
            font-size: 16px;
            font-weight: 800;
        }}
        .ticket-item-note {{
            font-size: 12px;
            font-style: italic;
            padding-left: 18px;
            font-weight: 600;
        }}
        .ticket-barcode-box {{
            text-align: center;
            margin-top: 10px;
            padding-top: 4px;
        }}
        .barcode-visual {{
            font-family: 'Libre Barcode 128', 'Libre Barcode 39', 'Courier New', monospace;
            font-size: 38px;
            letter-spacing: 3px;
            line-height: 1;
            display: block;
            margin: 4px 0;
        }}
        .barcode-text {{
            font-size: 14px;
            font-weight: 900;
            letter-spacing: 2px;
        }}
        .scan-instruction {{
            font-size: 11px;
            text-align: center;
            margin-top: 4px;
            color: #333;
        }}
        @media print {{
            body {{
                width: 100%;
                padding: 0;
            }}
            .no-print {{
                display: none;
            }}
        }}
    </style>
    <link href="https://fonts.googleapis.com/css2?family=Libre+Barcode+128&display=swap" rel="stylesheet">
</head>
<body>
    <div class="ticket-header">
        <div class="ticket-title">KITCHEN TICKET</div>
        <div class="ticket-sub">{order.display_id.name} &bull; {order.stage_id.name}</div>
    </div>

    <div class="ticket-meta">
        <div>TABLE: <span style="font-size:18px;">{table}</span></div>
        <div>GUESTS: {order.customer_count or 1}</div>
    </div>
    <div class="ticket-meta">
        <div>TYPE: {fulfillment}</div>
        <div>TIME: {time_str[11:16] if len(time_str) >= 16 else ''}</div>
    </div>

    <div class="ticket-items">
"""
        for l in lines:
            qty_str = f"{int(l.qty) if float(l.qty).is_integer() else l.qty}x"
            note_html = f'<div class="ticket-item-note">*** {l.note} ***</div>' if l.note else ''
            html += f"""
        <div class="ticket-item">
            <div class="ticket-item-row">
                <span>{qty_str} {l.name}</span>
            </div>
            {note_html}
        </div>
"""

        html += f"""
    </div>

    <div class="ticket-barcode-box">
        <div class="barcode-visual">*{barcode}*</div>
        <div class="barcode-text">{barcode}</div>
        <div class="scan-instruction">Scan barcode to advance order stage</div>
    </div>

    <script>
        window.addEventListener('load', () => {{
            window.print();
        }});
    </script>
</body>
</html>
"""
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @http.route('/hudson_kitchen_display/toggle_line', type='json', auth='user')
    def toggle_line(self, line_id):
        if not _has_kitchen_access(request.env):
            return False
        lid = _safe_int(line_id)
        line = request.env['pos.kitchen.order.line'].browse(lid) if lid else None
        if not line or not line.exists():
            return False
        line.action_toggle_done()
        return True

    @http.route('/hudson_kitchen_display/advance_line', type='json', auth='user')
    def advance_line(self, line_id):
        if not _has_kitchen_access(request.env):
            return False
        lid = _safe_int(line_id)
        line = request.env['pos.kitchen.order.line'].browse(lid) if lid else None
        if not line or not line.exists():
            return False
        line.action_advance_line()
        return True

    @http.route('/hudson_kitchen_display/change_stage', type='json', auth='user')
    def change_stage(self, order_id, stage_id):
        if not _has_kitchen_access(request.env):
            return False
        oid = _safe_int(order_id)
        sid = _safe_int(stage_id)
        order = request.env['pos.kitchen.order'].browse(oid) if oid else None
        if not order or not order.exists() or not sid:
            return False
        order.write({'stage_id': sid})
        order._notify_display()
        return True

    @http.route('/hudson_kitchen_display/previous_stage', type='json', auth='user')
    def previous_stage(self, order_id):
        if not _has_kitchen_access(request.env):
            return False
        oid = _safe_int(order_id)
        order = request.env['pos.kitchen.order'].browse(oid) if oid else None
        if not order or not order.exists():
            return False
        order.action_previous_stage()
        return True

    @http.route('/hudson_kitchen_display/reset_order', type='json', auth='user')
    def reset_order(self, order_id):
        if not _has_kitchen_access(request.env):
            return False
        oid = _safe_int(order_id)
        order = request.env['pos.kitchen.order'].browse(oid) if oid else None
        if not order or not order.exists():
            return False
        order.action_reset_to_initial_stage()
        return True

    @http.route('/hudson_kitchen_display/mark_done', type='json', auth='user')
    def mark_done(self, order_id):
        if not _has_kitchen_access(request.env):
            return False
        oid = _safe_int(order_id)
        order = request.env['pos.kitchen.order'].browse(oid) if oid else None
        if order and order.exists():
            order.action_mark_done()
        return True

    @http.route('/hudson_kitchen_display/clear_completed', type='json', auth='user')
    def clear_completed(self, display_id):
        if not _has_kitchen_access(request.env):
            return False
        did = _safe_int(display_id)
        display = request.env['pos.prep.display'].browse(did) if did else None
        if not display or not display.exists():
            return False
        stages = display.stage_ids.sorted('sequence')
        if stages:
            last_stage = stages[-1]
            orders = request.env['pos.kitchen.order'].search([
                ('display_id', '=', display.id),
                ('stage_id', '=', last_stage.id),
            ])
            orders.action_mark_done()
        return True

    @http.route('/hudson_kitchen_display/recall', type='json', auth='user')
    def recall(self, order_id=None, display_id=None):
        if not _has_kitchen_access(request.env):
            return {'success': False, 'error': 'access_denied'}
        Order = request.env['pos.kitchen.order'].with_context(active_test=False)
        order = None
        oid = _safe_int(order_id)
        did = _safe_int(display_id)
        if oid:
            order = Order.browse(oid)
        elif did:
            order = Order.search([
                ('display_id', '=', did),
            ], order='write_date desc, id desc', limit=1)

        if not order or not order.exists():
            return {'success': False, 'error': 'not_found'}

        order.action_recall()
        return {
            'success': True,
            'order_id': order.id,
            'stage_id': order.stage_id.id,
            'stage_name': order.stage_id.name,
            'table_number': order.table_number,
        }

    @http.route('/hudson_kitchen_display/reset_all', type='json', auth='user')
    def reset_all(self, display_id):
        if not _has_kitchen_access(request.env):
            return False
        did = _safe_int(display_id)
        display = request.env['pos.prep.display'].browse(did) if did else None
        if not display or not display.exists():
            return False
        display.action_reset_all_orders()
        return True

    # ------------------------------------------------------------------
    # Manual "Send to Kitchen"
    # ------------------------------------------------------------------
    @http.route('/hudson_kitchen_display/send_to_kitchen', type='json', auth='user')
    def send_to_kitchen(self, order_data):
        """Send an in-progress or draft POS order directly to the kitchen display
        before payment."""
        if not order_data:
            return {'ok': False, 'message': 'No order data received'}

        pos_reference = order_data.get('pos_reference') or order_data.get('name') or ''
        order_uid = order_data.get('order_uid') or ''
        server_id = order_data.get('server_id')
        session_id = order_data.get('session_id')
        config_id = order_data.get('config_id')
        company_id = order_data.get('company_id')
        table_name = order_data.get('table_name') or ''
        customer_count = order_data.get('customer_count') or 1
        fulfillment = order_data.get('fulfillment_type') or 'dine_in'
        lines_data = order_data.get('lines', [])

        if not lines_data:
            return {'ok': False, 'message': 'Order has no items to send'}

        pos_order = False
        if server_id:
            try:
                pos_order = request.env['pos.order'].sudo().browse(int(server_id))
                if not pos_order.exists():
                    pos_order = False
            except Exception:
                pos_order = False

        # Determine company with strict priority:
        company = False
        if pos_order and pos_order.company_id:
            company = pos_order.company_id
        if not company and company_id:
            try:
                c = request.env['res.company'].sudo().browse(int(company_id))
                if c.exists():
                    company = c
            except Exception:
                pass
        if not company and config_id:
            try:
                cfg = request.env['pos.config'].sudo().browse(int(config_id))
                if cfg.exists() and cfg.company_id:
                    company = cfg.company_id
            except Exception:
                pass
        if not company and session_id:
            try:
                sess = request.env['pos.session'].sudo().browse(int(session_id))
                if sess.exists() and sess.config_id and sess.config_id.company_id:
                    company = sess.config_id.company_id
            except Exception:
                pass
        if not company:
            company = request.env.company

        # Search existing pos.order by uuid or pos_reference
        if not pos_order:
            search_conds = []
            if order_uid and 'uuid' in request.env['pos.order']._fields:
                search_conds.append(('uuid', '=', order_uid))
            if pos_reference and pos_reference != '/':
                search_conds.append(('pos_reference', '=', pos_reference))
            if search_conds:
                domain = [('company_id', '=', company.id)]
                if len(search_conds) > 1:
                    domain += ['|'] * (len(search_conds) - 1)
                domain += search_conds
                pos_order = request.env['pos.order'].sudo().search(domain, limit=1)

        # If a backend pos.order already exists, send using its model method
        if pos_order:
            pos_order._send_to_kitchen_displays(force=True, lines_data=lines_data)
            return {'ok': True, 'pos_order_id': pos_order.id, 'pos_reference': pos_reference, 'message': 'Order sent to kitchen'}

        # Otherwise, find matching displays for this specific company and create pos.kitchen.order directly
        PrepDisplay = request.env['pos.prep.display'].sudo()
        display_domain = [('company_id', '=', company.id)]
        if config_id:
            display_domain.extend(['|', ('pos_config_ids', '=', False), ('pos_config_ids', 'in', int(config_id))])
        displays = PrepDisplay.search(display_domain)
        if not displays:
            displays = PrepDisplay.search([('company_id', '=', company.id)])

        if not displays:
            return {'ok': False, 'message': f'No kitchen display configured for company {company.name}'}

        from ..utils import get_pos_categories

        # Calculate already sent quantities for this pos_reference/order_uid within this company
        existing_domain = [('company_id', '=', company.id)]
        match_conds = []
        if order_uid:
            match_conds.append(('order_uid', '=', order_uid))
        if pos_reference and pos_reference != '/':
            match_conds.append(('pos_reference', '=', pos_reference))
        if match_conds:
            if len(match_conds) > 1:
                existing_domain += ['|'] * (len(match_conds) - 1)
            existing_domain += match_conds
            existing_preps = request.env['pos.kitchen.order'].sudo().search(existing_domain)
        else:
            existing_preps = request.env['pos.kitchen.order'].sudo().browse()

        sent_qty_per_product = {}
        for prep in existing_preps:
            for pl in prep.line_ids:
                pid = pl.product_id.id
                sent_qty_per_product[pid] = sent_qty_per_product.get(pid, 0.0) + pl.qty

        created_prep_ids = []
        for display in displays:
            lines = []
            for ldata in lines_data:
                pid = ldata.get('product_id')
                if not pid:
                    continue
                qty = float(ldata.get('qty', 1))
                sent_qty = sent_qty_per_product.get(pid, 0.0)
                qty_to_send = qty - sent_qty
                if qty_to_send <= 0:
                    continue
                product = request.env['product.product'].sudo().browse(pid)
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

            if not lines:
                continue
            first_stage = display.stage_ids.sorted('sequence')[:1]
            if not first_stage:
                continue
            prep_order = request.env['pos.kitchen.order'].sudo().create({
                'pos_order_id': False,
                'pos_reference': pos_reference,
                'order_uid': order_uid,
                'config_id': int(config_id) if config_id else False,
                'session_id': int(session_id) if session_id else False,
                'company_id': company.id,
                'display_id': display.id,
                'stage_id': first_stage.id,
                'fulfillment_type': fulfillment,
                'table_name': table_name,
                'customer_count': customer_count,
                'line_ids': lines,
            })
            prep_order._notify_display()
            created_prep_ids.append(prep_order.id)

        if not created_prep_ids and existing_preps:
            return {'ok': True, 'message': 'All items were already sent to kitchen', 'pos_reference': pos_reference}

        return {
            'ok': True,
            'pos_reference': pos_reference,
            'prep_order_ids': created_prep_ids,
            'message': 'Order sent to kitchen successfully',
        }

    # ------------------------------------------------------------------
    @http.route('/hudson_kitchen_display/manual_send_last_order', type='json', auth='user')
    def manual_send_last_order(self):
        order = request.env['pos.order'].sudo().search([
            ('create_uid', '=', request.env.uid),
            ('create_date', '>=', fields.Datetime.now() - timedelta(minutes=30)),
        ], order='create_date desc', limit=1)
        if not order:
            return {'ok': False}
        order.action_manual_send_to_kitchen()
        return {'ok': True, 'order_id': order.id}

    @http.route('/hudson_kitchen_display/manual_send/<int:order_id>', type='json', auth='user')
    def manual_send(self, order_id):
        order = request.env['pos.order'].sudo().browse(order_id)
        if not order.exists():
            return {'ok': False}
        order.action_manual_send_to_kitchen()
        return {'ok': True}

    # ------------------------------------------------------------------
    # Customer-facing order status screen (public, token protected)
    # ------------------------------------------------------------------
    @http.route('/pos-order-status/<string:access_token>', type='http', auth='public')
    def order_status_page(self, access_token, **kwargs):
        order = request.env['pos.order'].sudo().search(
            [('kitchen_access_token', '=', access_token)], limit=1)
        if not order:
            return request.not_found()
        return request.render('hudson_kitchen_display.order_status_page', {
            'order_id': order.id,
        })

    @http.route('/hudson_kitchen_display/get_order_status', type='json', auth='public')
    def get_order_status(self, order_id):
        oid = _safe_int(order_id)
        order = request.env['pos.order'].sudo().browse(oid) if oid else None
        if not order or not order.exists():
            return {'stage_name': 'Order received', 'sequence': 0, 'total_stages': 1}
        prep = order.kitchen_order_ids[:1]
        if not prep:
            return {'stage_name': 'Order received', 'sequence': 0, 'total_stages': 1}
        stages = prep.display_id.stage_ids.sorted('sequence')
        return {
            'stage_name': prep.stage_id.name,
            'sequence': prep.stage_id.sequence,
            'total_stages': len(stages),
        }

    # ------------------------------------------------------------------
    # Customer-facing order tracking screen (matching Odoo Online)
    # ------------------------------------------------------------------
    @http.route([
        '/pos-order-tracking',
        '/pos-order-tracking/',
        '/pos-order-tracking/<string:access_token>',
        '/hudson_kitchen_display/order_status',
    ], type='http', auth='public')
    def display_order_status_page(self, access_token=None, display_id=None, **kwargs):
        PrepDisplay = request.env['pos.prep.display'].sudo()
        token = access_token or kwargs.get('access_token')
        display = False
        if token:
            display = PrepDisplay.search([('access_token', '=', token)], limit=1)
        if not display and display_id:
            did = _safe_int(display_id)
            if did:
                display = PrepDisplay.browse(did)
        if not display or not display.exists():
            company_ids = request.env.companies.ids if request.env.user and not request.env.user._is_public() else [request.env.company.id]
            display = PrepDisplay.search([('company_id', 'in', company_ids)], limit=1)
        if not display or not display.exists():
            display = PrepDisplay.search([], limit=1)

        return request.render('hudson_kitchen_display.display_order_status_page', {
            'display_id': display.id if display else '',
            'display_name': display.name if display else 'Order Status',
            'access_token': display.access_token if display else '',
        })

    @http.route([
        '/hudson_kitchen_display/get_display_orders_status',
        '/pos-order-tracking/get_orders_status',
    ], type='json', auth='public')
    def get_display_orders_status(self, display_id=None, access_token=None):
        PrepDisplay = request.env['pos.prep.display'].sudo()
        display = False
        if access_token:
            display = PrepDisplay.search([('access_token', '=', access_token)], limit=1)
        if not display and display_id:
            did = _safe_int(display_id)
            if did:
                display = PrepDisplay.browse(did)
        if not display or not display.exists():
            company_ids = request.env.companies.ids if request.env.user and not request.env.user._is_public() else [request.env.company.id]
            display = PrepDisplay.search([('company_id', 'in', company_ids)], limit=1)
        if not display or not display.exists():
            display = PrepDisplay.search([], limit=1)

        if not display or not display.exists():
            return {'ready': [], 'preparing': [], 'stages': []}

        stages = display.stage_ids.sorted('sequence')
        if not stages:
            return {'ready': [], 'preparing': [], 'stages': []}

        # Stage classification for Customer Order Status Screen:
        # - Orders in 'Completed' stage -> Show in 'Ready' (customer pickup)
        # - Orders in 'Ready' stage in kitchen -> Show in 'Almost there' (food being packed / almost ready)
        # - Orders in 'To cook' stage -> Internal kitchen preparation only (NOT shown on customer screen)
        # - Orders with active=False (marked Done) -> Already handed over to customer (dropped from screen)
        completed_stage_ids = set()
        almost_there_stage_ids = set()
        for s in stages:
            s_name = (s.name or '').strip().lower()
            if any(w in s_name for w in ['complete', 'finish']):
                completed_stage_ids.add(s.id)
            elif 'ready' in s_name:
                almost_there_stage_ids.add(s.id)

        # Fallbacks if stages have custom names:
        if not completed_stage_ids:
            if len(stages) >= 3:
                completed_stage_ids.add(stages[-1].id)
                if not almost_there_stage_ids:
                    almost_there_stage_ids.add(stages[-2].id)
            elif len(stages) == 2:
                completed_stage_ids.add(stages[-1].id)
                if not almost_there_stage_ids:
                    almost_there_stage_ids.add(stages[0].id)

        # Active orders in kitchen for this display and company
        active_orders = request.env['pos.kitchen.order'].sudo().search([
            ('display_id', '=', display.id),
            ('company_id', '=', display.company_id.id),
            ('active', '=', True),
        ], order='id asc')

        ready_orders = []
        prep_orders = []
        seen_refs = set()

        for o in active_orders:
            num = _get_display_number(o)
            if not num:
                continue
            order_info = {
                'id': o.id,
                'reference': num,
                'stage_id': o.stage_id.id,
                'stage_name': o.stage_id.name or '',
            }
            if o.stage_id.id in completed_stage_ids:
                # Food is completed by kitchen -> Display in READY for customer pickup
                if num not in seen_refs:
                    order_info['is_ready'] = True
                    ready_orders.append(order_info)
                    seen_refs.add(num)
            elif o.stage_id.id in almost_there_stage_ids:
                # Kitchen 'Ready' stage -> Display in ALMOST THERE for customer
                if num not in seen_refs:
                    order_info['is_ready'] = False
                    prep_orders.append(order_info)
                    seen_refs.add(num)
            # Orders in 'To cook' or other preliminary stages are intentionally not displayed on customer screen

        return {
            'ready': ready_orders,
            'preparing': prep_orders,
            'ready_title': "Ready",
            'prep_title': "Almost there",
            'stages': [{'id': s.id, 'name': s.name, 'is_ready': s.id in completed_stage_ids} for s in stages],
        }

    # ------------------------------------------------------------------
    # Virtual / Preview Order Printer handler for PoS testing
    # ------------------------------------------------------------------
    @http.route([
        '/hw_proxy/default_printer_action',
        '/hw_proxy/print_xml_receipt',
        '/hw_proxy/status',
        '/hw_proxy/status_json',
        '/hw_proxy/hello',
    ], type='json', auth='none', cors='*')
    def hw_proxy_action(self, **kwargs):
        return {'result': True, 'status': 'connected'}
