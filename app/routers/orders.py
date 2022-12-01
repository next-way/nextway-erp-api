from datetime import datetime

import odoo
import pydantic
from fastapi import APIRouter, Depends, Query

from .. import utils
from ..dependencies import odoo_env

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    responses={404: {"description": "Not found"}},
)


class PartnerDeliveryAddress(pydantic.BaseModel):
    street: str = None
    street2: str = None
    zip: str = None
    city: str = None
    state_id: int = None  # State name
    country_id: int = None  # Country name

    class Config:
        orm_mode = True
        getter_dict = utils.GenericOdooGetter


class Order(pydantic.BaseModel):
    id: int
    display_name: str
    date_order: datetime
    state: str
    delivery_address: PartnerDeliveryAddress = None

    @classmethod
    def from_sale_order(
        cls, p: odoo.models.Model, env: odoo.api.Environment
    ) -> "Order":
        delivery_address_id = (
            p.partner_shipping_id.address_get(["delivery"])["delivery"]
            if p.partner_id
            else None
        )
        delivery_address = None
        if delivery_address_id:
            delivery_address = PartnerDeliveryAddress.from_orm(
                env["res.partner"].browse(delivery_address_id)
            )
            # delivery_address = env["res.partner"].browse(delivery_address_id)
        return Order(
            id=p.id,
            display_name=p.display_name,
            date_order=p.date_order,
            state=cls._state(p.picking_ids.state),
            delivery_address=delivery_address,
        )

    @classmethod
    def _state(cls, state):
        if not state:
            return "unassigned"
        return state


STATE_DESCRIPTION = """\
Must be one of the following:
- assigned
- waiting
- confirmed
- done
- cancelled
- unassigned
"""


@router.get("/")
async def list_orders(
    state: list[str]
    | None = Query(default=["assigned"], description=STATE_DESCRIPTION),
    env: odoo.api.Environment = Depends(odoo_env),
):
    domain = []
    all_orders = env["sale.order"].search(domain)
    # Filtering from state
    show_unassigned = False
    if "unassigned" in state:
        state.pop(state.index("unassigned"))
        show_unassigned = True
    orders = all_orders.filtered(lambda o: o.picking_ids.state in state)
    if show_unassigned:
        orders += all_orders.filtered(lambda o: not o.picking_ids.state)
    return [Order.from_sale_order(order, env) for order in orders]
