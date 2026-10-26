{
    'name': 'Kitchen Display System (Custom KDS)',
    'version': '20.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Kitchen Display / Preparation Display for Odoo Community',
    'description': """
Custom Kitchen Display System for Odoo Community Edition
==========================================================
Recreates the core workflow of the Enterprise "Preparation Display" app
so restaurants on Community Edition can run a kitchen screen without an
Enterprise subscription.

Features
--------
* Configurable displays: pick which Point of Sale(s) and product
  categories feed each screen (e.g. Grill screen, Bar screen).
* Configurable stages per display (To cook / Ready / Completed, or your
  own names), each with an optional "late" alert timer.
* Touch-friendly, responsive kitchen screen (phone/tablet/TV) with All /
  stage tabs, time filters (Now / Today / Tomorrow / Next days) and
  fulfillment filters (Dine In / Takeout / Delivery), zoom controls,
  Recall, Undo (previous stage), dark & high-contrast modes, and audio
  alerts for new/late orders.
* Near real-time updates via bus.bus push, with polling as a safety net.
* Public customer-facing order-status page (big "Ready" / "Almost
  there" style screen) driven by a per-order access token.
* Orders are sent to the kitchen automatically when a POS order is
  created; a manual "resend" action covers items added later (e.g.
  kiosk/self-order flows).
* Kitchen Order History report (list/pivot/graph) with per-order prep
  duration for manager auditing and average-time analysis.
* "Kitchen Screen Access" user flag for kitchen-only logins that aren't
  full POS users.

See README.md in this folder for setup notes and known limitations.
""",
    'author': 'Hudson Softwares',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'pos_restaurant'],
    'data': [
        'security/ir.access.csv',
        'views/pos_prep_display_views.xml',
        'views/pos_prep_order_views.xml',
        'views/pos_order_views.xml',
        'views/res_users_views.xml',
        'views/pos_preparation_time_report_views.xml',
        'views/pos_prep_display_menus.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_kitchen_display/static/src/css/pos_prep_display_backend.css',
        ],
        'web.assets_frontend': [
            'hudson_kitchen_display/static/src/css/kitchen_display.css',
            'hudson_kitchen_display/static/src/js/kitchen_display.js',
            'hudson_kitchen_display/static/src/js/order_status.js',
        ],
        'point_of_sale._assets_pos': [
            'hudson_kitchen_display/static/src/css/pos_actions_modal.css',
            'hudson_kitchen_display/static/src/app/**/*',
        ],
    },
    'installable': True,
    'application': True,
}
