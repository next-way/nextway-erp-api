# from https://github.com/acsone/odooxp2021-fastapi/blob/master/odoo_fastapi_demo/deps.py
import os

import odoo
from odoo.api import Environment


def odoo_env() -> Environment:
    #
    # /!\ With Odoo < 15 you need to wrap all this in 'with
    #     Environment.manage()' and apply this Odoo patch:
    #     https://github.com/odoo/odoo/pull/70398, to properly handle context
    #     locals in an async program.
    #
    # check_signaling() is to refresh the registry and cache when needed.
    # HACK: when running API outside of docker network where Odoo is running
    if odoo.tools.config["db_host"] == "host.docker.internal":
        odoo.tools.config["db_host"] = "0.0.0.0"
        if "DEV_ADDONS_PATH" in os.environ:
            odoo.tools.config["addons_path"] += "," + os.environ["DEV_ADDONS_PATH"]
    registry = odoo.registry(odoo.tools.config["db_name"]).check_signaling()
    # manage_change() is to signal other instances when the registry or cache
    # needs refreshing.
    with registry.manage_changes():
        # The cursor context manager commits unless there is an exception.
        with registry.cursor() as cr:
            try:
                ctx = Environment(cr, odoo.SUPERUSER_ID, {})["res.users"].context_get()
            except Exception as e:
                ctx = {"lang": "en_US"}
            yield Environment(cr, odoo.SUPERUSER_ID, ctx)
