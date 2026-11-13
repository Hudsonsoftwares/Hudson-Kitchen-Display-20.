from . import utils
from . import models
from . import controllers


def post_init_hook(env):
    """Create a single editable default Kitchen Display on module install."""
    PrepDisplay = env['pos.prep.display'].sudo()
    if not PrepDisplay.search([], limit=1):
        configs = env['pos.config'].sudo().search([('company_id', '=', env.company.id)])
        PrepDisplay.create({
            'name': 'Kitchen Display',
            'company_id': env.company.id,
            'pos_config_ids': [(6, 0, configs.ids)] if configs else False,
        })

