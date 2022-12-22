import logging
from os import path

import odoo
from fastapi import FastAPI
from fastapi_pagination import add_pagination

from .routers import authentication, orders, stats

# Follows https://fastapi.tiangolo.com/tutorial/bigger-applications/
# Follows https://github.com/acsone/odooxp2021-fastapi/blob/master/odoo_fastapi_demo/app.py

log_file_path = path.join(path.dirname(path.abspath(__file__)), "logging.conf")
logging.config.fileConfig(log_file_path, disable_existing_loggers=False)

app = FastAPI(
    title="Nextway ERP API",
    description="API for the Nextway ERP. Exposed here are services related to sale orders module (more coming soon).",
)


@app.on_event("startup")
def set_default_executor() -> None:
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    loop = asyncio.get_running_loop()
    # Tune this according to your requirements !
    loop.set_default_executor(ThreadPoolExecutor(max_workers=5))


@app.on_event("startup")
def initialize_odoo() -> None:
    # Read Odoo config from $ODOO_RC.
    odoo.tools.config.parse_config([])


app.include_router(authentication.router)
# TODO Consider removing partners/ completely. Only here to test unprotected API endpoint
# app.include_router(partners.router)
app.include_router(orders.router)
app.include_router(stats.router)

# Must be added last
add_pagination(app)
