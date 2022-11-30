from datetime import datetime

import odoo
import pydantic
from fastapi import APIRouter, Depends, Query

from ..dependencies import odoo_env

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    responses={404: {"description": "Not found"}},
)


class Order(pydantic.BaseModel):
    id: int
    display_name: str
    date_order: datetime
    state: str

    @classmethod
    def from_sale_order(cls, p: odoo.models.Model) -> "Order":
        return Order(
            id=p.id,
            display_name=p.display_name,
            date_order=p.date_order,
            state=cls._state(p.picking_ids.state),
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
    return [Order.from_sale_order(order) for order in orders]
