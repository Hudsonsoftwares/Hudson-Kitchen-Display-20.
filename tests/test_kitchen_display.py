# -*- coding: utf-8 -*-
import json
import uuid
from odoo import fields
from odoo.tests.common import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestKitchenDisplayRoutingAndStages(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', cls.company.id)], limit=1
        )
        if not sale_journal:
            sale_journal = cls.env['account.journal'].create({
                'name': 'KDS Sale Test',
                'type': 'sale',
                'code': 'KDSS',
                'company_id': cls.company.id,
            })
        bank_journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1
        )
        if not bank_journal:
            bank_journal = cls.env['account.journal'].create({
                'name': 'KDS Bank Test',
                'type': 'bank',
                'code': 'KDSB',
                'company_id': cls.company.id,
            })
        cls.payment_method = cls.env['pos.payment.method'].search(
            [('journal_id', '=', bank_journal.id)], limit=1
        ) or cls.env['pos.payment.method'].create({
            'name': 'KDS Bank',
            'type': 'bank',
            'journal_id': bank_journal.id,
        })

        cls.pos_config = cls.env['pos.config'].create({
            'name': 'KDS Test Restaurant',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, cls.payment_method.id)],
            'module_pos_restaurant': True,
        })

        cls.cat_food = cls.env['pos.category'].create({'name': 'KDS Food'})
        cls.cat_drinks = cls.env['pos.category'].create({'name': 'KDS Drinks'})

        cls.burger = cls.env['product.product'].create({
            'name': 'KDS Cheese Burger',
            'type': 'consu',
            'available_in_pos': True,
            'pos_categ_ids': [(6, 0, [cls.cat_food.id])],
            'lst_price': 15.0,
            'taxes_id': [(5, 0, 0)],
        })
        cls.cola = cls.env['product.product'].create({
            'name': 'KDS Cola',
            'type': 'consu',
            'available_in_pos': True,
            'pos_categ_ids': [(6, 0, [cls.cat_drinks.id])],
            'lst_price': 5.0,
            'taxes_id': [(5, 0, 0)],
        })

    def _open_session(self):
        if not self.pos_config.current_session_id:
            self.pos_config.open_ui()
        return self.pos_config.current_session_id

    def test_multi_display_independent_delivery_and_duplicate_guards(self):
        """Orders reach all matching displays independently, keep repeat lines, and never duplicate Done tickets."""
        PrepDisplay = self.env['pos.prep.display']
        KitchenOrder = self.env['pos.kitchen.order'].with_context(active_test=False)

        # Simulate multi-display setup where displays are explicitly assigned to this POS
        d_food = PrepDisplay.create({
            'name': 'Demo Food Display',
            'pos_config_ids': [(6, 0, [self.pos_config.id])],
            'category_ids': [(6, 0, [self.cat_food.id])],
            'stage_ids': [
                (0, 0, {'name': 'New Order', 'sequence': 1}),
                (0, 0, {'name': 'Cooking', 'sequence': 2}),
                (0, 0, {'name': 'Ready to Serve', 'sequence': 3}),
                (0, 0, {'name': 'Served', 'sequence': 4}),
            ],
        })
        d_drinks = PrepDisplay.create({
            'name': 'Demo Drinks Display',
            'pos_config_ids': [(6, 0, [self.pos_config.id])],
            'category_ids': [(6, 0, [self.cat_drinks.id])],
        })
        d_pass = PrepDisplay.create({
            'name': 'Demo Expediter Display',
            'pos_config_ids': [(6, 0, [self.pos_config.id])],
            'stage_ids': [
                (0, 0, {'name': 'Waiting', 'sequence': 1}),
                (0, 0, {'name': 'Plating', 'sequence': 2}),
                (0, 0, {'name': 'Pass Ready', 'sequence': 3}),
                (0, 0, {'name': 'Dispatched', 'sequence': 4}),
            ],
        })
        d_user = PrepDisplay.create({
            'name': 'Main Kitchen',
            'pos_config_ids': [(6, 0, [self.pos_config.id])],
        })
        d_unassigned = PrepDisplay.create({
            'name': 'Unassigned Bar',
        })

        session = self._open_session()
        order = self.env['pos.order'].create({
            'name': 'KDS-001',
            'pos_reference': 'Order 001',
            'uuid': str(uuid.uuid4()),
            'session_id': session.id,
            'config_id': self.pos_config.id,
            'amount_tax': 0.0,
            'amount_total': 35.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [
                (0, 0, {
                    'product_id': self.burger.id,
                    'full_product_name': 'KDS Cheese Burger',
                    'qty': 1,
                    'price_unit': 15.0,
                    'price_subtotal': 15.0,
                    'price_subtotal_incl': 15.0,
                    'customer_note': 'No onions',
                }),
                (0, 0, {
                    'product_id': self.burger.id,
                    'full_product_name': 'KDS Cheese Burger',
                    'qty': 1,
                    'price_unit': 15.0,
                    'price_subtotal': 15.0,
                    'price_subtotal_incl': 15.0,
                    'customer_note': 'Extra cheese',
                }),
                (0, 0, {
                    'product_id': self.cola.id,
                    'full_product_name': 'KDS Cola',
                    'qty': 1,
                    'price_unit': 5.0,
                    'price_subtotal': 5.0,
                    'price_subtotal_incl': 5.0,
                }),
            ],
        })

        t_food = KitchenOrder.search([('pos_order_id', '=', order.id), ('display_id', '=', d_food.id)])
        t_drinks = KitchenOrder.search([('pos_order_id', '=', order.id), ('display_id', '=', d_drinks.id)])
        t_pass = KitchenOrder.search([('pos_order_id', '=', order.id), ('display_id', '=', d_pass.id)])
        t_user = KitchenOrder.search([('pos_order_id', '=', order.id), ('display_id', '=', d_user.id)])

        self.assertEqual(len(t_food), 1)
        self.assertEqual(sum(t_food.line_ids.mapped('qty')), 2.0, "Both burger lines must be sent to food display")
        self.assertEqual(len(t_drinks), 1)
        self.assertEqual(t_drinks.line_ids.product_id, self.cola)
        self.assertEqual(len(t_pass), 1)
        self.assertEqual(sum(t_pass.line_ids.mapped('qty')), 3.0)
        self.assertEqual(len(t_user), 1, "User's 4th Main Kitchen display must receive its ticket!")
        self.assertEqual(sum(t_user.line_ids.mapped('qty')), 3.0, "Main Kitchen must receive all 3 items")
        self.assertEqual(t_user.stage_id.name, 'To cook')
        self.assertEqual(
            KitchenOrder.search_count([('pos_order_id', '=', order.id), ('display_id', '=', d_unassigned.id)]),
            0,
            "Display with empty POS must receive 0 orders under strict POS matching",
        )

        # Mark user's Main Kitchen ticket as Done (active=False), then pay/update the POS order -> must NOT duplicate
        t_user.action_mark_done()
        self.assertFalse(t_user.active)
        order.write({
            'state': 'paid',
            'amount_paid': 35.0,
        })
        t_user_after = KitchenOrder.search([('pos_order_id', '=', order.id), ('display_id', '=', d_user.id)])
        self.assertEqual(len(t_user_after), 1, "Paying order after Done must NOT create a duplicate ticket")

        # Add a new Cola line -> only delta qty (1 Cola) sent as a new ticket on d_user and d_drinks/d_pass, 0 on d_food
        order.write({
            'lines': [(0, 0, {
                'product_id': self.cola.id,
                'full_product_name': 'KDS Cola',
                'qty': 1,
                'price_unit': 5.0,
                'price_subtotal': 5.0,
                'price_subtotal_incl': 5.0,
            })],
        })
        self.assertEqual(len(KitchenOrder.search([('pos_order_id', '=', order.id), ('display_id', '=', d_food.id)])), 1)
        t_user_all = KitchenOrder.search([('pos_order_id', '=', order.id), ('display_id', '=', d_user.id)], order='id asc')
        self.assertEqual(len(t_user_all), 2)
        self.assertEqual(t_user_all[1].line_ids.mapped('product_id'), self.cola)

    def test_custom_stage_batch_advance(self):
        """Batch advancing works on any stage index in a custom 4-stage display."""
        disp = self.env['pos.prep.display'].create({
            'name': 'Custom 4 Stage KDS',
            'stage_ids': [
                (0, 0, {'name': 'New Order', 'sequence': 1}),
                (0, 0, {'name': 'Cooking', 'sequence': 2}),
                (0, 0, {'name': 'Ready to Serve', 'sequence': 3}),
                (0, 0, {'name': 'Served', 'sequence': 4}),
            ],
        })
        stages = disp.stage_ids.sorted('sequence')
        k_order = self.env['pos.kitchen.order'].create({
            'display_id': disp.id,
            'stage_id': stages[0].id,
            'pos_reference': 'Custom-1',
            'line_ids': [(0, 0, {'product_id': self.burger.id, 'name': 'Burger', 'qty': 1})],
        })
        KitchenOrder = self.env['pos.kitchen.order']
        for i in range(3):
            res = KitchenOrder.action_batch_advance_stage(stages[i].id, display_id=disp.id)
            self.assertTrue(res['success'])
            self.assertEqual(k_order.stage_id, stages[i + 1])
        res_done = KitchenOrder.action_batch_advance_stage(stages[3].id, display_id=disp.id)
        self.assertTrue(res_done['success'])
        self.assertFalse(k_order.active)

    def test_default_display_created_on_install_and_modifiable(self):
        """Module install creates one editable default Kitchen Display and demo loader creates none."""
        from odoo.addons.hudson_kitchen_display import post_init_hook

        PrepDisplay = self.env['pos.prep.display']
        all_displays = PrepDisplay.search([])
        self.assertEqual(len(all_displays), 1, "Fresh install must create exactly one default display")
        default_disp = all_displays[0]
        self.assertEqual(default_disp.name, 'Kitchen Display')
        self.assertEqual(default_disp.stage_ids.sorted('sequence').mapped('name'), ['To cook', 'Ready', 'Completed'])
        company_configs = self.env['pos.config'].search([('company_id', '=', self.env.company.id)])
        pre_existing_configs = company_configs - self.pos_config
        self.assertEqual(default_disp.pos_config_ids, pre_existing_configs)
        self.assertFalse(default_disp.category_ids)

        # When pos.config records already exist on install, post_init_hook links them to the default display
        default_disp.unlink()
        post_init_hook(self.env)
        recreated = PrepDisplay.search([])
        self.assertEqual(len(recreated), 1)
        self.assertEqual(recreated.pos_config_ids, company_configs)
        default_disp = recreated

        # User can customize the default display to match their workflow
        default_disp.write({
            'name': 'Custom Main Kitchen',
            'pos_config_ids': [(6, 0, [self.pos_config.id])],
            'category_ids': [(6, 0, [self.cat_food.id])],
            'stage_ids': [
                (5, 0, 0),
                (0, 0, {'name': 'Prep', 'sequence': 1}),
                (0, 0, {'name': 'Plating', 'sequence': 2}),
                (0, 0, {'name': 'Done', 'sequence': 3}),
            ],
        })

        # Re-running hook does not overwrite edits or add duplicates
        post_init_hook(self.env)
        self.assertEqual(PrepDisplay.search_count([]), 1)
        self.assertEqual(default_disp.name, 'Custom Main Kitchen')
        self.assertEqual(default_disp.stage_ids.sorted('sequence').mapped('name'), ['Prep', 'Plating', 'Done'])

        # Demo loader stub must no longer create extra KDS displays
        from odoo.addons.hudson_pos_demo_data.models.demo_data_loader import _load_kitchen_display_demo_data
        _load_kitchen_display_demo_data(self.env)
        self.assertEqual(PrepDisplay.search_count([]), 1)

    def test_demo_migration_removes_only_demo_displays_and_unlink_handles_orders(self):
        """Migration removes legacy demo displays (with orders) while keeping user displays intact."""
        import importlib.util
        import os
        from odoo.modules import get_module_path

        mig_path = os.path.join(
            get_module_path('hudson_pos_demo_data'),
            'migrations', '20.0.1.0.2', 'post-migrate.py',
        )
        spec = importlib.util.spec_from_file_location('hudson_pos_demo_data_post_migrate_102', mig_path)
        post_migrate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(post_migrate)
        PrepDisplay = self.env['pos.prep.display']
        IrModelData = self.env['ir.model.data'].sudo()

        # Replace default display with 3 demo displays (having orders + logs) + 1 user display
        PrepDisplay.search([]).unlink()
        d_demo_1 = PrepDisplay.create({'name': 'Main Kitchen Display'})
        d_demo_2 = PrepDisplay.create({'name': 'Bar & Drinks Display'})
        d_user = PrepDisplay.create({'name': 'User Main Kitchen'})
        for xml_id, disp in [('kds_main_kitchen', d_demo_1), ('kds_bar_drinks', d_demo_2)]:
            IrModelData.create({
                'module': 'hudson_pos_demo_data',
                'name': xml_id,
                'model': 'pos.prep.display',
                'res_id': disp.id,
                'noupdate': True,
            })

        stages_1 = d_demo_1.stage_ids.sorted('sequence')
        k_ord = self.env['pos.kitchen.order'].create({
            'display_id': d_demo_1.id,
            'stage_id': stages_1[0].id,
            'pos_reference': 'Demo-Ord-1',
            'line_ids': [(0, 0, {'product_id': self.burger.id, 'name': 'Burger', 'qty': 1})],
        })
        k_ord.action_next_stage()  # creates stage log entry on stage_id FK

        # Migration removes ONLY tracked demo displays & their orders/logs; keeps User Main Kitchen
        post_migrate.migrate(self.env.cr, '20.0.1.0.1')
        remaining = PrepDisplay.search([])
        self.assertEqual(remaining, d_user)
        self.assertFalse(IrModelData.search([
            ('module', '=', 'hudson_pos_demo_data'),
            ('model', '=', 'pos.prep.display'),
        ]))

        # Deleting a display with orders/logs via unlink() directly also succeeds cleanly
        k_user_ord = self.env['pos.kitchen.order'].create({
            'display_id': d_user.id,
            'stage_id': d_user.stage_ids.sorted('sequence')[0].id,
            'pos_reference': 'User-Ord-1',
            'line_ids': [(0, 0, {'product_id': self.cola.id, 'name': 'Cola', 'qty': 1})],
        })
        k_user_ord.action_next_stage()
        d_user.unlink()
        self.assertFalse(PrepDisplay.search([]))

        # Case 2: if ONLY demo displays existed, migration recreates 1 editable 'Kitchen Display'
        d_demo_only = PrepDisplay.create({'name': 'Main Kitchen Display'})
        IrModelData.create({
            'module': 'hudson_pos_demo_data',
            'name': 'kds_main_kitchen',
            'model': 'pos.prep.display',
            'res_id': d_demo_only.id,
            'noupdate': True,
        })
        post_migrate.migrate(self.env.cr, '20.0.1.0.1')
        after_only = PrepDisplay.search([])
        self.assertEqual(len(after_only), 1)
        self.assertEqual(after_only.name, 'Kitchen Display')

    def test_non_kitchen_lines_excluded_and_cleanup_migration(self):
        """Discounts, tips, service fees, gift cards, and negative lines stay off KDS and cleanup migration purges legacy lines."""
        import importlib.util
        import os
        from odoo.modules import get_module_path

        tip_prod = self.env['product.product'].create({
            'name': 'KDS Tips',
            'type': 'service',
            'available_in_pos': True,
            'lst_price': 1.0,
            'taxes_id': [(5, 0, 0)],
        })
        if 'tip_product_id' in self.pos_config._fields:
            self.pos_config.write({'tip_product_id': tip_prod.id})

        disc_prod = self.env['product.product'].create({
            'name': '15% Off All Orders',
            'type': 'service',
            'available_in_pos': False,
            'lst_price': 0.0,
            'taxes_id': [(5, 0, 0)],
        })
        gift_prod = None
        if 'loyalty.program' in self.env and 'loyalty.reward' in self.env:
            gift_prod = self.env['product.product'].create({
                'name': 'Gift Card',
                'type': 'service',
                'available_in_pos': True,
                'lst_price': 50.0,
                'taxes_id': [(5, 0, 0)],
            })
            self.env['loyalty.program'].create({
                'name': 'Test Gift Card',
                'program_type': 'gift_card',
                'trigger_product_ids': [(6, 0, [gift_prod.id])],
            })

        disp = self.env['pos.prep.display'].search([], limit=1)
        disp.write({'pos_config_ids': [(6, 0, [self.pos_config.id])], 'category_ids': [(5, 0, 0)]})
        session = self._open_session()

        order_lines = [
            (0, 0, {
                'product_id': self.burger.id,
                'full_product_name': 'KDS Cheese Burger',
                'qty': 1,
                'price_unit': 15.0,
                'price_subtotal': 15.0,
                'price_subtotal_incl': 15.0,
            }),
            (0, 0, {
                'product_id': tip_prod.id,
                'full_product_name': 'KDS Tips',
                'qty': 1,
                'price_unit': 2.0,
                'price_subtotal': 2.0,
                'price_subtotal_incl': 2.0,
            }),
            (0, 0, {
                'product_id': disc_prod.id,
                'full_product_name': '15% Off All Orders',
                'qty': 1,
                'price_unit': -2.25,
                'price_subtotal': -2.25,
                'price_subtotal_incl': -2.25,
            }),
        ]

        if 'loyalty.program' in self.env and 'loyalty.reward' in self.env:
            prog = self.env['loyalty.program'].create({
                'name': 'Test Loyalty',
                'program_type': 'loyalty',
            })
            rew_disc = self.env['loyalty.reward'].create({
                'program_id': prog.id,
                'reward_type': 'discount',
                'discount': 10.0,
                'discount_line_product_id': disc_prod.id,
            })
            rew_free = self.env['loyalty.reward'].create({
                'program_id': prog.id,
                'reward_type': 'product',
                'reward_product_id': self.cola.id,
            })
            order_lines.append((0, 0, {
                'product_id': self.cola.id,
                'full_product_name': 'KDS Cola (Free)',
                'qty': 1,
                'price_unit': 0.0,
                'price_subtotal': 0.0,
                'price_subtotal_incl': 0.0,
                'is_reward_line': True,
                'reward_id': rew_free.id,
            }))
            # Simulate a positive-price reward deduction line edge case via reward_id
            order_lines.append((0, 0, {
                'product_id': disc_prod.id,
                'full_product_name': 'Reward Deduction',
                'qty': 1,
                'price_unit': 0.0,
                'price_subtotal': 0.0,
                'price_subtotal_incl': 0.0,
                'is_reward_line': True,
                'reward_id': rew_disc.id,
            }))

        pos_order = self.env['pos.order'].create({
            'name': 'KDS-DISC-01',
            'pos_reference': 'Order DISC-01',
            'uuid': str(uuid.uuid4()),
            'session_id': session.id,
            'config_id': self.pos_config.id,
            'amount_tax': 0.0,
            'amount_total': 14.75,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': order_lines,
        })

        tickets = self.env['pos.kitchen.order'].search([('pos_order_id', '=', pos_order.id)])
        self.assertEqual(len(tickets), 1)
        sent_products = tickets.line_ids.mapped('product_id')
        self.assertIn(self.burger, sent_products)
        self.assertNotIn(tip_prod, sent_products)
        self.assertNotIn(disc_prod, sent_products)
        if 'loyalty.reward' in self.env:
            self.assertIn(self.cola, sent_products, "Free product loyalty reward must still reach KDS")

        # Test migration cleanup on legacy KDS tickets created before filter existed
        mig_path = os.path.join(
            get_module_path('hudson_kitchen_display'),
            'migrations', '20.0.1.0.1', 'post-migrate.py',
        )
        spec = importlib.util.spec_from_file_location('hudson_kitchen_display_post_migrate_101', mig_path)
        post_migrate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(post_migrate)

        first_stage = disp.stage_ids.sorted('sequence')[:1]
        legacy_mixed = self.env['pos.kitchen.order'].create({
            'display_id': disp.id,
            'stage_id': first_stage.id,
            'pos_order_id': pos_order.id,
            'pos_reference': 'Legacy-Mixed',
            'line_ids': [
                (0, 0, {'product_id': self.burger.id, 'name': 'Burger', 'qty': 1}),
                (0, 0, {'product_id': tip_prod.id, 'name': 'KDS Tips', 'qty': 1}),
                (0, 0, {'product_id': disc_prod.id, 'name': '15% Off All Orders', 'qty': 1}),
            ],
        })
        empty_lines = [(0, 0, {'product_id': tip_prod.id, 'name': 'KDS Tips', 'qty': 1})]
        if gift_prod:
            empty_lines.append((0, 0, {'product_id': gift_prod.id, 'name': 'Gift Card', 'qty': 1}))
        legacy_only_non_kitchen = self.env['pos.kitchen.order'].create({
            'display_id': disp.id,
            'stage_id': first_stage.id,
            'pos_reference': 'Legacy-Empty',
            'line_ids': empty_lines,
        })
        legacy_only_non_kitchen.action_next_stage()  # creates stage log to verify clean cascade/unlink

        post_migrate.migrate(self.env.cr, '20.0.1.0.0')
        self.assertTrue(legacy_mixed.exists())
        self.assertEqual(legacy_mixed.line_ids.mapped('product_id'), self.burger)
        self.assertFalse(legacy_only_non_kitchen.exists(), "Ticket left with only non-kitchen lines must be removed")

    def test_pos_config_isolation_and_no_retroactive_paid_push(self):
        """POS config isolation never leaks to other displays and paying old orders does not flood newer displays."""
        PrepDisplay = self.env['pos.prep.display']
        KitchenOrder = self.env['pos.kitchen.order'].with_context(active_test=False)
        # Clear default All display so we test strict per-POS routing
        PrepDisplay.search([]).unlink()

        sale_journal = self.env['account.journal'].search([('type', '=', 'sale')], limit=1)
        bank_journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        pm = self.env['pos.payment.method'].search([('journal_id', '=', bank_journal.id)], limit=1)

        cfg_bar = self.env['pos.config'].create({
            'name': 'KDS Bar POS',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, pm.id)] if pm else [],
        })
        cfg_other = self.env['pos.config'].create({
            'name': 'KDS Other POS',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, pm.id)] if pm else [],
        })

        d_rest = PrepDisplay.create({
            'name': 'Main Kitchen Only',
            'pos_config_ids': [(6, 0, [self.pos_config.id])],
        })
        d_bar = PrepDisplay.create({
            'name': 'Bar Only',
            'pos_config_ids': [(6, 0, [cfg_bar.id])],
        })

        session_rest = self._open_session()
        order_rest = self.env['pos.order'].create({
            'name': 'REST-001',
            'pos_reference': 'Order REST-001',
            'uuid': str(uuid.uuid4()),
            'session_id': session_rest.id,
            'config_id': self.pos_config.id,
            'amount_tax': 0.0,
            'amount_total': 15.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.burger.id,
                'full_product_name': 'KDS Cheese Burger',
                'qty': 1,
                'price_unit': 15.0,
                'price_subtotal': 15.0,
                'price_subtotal_incl': 15.0,
            })],
        })
        self.assertEqual(KitchenOrder.search_count([('pos_order_id', '=', order_rest.id), ('display_id', '=', d_rest.id)]), 1)
        self.assertEqual(KitchenOrder.search_count([('pos_order_id', '=', order_rest.id), ('display_id', '=', d_bar.id)]), 0)

        # Unmatched POS (cfg_other) must NOT fall back and leak into d_rest or d_bar
        cfg_other.open_ui()
        order_other = self.env['pos.order'].create({
            'name': 'OTH-001',
            'pos_reference': 'Order OTH-001',
            'uuid': str(uuid.uuid4()),
            'session_id': cfg_other.current_session_id.id,
            'config_id': cfg_other.id,
            'amount_tax': 0.0,
            'amount_total': 5.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': self.cola.id,
                'full_product_name': 'KDS Cola',
                'qty': 1,
                'price_unit': 5.0,
                'price_subtotal': 5.0,
                'price_subtotal_incl': 5.0,
            })],
        })
        self.assertEqual(KitchenOrder.search_count([('pos_order_id', '=', order_other.id)]), 0)

        # Backdate initial rest ticket, then create:
        # 1) an unassigned display (empty POS) -> must NEVER receive orders
        # 2) a brand-new assigned display -> paying order_rest must NOT push old items onto it
        rest_ticket = KitchenOrder.search([('pos_order_id', '=', order_rest.id), ('display_id', '=', d_rest.id)], limit=1)
        self.env.cr.execute(
            "UPDATE pos_kitchen_order SET create_date = (NOW() AT TIME ZONE 'UTC') - INTERVAL '10 minutes' WHERE id = %s",
            [rest_ticket.id],
        )
        rest_ticket.invalidate_recordset(['create_date'])
        d_empty = PrepDisplay.create({'name': 'Bar Unassigned'})
        d_later = PrepDisplay.create({
            'name': 'Late Assigned Kitchen',
            'pos_config_ids': [(6, 0, [self.pos_config.id])],
        })
        order_rest.write({'state': 'paid', 'amount_paid': 15.0})
        self.assertEqual(KitchenOrder.search_count([('pos_order_id', '=', order_rest.id), ('display_id', '=', d_empty.id)]), 0)
        self.assertEqual(KitchenOrder.search_count([('pos_order_id', '=', order_rest.id), ('display_id', '=', d_later.id)]), 0)


@tagged('post_install', '-at_install')
class TestKitchenDisplayHttpRoutes(HttpCase):

    def test_send_to_kitchen_then_sync_does_not_duplicate_and_renders_dynamic_ui(self):
        """HTTP /send_to_kitchen followed by PosOrder.create shares uuid tracking cleanly and UI renders dynamically."""
        sale_journal = self.env['account.journal'].search([('type', '=', 'sale')], limit=1)
        bank_journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        pm = self.env['pos.payment.method'].search([('journal_id', '=', bank_journal.id)], limit=1)
        if not pm:
            pm = self.env['pos.payment.method'].create({
                'name': 'Bank',
                'type': 'bank',
                'journal_id': bank_journal.id,
            })
        cfg = self.env['pos.config'].create({
            'name': 'HTTP KDS Restaurant',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, pm.id)],
            'module_pos_restaurant': True,
        })
        cfg.open_ui()
        session = cfg.current_session_id
        prod = self.env['product.product'].create({
            'name': 'HTTP KDS Pasta',
            'type': 'consu',
            'available_in_pos': True,
            'lst_price': 20.0,
            'taxes_id': [(5, 0, 0)],
        })
        d1 = self.env['pos.prep.display'].create({
            'name': 'Demo Display Custom',
            'pos_config_ids': [(6, 0, [cfg.id])],
            'stage_ids': [
                (0, 0, {'name': 'Queue', 'sequence': 1}),
                (0, 0, {'name': 'Prep', 'sequence': 2}),
                (0, 0, {'name': 'Pass', 'sequence': 3}),
                (0, 0, {'name': 'Served', 'sequence': 4}),
            ],
        })
        d2 = self.env['pos.prep.display'].create({
            'name': 'Main Kitchen HTTP',
            'pos_config_ids': [(6, 0, [cfg.id])],
        })
        d_unassigned_http = self.env['pos.prep.display'].create({
            'name': 'Bar Unassigned HTTP',
        })

        user = self.env['res.users'].create({
            'name': 'KDS HTTP User',
            'login': 'kds_http_user',
            'password': 'kds_http_user',
            'group_ids': [(6, 0, [self.env.ref('point_of_sale.group_pos_manager').id])],
        })
        self.authenticate(user.login, 'kds_http_user')

        order_uid = str(uuid.uuid4())
        resp = self.url_open(
            '/hudson_kitchen_display/send_to_kitchen',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'order_data': {
                        'pos_reference': 'Order 777',
                        'order_uid': order_uid,
                        'config_id': cfg.id,
                        'session_id': session.id,
                        'company_id': cfg.company_id.id,
                        'table_name': '5',
                        'customer_count': 2,
                        'fulfillment_type': 'dine_in',
                        'lines': [{
                            'product_id': prod.id,
                            'name': prod.display_name,
                            'qty': 1,
                            'note': 'Hot',
                            'course_name': 'Main Course',
                        }],
                    }
                },
                'id': 1,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(resp.status_code, 200)
        res_json = resp.json().get('result', {})
        self.assertTrue(res_json.get('ok'))

        KitchenOrder = self.env['pos.kitchen.order'].with_context(active_test=False)
        self.assertEqual(KitchenOrder.search_count([('order_uid', '=', order_uid), ('display_id', '=', d1.id)]), 1)
        self.assertEqual(KitchenOrder.search_count([('order_uid', '=', order_uid), ('display_id', '=', d2.id)]), 1)
        self.assertEqual(KitchenOrder.search_count([('order_uid', '=', order_uid), ('display_id', '=', d_unassigned_http.id)]), 0)

        # Now sync POS order with the same uuid -> must link without creating duplicate tickets!
        pos_order = self.env['pos.order'].create({
            'name': 'Order 777',
            'pos_reference': 'Order 777',
            'uuid': order_uid,
            'session_id': session.id,
            'config_id': cfg.id,
            'amount_tax': 0.0,
            'amount_total': 20.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': prod.id,
                'full_product_name': 'HTTP KDS Pasta',
                'qty': 1,
                'price_unit': 20.0,
                'price_subtotal': 20.0,
                'price_subtotal_incl': 20.0,
            })],
        })
        self.assertEqual(KitchenOrder.search_count([('pos_order_id', '=', pos_order.id), ('display_id', '=', d1.id)]), 1)
        self.assertEqual(KitchenOrder.search_count([('pos_order_id', '=', pos_order.id), ('display_id', '=', d2.id)]), 1)

        # Verify /hudson_kitchen_display/get_orders returns all 4 custom stages dynamically
        orders_resp = self.url_open(
            '/hudson_kitchen_display/get_orders',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {'display_id': d1.id},
                'id': 2,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(orders_resp.status_code, 200)
        orders_data = orders_resp.json().get('result', {})
        self.assertEqual([s['name'] for s in orders_data['stages']], ['Queue', 'Prep', 'Pass', 'Served'])
        self.assertEqual(len(orders_data['orders']), 1)

        # Add extra out-of-order tickets to verify /get_orders returns natural ascending order
        stage_q = d1.stage_ids.sorted('sequence')[:1]
        extra_tickets = KitchenOrder.create([
            {
                'display_id': d1.id,
                'stage_id': stage_q.id,
                'table_name': '1019',
                'pos_reference': 'Order 1019',
                'line_ids': [(0, 0, {'product_id': prod.id, 'name': prod.name, 'qty': 1})],
            },
            {
                'display_id': d1.id,
                'stage_id': stage_q.id,
                'table_name': '1003',
                'pos_reference': 'Order 1003',
                'line_ids': [(0, 0, {'product_id': prod.id, 'name': prod.name, 'qty': 1})],
            },
            {
                'display_id': d1.id,
                'stage_id': stage_q.id,
                'table_name': '9',
                'pos_reference': 'Order 9',
                'line_ids': [(0, 0, {'product_id': prod.id, 'name': prod.name, 'qty': 1})],
            },
            {
                'display_id': d1.id,
                'stage_id': stage_q.id,
                'table_name': '1010',
                'pos_reference': 'Order 1010',
                'line_ids': [(0, 0, {'product_id': prod.id, 'name': prod.name, 'qty': 1})],
            },
        ])
        orders_resp_sorted = self.url_open(
            '/hudson_kitchen_display/get_orders',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {'display_id': d1.id},
                'id': 20,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(orders_resp_sorted.status_code, 200)
        disp_nums = [
            o['display_number']
            for o in orders_resp_sorted.json()['result']['orders']
            if o['id'] in extra_tickets.ids
        ]
        self.assertEqual(disp_nums, ['9', '1003', '1010', '1019'])
        extra_tickets.unlink()

        # Verify web HTML page renders cleanly with dynamic tab + grid ascending layout logic
        page_resp = self.url_open(f'/hudson_kitchen_display/web?display_id={d1.id}')
        self.assertEqual(page_resp.status_code, 200)
        html = page_resp.text
        self.assertIn('stages.forEach((s, idx) =>', html)
        self.assertNotIn('data-tab="to_cook"', html)
        self.assertIn('kd-masonry', html)
        self.assertIn('compareOrdersAscending', html)
        self.assertIn('grid-template-columns', html)
        self.assertIn('getColumnCount', html)
        self.assertNotIn('min-width: 275px;', html)

        # Verify backend Kanban CSS asset is served with full-width 2-column grid rule
        css_resp = self.url_open('/hudson_kitchen_display/static/src/css/pos_prep_display_backend.css')
        self.assertEqual(css_resp.status_code, 200)
        self.assertIn('repeat(2, minmax(0, 1fr))', css_resp.text)
        self.assertIn('o_prep_display_kanban', css_resp.text)

        # Verify HTTP /send_to_kitchen filters out non-kitchen lines and skips empty non-kitchen-only orders
        disc_http_prod = self.env['product.product'].create({
            'name': 'HTTP 20% Off',
            'type': 'service',
            'available_in_pos': False,
            'lst_price': 0.0,
            'taxes_id': [(5, 0, 0)],
        })
        tip_http_prod = self.env['product.product'].create({
            'name': 'HTTP Tip',
            'type': 'service',
            'available_in_pos': True,
            'lst_price': 1.0,
            'taxes_id': [(5, 0, 0)],
        })
        if 'tip_product_id' in cfg._fields:
            cfg.write({'tip_product_id': tip_http_prod.id})

        uid_mixed = str(uuid.uuid4())
        mixed_resp = self.url_open(
            '/hudson_kitchen_display/send_to_kitchen',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'order_data': {
                        'pos_reference': 'Order MIXED',
                        'order_uid': uid_mixed,
                        'config_id': cfg.id,
                        'session_id': session.id,
                        'company_id': cfg.company_id.id,
                        'table_name': '8',
                        'customer_count': 2,
                        'fulfillment_type': 'dine_in',
                        'lines': [
                            {'product_id': prod.id, 'name': 'HTTP KDS Pasta', 'qty': 1, 'price_unit': 20.0},
                            {'product_id': prod.id, 'name': 'Free Pasta Reward', 'qty': 1, 'is_reward_line': True, 'reward_type': 'product', 'price_unit': 0.0},
                            {'product_id': disc_http_prod.id, 'name': '20% Off All', 'qty': 1, 'is_reward_line': True, 'reward_type': 'discount', 'price_unit': -4.0},
                            {'product_id': tip_http_prod.id, 'name': 'HTTP Tip', 'qty': 1, 'is_tip_line': True, 'price_unit': 2.0},
                            {'product_id': prod.id, 'name': 'eWallet Topup', 'qty': 1, 'is_payment_program': True, 'price_unit': 10.0},
                        ],
                    }
                },
                'id': 3,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(mixed_resp.status_code, 200)
        self.assertTrue(mixed_resp.json().get('result', {}).get('ok'))
        mixed_tickets = KitchenOrder.search([('order_uid', '=', uid_mixed), ('display_id', '=', d2.id)])
        self.assertEqual(len(mixed_tickets), 1)
        self.assertEqual(sum(mixed_tickets.line_ids.mapped('qty')), 2.0, "Only Pasta + Free Pasta Reward should appear")
        self.assertNotIn(disc_http_prod, mixed_tickets.line_ids.mapped('product_id'))
        self.assertNotIn(tip_http_prod, mixed_tickets.line_ids.mapped('product_id'))

        # Non-kitchen only order must create 0 tickets
        uid_non_kitchen = str(uuid.uuid4())
        empty_resp = self.url_open(
            '/hudson_kitchen_display/send_to_kitchen',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'order_data': {
                        'pos_reference': 'Order DISC ONLY',
                        'order_uid': uid_non_kitchen,
                        'config_id': cfg.id,
                        'session_id': session.id,
                        'company_id': cfg.company_id.id,
                        'lines': [
                            {'product_id': disc_http_prod.id, 'name': '15% Off', 'qty': 1, 'is_reward_line': True, 'reward_type': 'discount', 'price_unit': -3.0},
                            {'product_id': tip_http_prod.id, 'name': 'HTTP Tip', 'qty': 1, 'is_tip_line': True, 'price_unit': 2.0},
                        ],
                    }
                },
                'id': 4,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(empty_resp.status_code, 200)
        empty_res = empty_resp.json().get('result', {})
        self.assertTrue(empty_res.get('ok'))
        self.assertEqual(KitchenOrder.search_count([('order_uid', '=', uid_non_kitchen)]), 0)

    def test_http_send_to_kitchen_pos_isolation(self):
        """HTTP /send_to_kitchen resolves config via session_id when omitted and never leaks to other POS displays."""
        PrepDisplay = self.env['pos.prep.display']
        KitchenOrder = self.env['pos.kitchen.order'].with_context(active_test=False)
        PrepDisplay.search([]).unlink()

        sale_journal = self.env['account.journal'].search([('type', '=', 'sale')], limit=1)
        bank_journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        pm = self.env['pos.payment.method'].search([('journal_id', '=', bank_journal.id)], limit=1)
        if not pm:
            pm = self.env['pos.payment.method'].create({
                'name': 'Bank Iso',
                'type': 'bank',
                'journal_id': bank_journal.id,
            })

        cfg_rest = self.env['pos.config'].create({
            'name': 'HTTP Rest POS',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, pm.id)],
            'module_pos_restaurant': True,
        })
        cfg_cafe = self.env['pos.config'].create({
            'name': 'HTTP Cafe POS',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, pm.id)],
        })
        cfg_unmapped = self.env['pos.config'].create({
            'name': 'HTTP Unmapped POS',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, pm.id)],
        })
        cfg_rest.open_ui()
        cfg_unmapped.open_ui()

        d_rest = PrepDisplay.create({'name': 'Rest Display', 'pos_config_ids': [(6, 0, [cfg_rest.id])]})
        d_cafe = PrepDisplay.create({'name': 'Cafe Display', 'pos_config_ids': [(6, 0, [cfg_cafe.id])]})

        prod = self.env['product.product'].create({
            'name': 'HTTP Iso Soup',
            'type': 'consu',
            'available_in_pos': True,
            'lst_price': 10.0,
            'taxes_id': [(5, 0, 0)],
        })

        user = self.env['res.users'].create({
            'name': 'KDS Iso HTTP User',
            'login': 'kds_iso_http_user',
            'password': 'kds_iso_http_user',
            'group_ids': [(6, 0, [self.env.ref('point_of_sale.group_pos_manager').id])],
        })
        self.authenticate(user.login, 'kds_iso_http_user')

        # Omit config_id -> must resolve via session_id and hit ONLY d_rest
        uid_sess_only = str(uuid.uuid4())
        r1 = self.url_open(
            '/hudson_kitchen_display/send_to_kitchen',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'order_data': {
                        'pos_reference': 'Order ISO-1',
                        'order_uid': uid_sess_only,
                        'config_id': False,
                        'session_id': cfg_rest.current_session_id.id,
                        'company_id': cfg_rest.company_id.id,
                        'lines': [{'product_id': prod.id, 'name': 'HTTP Iso Soup', 'qty': 1, 'price_unit': 10.0}],
                    }
                },
                'id': 11,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json().get('result', {}).get('ok'))
        self.assertEqual(KitchenOrder.search_count([('order_uid', '=', uid_sess_only), ('display_id', '=', d_rest.id)]), 1)
        self.assertEqual(KitchenOrder.search_count([('order_uid', '=', uid_sess_only), ('display_id', '=', d_cafe.id)]), 0)

        # Unmapped POS -> must return ok with 0 tickets and NOT leak to d_rest or d_cafe
        uid_unmapped = str(uuid.uuid4())
        r2 = self.url_open(
            '/hudson_kitchen_display/send_to_kitchen',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'order_data': {
                        'pos_reference': 'Order ISO-2',
                        'order_uid': uid_unmapped,
                        'config_id': cfg_unmapped.id,
                        'session_id': cfg_unmapped.current_session_id.id,
                        'company_id': cfg_unmapped.company_id.id,
                        'lines': [{'product_id': prod.id, 'name': 'HTTP Iso Soup', 'qty': 1, 'price_unit': 10.0}],
                    }
                },
                'id': 12,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(r2.status_code, 200)
        res2 = r2.json().get('result', {})
        self.assertTrue(res2.get('ok'))
        self.assertEqual(res2.get('prep_order_ids'), [])
        self.assertEqual(KitchenOrder.search_count([('order_uid', '=', uid_unmapped)]), 0)


@tagged('post_install', '-at_install')
class TestSelfOrderKitchenStatusTracking(HttpCase):

    def test_qr_mobile_order_tracks_3_stages_strictly_scoped_per_customer(self):
        """QR Ordering (mobile) routes to KDS, tracks all 3 stages per order, and enforces strict token isolation."""
        sale_journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', self.env.company.id)], limit=1
        )
        bank_journal = self.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', self.env.company.id)], limit=1
        )
        pm = self.env['pos.payment.method'].search([('journal_id', '=', bank_journal.id)], limit=1)
        if not pm:
            pm = self.env['pos.payment.method'].create({
                'name': 'Self Bank',
                'type': 'bank',
                'journal_id': bank_journal.id,
            })

        pos_user = self.env['res.users'].search([
            ('group_ids', 'in', [self.env.ref('point_of_sale.group_pos_manager').id]),
            ('company_id', '=', self.env.company.id),
        ], limit=1) or self.env.user

        cfg = self.env['pos.config'].create({
            'name': 'QR Mobile Restaurant',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, pm.id)],
            'module_pos_restaurant': True,
            'self_ordering_mode': 'mobile',
            'self_ordering_service_mode': 'table',
            'self_ordering_pay_after': 'meal',
            'self_ordering_default_user_id': pos_user.id,
        })
        cfg.write({
            'self_ordering_mode': 'mobile',
            'self_ordering_service_mode': 'table',
            'self_ordering_pay_after': 'meal',
        })
        floor = self.env['restaurant.floor'].create({
            'name': 'QR Floor',
            'pos_config_ids': [(4, cfg.id)],
        })
        table_a = self.env['restaurant.table'].create({
            'floor_id': floor.id,
            'table_number': 5,
            'seats': 4,
        })
        table_b = self.env['restaurant.table'].create({
            'floor_id': floor.id,
            'table_number': 9,
            'seats': 4,
        })

        cat_food = self.env['pos.category'].create({'name': 'QR Food'})
        cat_drinks = self.env['pos.category'].create({'name': 'QR Drinks'})
        burger = self.env['product.product'].create({
            'name': 'QR Smash Burger',
            'type': 'consu',
            'available_in_pos': True,
            'pos_categ_ids': [(6, 0, [cat_food.id])],
            'lst_price': 12.0,
            'taxes_id': [(5, 0, 0)],
        })
        drink = self.env['product.product'].create({
            'name': 'QR Lime Soda',
            'type': 'consu',
            'available_in_pos': True,
            'pos_categ_ids': [(6, 0, [cat_drinks.id])],
            'lst_price': 4.0,
            'taxes_id': [(5, 0, 0)],
        })

        self.env['pos.prep.display'].search([]).unlink()
        d_kitchen = self.env['pos.prep.display'].create({
            'name': 'Main Kitchen',
            'pos_config_ids': [(6, 0, [cfg.id])],
            'category_ids': [(6, 0, [cat_food.id])],
        })
        d_bar = self.env['pos.prep.display'].create({
            'name': 'Bar',
            'pos_config_ids': [(6, 0, [cfg.id])],
            'category_ids': [(6, 0, [cat_drinks.id])],
        })

        cfg.open_ui()
        session = cfg.current_session_id

        def _place_qr_order(table, product, order_uuid):
            resp = self.url_open(
                '/pos-self-order/process-order/mobile',
                data=json.dumps({
                    'jsonrpc': '2.0',
                    'method': 'call',
                    'params': {
                        'access_token': cfg.access_token,
                        'table_identifier': table.identifier,
                        'order': {
                            'uuid': order_uuid,
                            'session_id': session.id,
                            'sequence_number': 1,
                            'amount_tax': 0.0,
                            'amount_total': product.lst_price,
                            'amount_paid': 0.0,
                            'amount_return': 0.0,
                            'customer_count': 2,
                            'preset_id': cfg.default_preset_id.id if cfg.use_presets and cfg.default_preset_id else False,
                            'lines': [[0, 0, {
                                'product_id': product.id,
                                'full_product_name': product.name,
                                'qty': 1,
                                'price_unit': product.lst_price,
                                'price_subtotal': product.lst_price,
                                'price_subtotal_incl': product.lst_price,
                                'uuid': str(uuid.uuid4()),
                            }]],
                        },
                    },
                    'id': 101,
                }),
                headers={'Content-Type': 'application/json'},
            )
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertNotIn('error', payload, f"Unexpected RPC error placing self-order: {payload}")
            order_data = payload['result']['pos.order'][0]
            return self.env['pos.order'].browse(order_data['id'])

        order_a = _place_qr_order(table_a, burger, str(uuid.uuid4()))
        order_b = _place_qr_order(table_b, drink, str(uuid.uuid4()))

        KitchenOrder = self.env['pos.kitchen.order'].with_context(active_test=False)
        t_a = KitchenOrder.search([('pos_order_id', '=', order_a.id), ('display_id', '=', d_kitchen.id)])
        t_b = KitchenOrder.search([('pos_order_id', '=', order_b.id), ('display_id', '=', d_bar.id)])
        self.assertEqual(len(t_a), 1)
        self.assertEqual(t_a.table_name, 'T5')
        self.assertEqual(t_a.fulfillment_type, 'dine_in')
        self.assertEqual(t_a.stage_id.name, 'To cook')
        self.assertEqual(len(t_b), 1)

        def _fetch_status(req_orders, cfg_token=None):
            r = self.url_open(
                '/pos-self-order/kitchen-status',
                data=json.dumps({
                    'jsonrpc': '2.0',
                    'method': 'call',
                    'params': {
                        'access_token': cfg_token if cfg_token is not None else cfg.access_token,
                        'orders': req_orders,
                    },
                    'id': 202,
                }),
                headers={'Content-Type': 'application/json'},
            )
            self.assertEqual(r.status_code, 200)
            return r.json()

        # Customer A queries ONLY their own order AND tries probing Customer B's order with invalid/A's token
        res_1 = _fetch_status([
            {'id': order_a.id, 'access_token': order_a.access_token},
            {'id': order_b.id, 'access_token': order_a.access_token},
            {'id': order_b.id, 'access_token': 'forged-token'},
        ])
        self.assertNotIn('error', res_1)
        statuses_1 = res_1['result']['statuses']
        self.assertEqual(list(statuses_1.keys()), [order_a.access_token], "Must ONLY return token-verified Customer A order")
        self.assertNotIn(order_b.access_token, statuses_1)

        st_a = statuses_1[order_a.access_token]
        self.assertTrue(st_a['has_kitchen'])
        self.assertFalse(st_a['is_cancelled'])
        self.assertEqual(st_a['summary_label'], 'To cook')
        self.assertEqual(
            [(s['name'], s['state']) for s in st_a['displays'][0]['stages']],
            [('To cook', 'active'), ('Ready', 'pending'), ('Completed', 'pending')],
        )

        # Invalid pos.config access_token must be refused
        bad_cfg_res = _fetch_status([{'id': order_a.id, 'access_token': order_a.access_token}], cfg_token='wrong-pos-token')
        self.assertIn('error', bad_cfg_res)

        # Advance Kitchen ticket A -> Stage 2 (Ready), AND mark POS order paid (Done/Paid in My Orders!)
        t_a.action_next_stage()
        order_a.write({'state': 'paid', 'amount_paid': 12.0})
        statuses_2 = _fetch_status([{'id': order_a.id, 'access_token': order_a.access_token}])['result']['statuses']
        st_a2 = statuses_2[order_a.access_token]
        self.assertEqual(st_a2['summary_label'], 'Ready')
        self.assertEqual(
            [(s['name'], s['state']) for s in st_a2['displays'][0]['stages']],
            [('To cook', 'done'), ('Ready', 'active'), ('Completed', 'pending')],
        )

        # Customer B is STILL unaffected (independent isolation)
        statuses_b = _fetch_status([{'id': order_b.id, 'access_token': order_b.access_token}])['result']['statuses']
        self.assertEqual(statuses_b[order_b.access_token]['summary_label'], 'To cook')

        # Advance Kitchen ticket A -> Stage 3 (Completed)
        t_a.action_next_stage()
        statuses_3 = _fetch_status([{'id': order_a.id, 'access_token': order_a.access_token}])['result']['statuses']
        st_a3 = statuses_3[order_a.access_token]
        self.assertEqual(st_a3['summary_label'], 'Completed')
        self.assertEqual(
            [(s['name'], s['state']) for s in st_a3['displays'][0]['stages']],
            [('To cook', 'done'), ('Ready', 'done'), ('Completed', 'active')],
        )

        # Kitchen marks ticket A Done (archived) -> cleared from active batches & displays, status stays Completed
        t_a.action_mark_done()
        statuses_4 = _fetch_status([{'id': order_a.id, 'access_token': order_a.access_token}])['result']['statuses']
        st_a4 = statuses_4[order_a.access_token]
        self.assertTrue(st_a4['is_served_done'])
        self.assertEqual(st_a4['summary_label'], 'Completed')
        self.assertFalse(st_a4['has_kitchen'])
        self.assertEqual(st_a4['batches'], [])
        self.assertEqual(st_a4['displays'], [])

        # Cancelling order B archives its active kitchen ticket and reports is_cancelled=True
        order_b.write({'state': 'cancel'})
        self.assertFalse(t_b.active)
        statuses_b_cancel = _fetch_status([{'id': order_b.id, 'access_token': order_b.access_token}])['result']['statuses']
        self.assertTrue(statuses_b_cancel[order_b.access_token]['is_cancelled'])
        self.assertFalse(statuses_b_cancel[order_b.access_token]['has_kitchen'])

        # Verify Pay After = Each Order (table QR) also sets T5 + dine_in properly on KDS
        cfg.write({'self_ordering_pay_after': 'each'})
        order_each = _place_qr_order(table_a, burger, str(uuid.uuid4()))
        t_each = KitchenOrder.search([('pos_order_id', '=', order_each.id), ('display_id', '=', d_kitchen.id)])
        self.assertEqual(len(t_each), 1)
        self.assertEqual(t_each.table_name, 'T5')
        self.assertEqual(t_each.fulfillment_type, 'dine_in')

        # Verify self-order mobile page + pos_self_order.assets bundle renders cleanly (no SCSS/XML/xpath failures)
        page = self.url_open(f'/pos-self/{cfg.id}?access_token={cfg.access_token}&table_identifier={table_a.identifier}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('pos_self_order', page.text)
        import re
        js_match = re.search(r'(/web/assets/[^"\']+pos_self_order\.assets[^"\']*\.js)', page.text)
        css_match = re.search(r'(/web/assets/[^"\']+pos_self_order\.assets[^"\']*\.css)', page.text)
        self.assertIsNotNone(js_match, "pos_self_order JS asset bundle URL missing from page HTML")
        self.assertIsNotNone(css_match, "pos_self_order CSS asset bundle URL missing from page HTML")
        js_resp = self.url_open(js_match.group(1))
        css_resp = self.url_open(css_match.group(1))
        self.assertEqual(js_resp.status_code, 200)
        self.assertEqual(css_resp.status_code, 200)
        self.assertIn('hudson_kitchen_display.KitchenOrderStatusCard', js_resp.text)
        self.assertIn('kitchenStatusByToken', js_resp.text)
        self.assertIn('hkd_self_status_box', css_resp.text)
        self.assertIn('hkd_self_cat_group', css_resp.text)
        self.assertIn('hkd_self_live_dot', css_resp.text)
        self.assertIn('hkd_self_status_station--cook', css_resp.text)
        self.assertIn('hkd_self_chevron', css_resp.text)
        self.assertIn('hkd_self_status_station--expanded', css_resp.text)
        self.assertIn('getBatchTitle', js_resp.text)
        self.assertIn('toggleBatch', js_resp.text)
        self.assertIn('isBatchExpanded', js_resp.text)
        # Ensure Odoo 20 Owl 3 reactive primitive (proxy) is used instead of removed Owl 2 useState
        hkd_idx = js_resp.text.find('KitchenOrderStatusCard')
        self.assertGreater(hkd_idx, -1)
        self.assertNotIn('useState', js_resp.text[max(0, hkd_idx - 200):hkd_idx + 1200])

    def test_single_step_stage_guards_and_multi_batch_category_tracking(self):
        """Regression test for:
        1) Line toggle + expected_stage_id guard never double-jumps (To cook -> Ready -> Completed).
        2) Multi-round pay_after='meal' QR orders track per-order batches & POS categories independently.
        """
        sale_journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', self.env.company.id)], limit=1
        )
        bank_journal = self.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', self.env.company.id)], limit=1
        )
        pm = self.env['pos.payment.method'].search([('journal_id', '=', bank_journal.id)], limit=1)
        if not pm:
            pm = self.env['pos.payment.method'].create({
                'name': 'MultiBatch Bank',
                'type': 'bank',
                'journal_id': bank_journal.id,
            })

        pos_user = self.env['res.users'].search([
            ('login', '=', 'kds_iso_http_user'),
        ], limit=1)
        if not pos_user:
            pos_user = self.env['res.users'].create({
                'name': 'KDS MultiBatch User',
                'login': 'kds_multibatch_user',
                'password': 'kds_multibatch_user',
                'group_ids': [(6, 0, [self.env.ref('point_of_sale.group_pos_manager').id])],
            })
        else:
            pos_user.write({'password': 'kds_multibatch_user'})

        cfg = self.env['pos.config'].create({
            'name': 'QR MultiBatch Resto',
            'journal_id': sale_journal.id,
            'closing_journal_id': sale_journal.id,
            'payment_method_ids': [(4, pm.id)],
            'module_pos_restaurant': True,
            'self_ordering_mode': 'mobile',
            'self_ordering_service_mode': 'table',
            'self_ordering_pay_after': 'meal',
            'self_ordering_default_user_id': pos_user.id,
        })
        cfg.write({
            'self_ordering_mode': 'mobile',
            'self_ordering_service_mode': 'table',
            'self_ordering_pay_after': 'meal',
        })
        floor = self.env['restaurant.floor'].create({
            'name': 'Batch Floor',
            'pos_config_ids': [(4, cfg.id)],
        })
        table = self.env['restaurant.table'].create({
            'floor_id': floor.id,
            'table_number': 6,
            'seats': 4,
        })

        cat_food = self.env['pos.category'].create({'name': 'Food'})
        cat_drinks = self.env['pos.category'].create({'name': 'Drinks'})
        cat_choc = self.env['pos.category'].create({'name': 'Chocolates & Sweets'})

        burger = self.env['product.product'].create({
            'name': 'Cheese Burger',
            'type': 'consu',
            'available_in_pos': True,
            'pos_categ_ids': [(6, 0, [cat_food.id])],
            'lst_price': 10.0,
            'taxes_id': [(5, 0, 0)],
        })
        drink = self.env['product.product'].create({
            'name': 'Minute Maid',
            'type': 'consu',
            'available_in_pos': True,
            'pos_categ_ids': [(6, 0, [cat_drinks.id])],
            'lst_price': 3.0,
            'taxes_id': [(5, 0, 0)],
        })
        choc = self.env['product.product'].create({
            'name': 'Luxury Chocolate Box',
            'type': 'consu',
            'available_in_pos': True,
            'pos_categ_ids': [(6, 0, [cat_choc.id])],
            'lst_price': 20.0,
            'taxes_id': [(5, 0, 0)],
        })

        self.env['pos.prep.display'].search([]).unlink()
        display = self.env['pos.prep.display'].create({
            'name': 'Main Kitchen',
            'pos_config_ids': [(6, 0, [cfg.id])],
        })
        stages = list(display.stage_ids.sorted('sequence'))
        self.assertEqual([s.name for s in stages], ['To cook', 'Ready', 'Completed'])
        st_cook, st_ready, st_comp = stages[0], stages[1], stages[2]

        cfg.open_ui()
        session = cfg.current_session_id

        # Round 1 via self-order mobile endpoint (creates pos.order + ticket #1)
        order_uuid = str(uuid.uuid4())
        r1 = self.url_open(
            '/pos-self-order/process-order/mobile',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'access_token': cfg.access_token,
                    'table_identifier': table.identifier,
                    'order': {
                        'uuid': order_uuid,
                        'session_id': session.id,
                        'sequence_number': 1,
                        'amount_tax': 0.0,
                        'amount_total': 13.0,
                        'amount_paid': 0.0,
                        'amount_return': 0.0,
                        'customer_count': 2,
                        'lines': [
                            [0, 0, {
                                'product_id': burger.id,
                                'full_product_name': burger.name,
                                'qty': 1,
                                'price_unit': 10.0,
                                'price_subtotal': 10.0,
                                'price_subtotal_incl': 10.0,
                                'uuid': str(uuid.uuid4()),
                            }],
                            [0, 0, {
                                'product_id': drink.id,
                                'full_product_name': drink.name,
                                'qty': 1,
                                'price_unit': 3.0,
                                'price_subtotal': 3.0,
                                'price_subtotal_incl': 3.0,
                                'uuid': str(uuid.uuid4()),
                            }],
                        ],
                    },
                },
                'id': 301,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(r1.status_code, 200)
        order_id = r1.json()['result']['pos.order'][0]['id']
        pos_order = self.env['pos.order'].browse(order_id)

        KitchenOrder = self.env['pos.kitchen.order'].with_context(active_test=False)
        t1 = KitchenOrder.search([('pos_order_id', '=', pos_order.id)], order='id asc')
        self.assertEqual(len(t1), 1)
        self.assertEqual(len(t1.line_ids), 2)

        # Authenticate as kitchen user and test single-step /toggle_line + /change_stage guard
        self.authenticate(pos_user.login, 'kds_multibatch_user')

        def _rpc(url, params):
            resp = self.url_open(
                url,
                data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}),
                headers={'Content-Type': 'application/json'},
            )
            self.assertEqual(resp.status_code, 200)
            return resp.json().get('result')

        l1, l2 = t1.line_ids.sorted('id')[0], t1.line_ids.sorted('id')[1]
        tog1 = _rpc('/hudson_kitchen_display/toggle_line', {'line_id': l1.id})
        self.assertTrue(tog1['ok'])
        self.assertTrue(tog1['is_done'])
        self.assertFalse(tog1['advanced'])
        self.assertEqual(t1.stage_id.id, st_cook.id)

        # Toggling final line must advance strictly ONE stage (To cook -> Ready, NOT Completed!)
        tog2 = _rpc('/hudson_kitchen_display/toggle_line', {'line_id': l2.id})
        self.assertTrue(tog2['ok'])
        self.assertFalse(tog2['advanced'] is False)
        self.assertEqual(tog2['stage_id'], st_ready.id)
        t1.invalidate_recordset()
        self.assertEqual(t1.stage_id.id, st_ready.id, "Must advance only 1 stage to Ready, never auto-jump to Completed")

        # Striking every item while the ticket is in Ready completes it (one stage: Ready -> Completed);
        # the items are un-struck when the order moves to Completed
        res_ready = _rpc('/hudson_kitchen_display/toggle_line', {'line_id': l1.id})
        self.assertTrue(res_ready['is_done'])
        self.assertFalse(res_ready['advanced'])
        res_ready = _rpc('/hudson_kitchen_display/toggle_line', {'line_id': l2.id})
        self.assertTrue(res_ready['advanced'])
        self.assertEqual(res_ready['stage_id'], st_comp.id)
        t1.invalidate_recordset()
        self.assertEqual(t1.stage_id.id, st_comp.id, "Striking every item in Ready completes the order")
        self.assertFalse(any(t1.line_ids.mapped('is_done')), "Items are not auto-struck when the order is completed")
        # back to Ready with items un-struck so the rest of this test starts from the same state
        t1.write({'stage_id': st_ready.id})
        t1.line_ids.write({'is_done': False})

        # Duplicate/stale change_stage carrying expected_stage_id=To cook must be rejected!
        stale_res = _rpc('/hudson_kitchen_display/change_stage', {
            'order_id': t1.id,
            'stage_id': st_comp.id,
            'expected_stage_id': st_cook.id,
        })
        self.assertFalse(stale_res, "Stale expected_stage_id transition must be ignored")
        t1.invalidate_recordset()
        self.assertEqual(t1.stage_id.id, st_ready.id)

        # Valid change_stage from Ready -> Completed succeeds, then mark done (Served)
        ok_res = _rpc('/hudson_kitchen_display/change_stage', {
            'order_id': t1.id,
            'stage_id': st_comp.id,
            'expected_stage_id': st_ready.id,
        })
        self.assertTrue(ok_res)
        t1.invalidate_recordset()
        self.assertEqual(t1.stage_id.id, st_comp.id)
        t1.action_mark_done()

        # Round 2 appended onto the SAME pos.order (pay_after='meal' table flow)
        pos_order.write({
            'amount_total': 33.0,
            'lines': [(0, 0, {
                'product_id': choc.id,
                'full_product_name': choc.name,
                'qty': 1,
                'price_unit': 20.0,
                'price_subtotal': 20.0,
                'price_subtotal_incl': 20.0,
                'uuid': str(uuid.uuid4()),
            })],
        })
        # Round 3 appended onto the SAME pos.order
        pos_order.write({
            'amount_total': 46.0,
            'lines': [
                (0, 0, {
                    'product_id': burger.id,
                    'full_product_name': burger.name,
                    'qty': 1,
                    'price_unit': 10.0,
                    'price_subtotal': 10.0,
                    'price_subtotal_incl': 10.0,
                    'uuid': str(uuid.uuid4()),
                }),
                (0, 0, {
                    'product_id': drink.id,
                    'full_product_name': drink.name,
                    'qty': 1,
                    'price_unit': 3.0,
                    'price_subtotal': 3.0,
                    'price_subtotal_incl': 3.0,
                    'uuid': str(uuid.uuid4()),
                }),
            ],
        })

        all_tix = KitchenOrder.search([('pos_order_id', '=', pos_order.id)], order='id asc')
        self.assertEqual(len(all_tix), 3)
        t2, t3 = all_tix[1], all_tix[2]
        # Leave t2 on To cook, advance t3 to Ready
        t3.action_next_stage()
        self.assertEqual(t2.stage_id.id, st_cook.id)
        self.assertEqual(t3.stage_id.id, st_ready.id)

        # Verify KDS /get_orders includes batch metadata + category metadata on lines
        kds_data = _rpc('/hudson_kitchen_display/get_orders', {'display_id': display.id})
        active_by_id = {o['id']: o for o in kds_data['orders'] if o['id'] in (t2.id, t3.id)}
        self.assertEqual(active_by_id[t2.id]['batch_number'], 2)
        self.assertEqual(active_by_id[t2.id]['batch_total'], 3)
        self.assertEqual(active_by_id[t3.id]['batch_number'], 3)
        self.assertEqual(active_by_id[t3.id]['batch_total'], 3)
        self.assertEqual(sorted(l['category_name'] for l in active_by_id[t3.id]['lines']), ['Drinks', 'Food'])

        # Verify /pos-self-order/kitchen-status returns ONLY currently active batches (served batch #1 cleared!)
        self.authenticate(None, None)
        st_payload = _rpc('/pos-self-order/kitchen-status', {
            'access_token': cfg.access_token,
            'orders': [{'id': pos_order.id, 'access_token': pos_order.access_token}],
        })
        st = st_payload['statuses'][pos_order.access_token]
        self.assertTrue(st['has_kitchen'])
        batches = st['batches']
        self.assertEqual(len(batches), 2)
        self.assertEqual([b['batch_number'] for b in batches], [2, 3])
        self.assertEqual([b['current_stage_name'] for b in batches], ['To cook', 'Ready'])
        self.assertEqual([c['category_name'] for c in batches[0]['categories']], ['Chocolates & Sweets'])
        self.assertEqual([c['category_name'] for c in batches[1]['categories']], ['Drinks', 'Food'])
        self.assertEqual(
            [c['category_name'] for c in st['categories']],
            ['Chocolates & Sweets', 'Drinks', 'Food'],
        )

        # Marking all remaining batches Done clears the active tracker cleanly
        t2.action_mark_done()
        t3.action_mark_done()
        st_done_payload = _rpc('/pos-self-order/kitchen-status', {
            'access_token': cfg.access_token,
            'orders': [{'id': pos_order.id, 'access_token': pos_order.access_token}],
        })
        st_done = st_done_payload['statuses'][pos_order.access_token]
        self.assertFalse(st_done['has_kitchen'])
        self.assertTrue(st_done['is_served_done'])
        self.assertEqual(st_done['summary_label'], 'Completed')
        self.assertEqual(st_done['batches'], [])
        self.assertEqual(st_done['displays'], [])

        # Verify configuring Kitchen Display categories (excluding Drinks) skips Drinks-only orders
        display.write({'category_ids': [(6, 0, [cat_food.id, cat_choc.id])]})
        table_drinks = self.env['restaurant.table'].create({
            'floor_id': floor.id,
            'table_number': 7,
            'seats': 2,
        })
        drinks_only_r = self.url_open(
            '/pos-self-order/process-order/mobile',
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'call',
                'params': {
                    'access_token': cfg.access_token,
                    'table_identifier': table_drinks.identifier,
                    'order': {
                        'uuid': str(uuid.uuid4()),
                        'session_id': session.id,
                        'sequence_number': 2,
                        'amount_tax': 0.0,
                        'amount_total': 3.0,
                        'amount_paid': 0.0,
                        'amount_return': 0.0,
                        'customer_count': 1,
                        'lines': [
                            [0, 0, {
                                'product_id': drink.id,
                                'full_product_name': drink.name,
                                'qty': 1,
                                'price_unit': 3.0,
                                'price_subtotal': 3.0,
                                'price_subtotal_incl': 3.0,
                                'uuid': str(uuid.uuid4()),
                            }],
                        ],
                    },
                },
                'id': 302,
            }),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(drinks_only_r.status_code, 200)
        drink_order_id = drinks_only_r.json()['result']['pos.order'][0]['id']
        drink_order = self.env['pos.order'].browse(drink_order_id)
        self.assertEqual(KitchenOrder.search_count([('pos_order_id', '=', drink_order.id)]), 0)
        st_drink_payload = _rpc('/pos-self-order/kitchen-status', {
            'access_token': cfg.access_token,
            'orders': [{'id': drink_order.id, 'access_token': drink_order.access_token}],
        })
        st_drink = st_drink_payload['statuses'][drink_order.access_token]
        self.assertFalse(st_drink['has_kitchen'])
        self.assertEqual(st_drink['batches'], [])
        self.assertEqual(st_drink['displays'], [])

        # Verify self-order My Orders HTML + bundled pos_self_order.assets JS have no Owl2 useState regression
        orders_page_resp = self.url_open(f'/pos-self/{cfg.id}/orders?access_token={cfg.access_token}&table_identifier={table.identifier}')
        self.assertEqual(orders_page_resp.status_code, 200)
        import os as _os, re as _re
        js_path = _os.path.join(_os.path.dirname(__file__), '..', 'static', 'src', 'self_order', 'kitchen_status_tracker.js')
        with open(js_path, 'r', encoding='utf-8') as f_js:
            js_src = f_js.read()
        self.assertIn('proxy', js_src)
        self.assertNotIn('useState', js_src, "Odoo 20 @odoo/owl (Owl 3) does not export useState; use proxy()")
        bundle_urls = _re.findall(r'/web/assets/[^"\'\s<>]+pos_self_order[^"\'\s<>]+\.js', orders_page_resp.text)
        self.assertTrue(bundle_urls, "Expected pos_self_order JS bundle URL on My Orders page")
        bundle_resp = self.url_open(bundle_urls[0])
        self.assertEqual(bundle_resp.status_code, 200)
        self.assertIn('KitchenOrderStatusCard', bundle_resp.text)
        idx_card = bundle_resp.text.find('KitchenOrderStatusCard')
        self.assertNotIn('useState', bundle_resp.text[max(0, idx_card - 300):idx_card + 600])






