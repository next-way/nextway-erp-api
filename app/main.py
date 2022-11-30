from typing import List, Optional

import odoo
from fastapi import Depends, FastAPI
from odoo.api import Environment
from odoo.models import Model
from pydantic import BaseModel

from .dependencies import odoo_env

# Follows https://fastapi.tiangolo.com/tutorial/bigger-applications/
# Follows https://github.com/acsone/odooxp2021-fastapi/blob/master/odoo_fastapi_demo/app.py

app = FastAPI()


@app.on_event("startup")
def initialize_odoo() -> None:
    # Read Odoo config from $ODOO_RC.
    odoo.tools.config.parse_config([])


@app.get("/")
async def root():
    return {"message": "Hello World"}


class Partner(BaseModel):
    id: Optional[int]
    name: str
    email: Optional[str]
    is_company: bool = False

    @classmethod
    def from_res_partner(cls, p: Model) -> "Partner":
        return Partner(id=p.id, name=p.name, email=p.email, is_company=p.is_company)


@app.get("/partners", response_model=List[Partner])
def partners(is_company: Optional[bool] = None, env: Environment = Depends(odoo_env)):
    domain = []
    if is_company is not None:
        domain.append(("is_company", "=", is_company))
    partners = env["res.partner"].search(domain)
    return [Partner.from_res_partner(p) for p in partners]
