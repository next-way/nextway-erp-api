import odoo
from fastapi import FastAPI

from .routers import partners

# Follows https://fastapi.tiangolo.com/tutorial/bigger-applications/
# Follows https://github.com/acsone/odooxp2021-fastapi/blob/master/odoo_fastapi_demo/app.py

app = FastAPI()


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


app.include_router(partners.router)
