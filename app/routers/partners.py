from typing import Optional

import odoo
import pydantic
from fastapi import APIRouter, Depends
from odoo.api import Environment

from ..dependencies import odoo_env


class Partner(pydantic.BaseModel):
    id: Optional[int]
    name: str
    email: Optional[str]
    is_company: bool = False

    @classmethod
    def from_res_partner(cls, p: odoo.models.Model) -> "Partner":
        return Partner(id=p.id, name=p.name, email=p.email, is_company=p.is_company)


router = APIRouter(
    prefix="/partners",
    tags=["partners"],
    dependencies=[Depends(odoo_env)],
    responses={404: {"description": "Not found"}},
)


# TODO While environment dependency can be set at the router level,
# no easy way to get the env dependency from the routes themselves
# next(router.dependencies[0].dependency()) -> env but says cursor already closed
@router.get("/")
async def read_partners(
    is_company: Optional[bool] = None, env: Environment = Depends(odoo_env)
):
    domain = []
    if is_company is not None:
        domain.append(("is_company", "=", is_company))
    partners = env["res.partner"].search(domain)
    return [Partner.from_res_partner(p) for p in partners]


@router.get("/{partner_id}")
async def read_partner(partner_id: str, env: Environment = Depends(odoo_env)):
    domain = [("id", "=", partner_id)]
    partners = env["res.partner"].search(domain)
    return [Partner.from_res_partner(p) for p in partners]
