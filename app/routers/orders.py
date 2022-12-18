import logging
from datetime import date, datetime
from enum import Enum
from typing import Optional

import odoo
import pydantic
from fastapi import APIRouter, Depends, Query, Security
from fastapi_pagination import Page, paginate
from pydantic import Field

from .. import utils
from ..dependencies import User, get_current_active_user, get_odoo_user, odoo_env

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    responses={404: {"description": "Not found"}},
)


class PartnerDeliveryAddress(pydantic.BaseModel):
    name: str = None
    display_name: str = None
    company_name: str = None
    street: str = None
    street2: str = None
    zip: str = None
    city: str = None
    state_id: int = None
    country_id: int = None
    state: str = None
    country: str = None
    partner_latitude: float = None
    partner_longitude: float = None
    phone: str = None
    mobile: str = None
    display_address: str = None

    class Config:
        orm_mode = True
        getter_dict = utils.GenericOdooGetter


class Order(pydantic.BaseModel):
    id: int
    display_name: str
    # Order date. Creation date of draft/sent orders. Confirmation date of confirmed orders.
    date_order: datetime = Field(description="Confirmation date of confirmed orders.")
    # From `picking_ids`
    scheduled_date: datetime | None = Field(
        description="Scheduled time for the first part of the shipment to be processed. "
        "Setting manually a value here would set it as expected date for all the stock moves.",
    )
    date_deadline: datetime | None = Field(
        description="Date Promise to the customer on the top level document (SO/PO)"
    )
    # Expected Date. Delivery date you can promise to the customer,
    # computed from the minimum lead time of the order lines.
    expected_date: datetime | None = Field(
        default=None,
        description="Delivery date you can promise to the customer, "
        "computed from the minimum lead time of the order lines.",
    )
    # # Delivery Date. Delivery date promised to customer.  @NOTE For me, not reliable
    # commitment_date: datetime | None = Field(
    #     description="Delivery date promised to customer."
    # )
    # TODO Better documentation of fields by using custom `Field`
    state: str
    delivery_address: PartnerDeliveryAddress = None
    require_signature: bool = None
    signed_by: str = None
    signed_on: datetime = None
    validity_date: date = None
    note: str = None
    is_expired: bool = None
    amount_total: float = None
    # TODO Add order items

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
            rec_delivery_address = env["res.partner"].browse(delivery_address_id)
            delivery_address = PartnerDeliveryAddress.from_orm(rec_delivery_address)
            delivery_address.display_address = rec_delivery_address._display_address()
            delivery_address.state = rec_delivery_address.state_id.name or ""
            delivery_address.country = rec_delivery_address.country_id.name or ""
        return Order(
            id=p.id,
            display_name=p.display_name,
            date_order=p.date_order,
            scheduled_date=p.picking_ids.scheduled_date,
            date_deadline=p.picking_ids.date_deadline,
            expected_date=p.expected_date,
            # commitment_date=p.commitment_date if p.commitment_date else None,
            state=cls._state(p.picking_ids.state),
            delivery_address=delivery_address,
            require_signature=p.require_signature,
            signed_by=cls._null_for_false(p, "signed_by"),
            signed_on=p.signed_on,
            validity_date=p.validity_date,
            note=cls._null_for_false(p, "note"),
            is_expired=p.is_expired,
            amount_total=p.amount_total,
        )

    @classmethod
    def _state(cls, state):
        if not state:
            return "unassigned"
        return state

    @classmethod
    def _null_for_false(cls, order, key):
        field = order._fields[key]
        res = getattr(order, key, None)
        if not res and field.type != "boolean":
            return None


STATE_DESCRIPTION = """\
Must be one of the following:
- assigned
- waiting
- confirmed
- done
- cancelled
- unassigned
"""
# TODO Order by state

logger = logging.getLogger(__name__)


class PickingState(str, Enum):
    assigned = "assigned"
    waiting = "waiting"
    confirmed = "confirmed"
    done = "done"
    cancelled = "cancelled"
    unassigned = "unassigned"


@router.get("/", response_model=Page[Order])
async def list_orders(
    state: Optional[list[str]] = Query(
        default=[PickingState.assigned],
        choices=[s.value for s in PickingState],
        description=STATE_DESCRIPTION,
    ),
    env: odoo.api.Environment = Depends(odoo_env),
    current_user: User = Security(get_current_active_user, scopes=["orders:list"]),
):
    domain = []
    all_orders = env["sale.order"].search(domain)
    # Filtering from state
    show_unassigned = False
    if "unassigned" in state:
        state.pop(state.index("unassigned"))
        show_unassigned = True
    # Filtering other states should only include the user's
    __, odoo_user = get_odoo_user(current_user.username)
    orders = all_orders.filtered(
        lambda o: o.picking_ids.state in state
        and o.picking_ids.user_id.id == odoo_user.id
    )
    if show_unassigned:
        orders |= all_orders.filtered(lambda o: not o.picking_ids.state)
    # TODO Paginate `orders` instead?
    # TODO BUG size is returning length of array instead of matched states/query. total and size are both correct.
    return paginate([Order.from_sale_order(order, env) for order in orders])
