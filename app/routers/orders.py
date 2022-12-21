import logging
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

import odoo
import pydantic
from fastapi import APIRouter, Depends, HTTPException, Query, Security
from fastapi_pagination import Page, paginate
from odoo import _
from pydantic import BaseModel, Field

from .. import utils
from ..dependencies import User, get_current_active_user, get_odoo_user, odoo_env

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    responses={404: {"description": "Not found"}},
)


class OrderLine(pydantic.BaseModel):
    order_id: int
    name: str
    product_id: int
    product_uom_qty: float
    product_uom_name: str = None
    discount: float
    price_unit: float
    price_tax: float
    price_subtotal: float
    qty_delivered: float
    qty_invoiced: float
    qty_to_invoice: float
    invoice_status: str

    class Config:
        orm_mode = True
        getter_dict = utils.GenericOdooGetter


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
    order_lines: List[OrderLine] = None

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
            delivery_address.partner_latitude = (
                delivery_address.partner_latitude or p.partner_id.partner_latitude
            )
            delivery_address.partner_longitude = (
                delivery_address.partner_longitude or p.partner_id.partner_longitude
            )

        def get_order_line(ol):
            sale_order_line = OrderLine.from_orm(ol)
            sale_order_line.product_uom_name = ol.product_uom.display_name
            return sale_order_line

        order_lines = [get_order_line(ol) for ol in p.order_line]
        return Order(
            id=p.id,
            display_name=p.display_name,
            date_order=p.date_order,
            scheduled_date=p.picking_ids.scheduled_date,
            date_deadline=p.picking_ids.date_deadline,
            expected_date=p.expected_date,
            # commitment_date=p.commitment_date if p.commitment_date else None,
            state=cls._state(p, p.picking_ids.state),
            delivery_address=delivery_address,
            require_signature=p.require_signature,
            signed_by=cls._null_for_false(p, "signed_by"),
            signed_on=p.signed_on,
            validity_date=p.validity_date,
            note=cls._null_for_false(p, "note"),
            is_expired=p.is_expired,
            amount_total=p.amount_total,
            order_lines=order_lines,
        )

    @classmethod
    def _state(cls, order, state):
        if not state or (
            state == PickingState.assigned and order.picking_ids.user_id.id is False
        ):
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


CANCELLABLE_ORDER_PICKING_STATES = (PickingState.assigned,)


class OrderNotFoundException(Exception):
    pass


def get_order_obj(order_id: int, env: odoo.api.Environment, current_user: User):
    __, odoo_user = get_odoo_user(current_user.username)
    order_obj = env["sale.order"].browse(order_id).with_user(odoo_user)
    error_header = None
    if not order_obj.exists():
        error_header = "Order does not exist"
    elif len(order_obj.picking_ids) == 0:
        # Must have picking already
        error_header = "Order must have picking"
    if error_header:
        raise OrderNotFoundException(error_header)
    return order_obj


@router.post("/{order_id}/accept")
async def accept(
    order_id: int,
    env: odoo.api.Environment = Depends(odoo_env),
    current_user: User = Security(get_current_active_user, scopes=["orders:post"]),
):
    """Accept order job. Only for unassigned orders."""
    __, odoo_user = get_odoo_user(current_user.username)
    try:
        order_obj = get_order_obj(order_id, env, current_user)
    except OrderNotFoundException as e:
        return HTTPException(
            status_code=404, detail="Order not found", headers={"X-Error": str(e)}
        )
    else:
        # More validations
        error_header = None
        if (
            order_obj.picking_ids.user_id.id is not False
            and order_obj.picking_ids.user_id.id != odoo.SUPERUSER_ID
        ):
            # Already assigned (and is not Odoo bot)
            error_header = "Order can't be self-assigned"
        if order_obj.picking_ids.user_id.id == odoo_user.id:
            # Already assigned to driver
            error_header = "Order already assigned to driver"
        if error_header:
            return HTTPException(
                status_code=404,
                detail="Order not found",
                headers={"X-Error": error_header},
            )

    picking = order_obj.picking_ids
    # Log self-assignment on the picking
    message = _(
        "Self-assign delivery responsible by %(user_name)s (#%(user_id)s) on %(timestamp)s",
        user_name=current_user.username,
        user_id=odoo_user.id,
        timestamp=datetime.now().isoformat(),
    )
    picking._message_log(body=message)
    # Log self-assignment on the order
    order_obj._message_log(body=message)
    # Self-assign driver to picking
    picking.write({"user_id": odoo_user.id})
    return {"object_id": order_obj.id}


class DropOffRequestBody(BaseModel):
    drop_off_datetime: Optional[datetime]
    collection_datetime: Optional[datetime]
    message: Optional[str]


@router.post("/{order_id}/drop-off")
async def drop_off(
    order_id: int,
    request_body: DropOffRequestBody,
    env: odoo.api.Environment = Depends(odoo_env),
    current_user: User = Security(get_current_active_user, scopes=["orders:post"]),
):
    """Drop off job. Driver arrives at the delivery address, drop-off packages, collect payment,
    and mark the order as complete."""
    __, odoo_user = get_odoo_user(current_user.username)
    try:
        order_obj = get_order_obj(order_id, env, current_user)
    except OrderNotFoundException as e:
        return HTTPException(
            status_code=404, detail="Order not found", headers={"X-Error": str(e)}
        )
    else:
        # More validations
        error_header = None
        if order_obj.picking_ids.user_id.id != odoo_user.id:
            # Restrict order is assigned to the requestor
            error_header = "User not allowed to modify order"
        if error_header:
            return HTTPException(
                status_code=404,
                detail="Order not found",
                headers={"X-Error": error_header},
            )

    # Mark order drop off time when provided
    if request_body.drop_off_datetime:
        order_obj._message_log(
            body=_(
                "Drop off by %(user_name)s (#%(user_id)s) on %(timestamp)s",
                user_name=current_user.username,
                user_id=odoo_user.id,
                timestamp=str(request_body.drop_off_datetime),
            )
        )
    # Mark collected payment time when provided
    if request_body.collection_datetime:
        order_obj._message_log(
            body=_(
                "Collection of payment by %(user_name)s (#%(user_id)s) on %(timestamp)s",
                user_name=current_user.username,
                user_id=odoo_user.id,
                timestamp=str(request_body.collection_datetime),
            )
        )
    if request_body.message:
        order_obj._message_log(
            body=_(
                "Drop off message by %(user_name)s (#%(user_id)s) <br/><br/> %(message)s",
                user_name=current_user.username,
                user_id=odoo_user.id,
                message=request_body.message,
            )
        )
    # Picking
    picking = order_obj.picking_ids
    picking.button_validate()
    return {"object_id": order_obj.id}


class CancelBody(BaseModel):
    message: str


@router.post("/{order_id}/cancel-order")
async def cancel_order(
    order_id: int,
    request_body: CancelBody,
    env: odoo.api.Environment = Depends(odoo_env),
    current_user: User = Security(get_current_active_user, scopes=["orders:post"]),
):
    """Cancel order itself. Only possible for orders assigned to the requestor."""
    __, odoo_user = get_odoo_user(current_user.username)
    try:
        order_obj = get_order_obj(order_id, env, current_user)
    except OrderNotFoundException as e:
        return HTTPException(
            status_code=404, detail="Order not found", headers={"X-Error": str(e)}
        )
    else:
        # More validations
        error_header = None
        if order_obj.picking_ids.user_id.id != odoo_user.id:
            # Restrict order is assigned to the requestor
            error_header = "User not allowed to modify order"
        elif order_obj.picking_ids.state not in CANCELLABLE_ORDER_PICKING_STATES:
            # Restrict allowed order status that can be cancelled
            error_header = "Order cannot be cancelled"
        if error_header:
            return HTTPException(
                status_code=404,
                detail="Order not found",
                headers={"X-Error": error_header},
            )

    # Do order cancellation
    order_obj._action_cancel()
    # TODO As in Odoo, trigger sending notification to followers of the order thread
    # Log note to the sale order
    message = request_body.message
    order_obj._message_log(
        body=_(
            "Cancelled by %(user_name)s (#%(user_id)s). Message: <br/>%(message)s",
            user_name=current_user.username,
            user_id=odoo_user.id,
            message=message,
        )
    )
    return {"object_id": order_obj.id}


@router.post("/{order_id}/cancel-job")
async def cancel_order_job(
    order_id: int,
    request_body: CancelBody,
    env: odoo.api.Environment = Depends(odoo_env),
    current_user: User = Security(get_current_active_user, scopes=["orders:post"]),
):
    """Unassign the job. Only possible for orders assigned to the requestor."""
    __, odoo_user = get_odoo_user(current_user.username)
    try:
        order_obj = get_order_obj(order_id, env, current_user)
    except OrderNotFoundException as e:
        return HTTPException(
            status_code=404, detail="Order not found", headers={"X-Error": str(e)}
        )
    else:
        # More validations
        error_header = None
        if order_obj.picking_ids.user_id.id != odoo_user.id:
            # Restrict order is assigned to the requestor
            error_header = "User not allowed to modify order"
        elif order_obj.picking_ids.state not in CANCELLABLE_ORDER_PICKING_STATES:
            # Restrict allowed order status that can be cancelled
            error_header = "Order cannot be cancelled"
        if error_header:
            return HTTPException(
                status_code=404,
                detail="Order not found",
                headers={"X-Error": error_header},
            )

    # Do order unassignment
    picking = order_obj.picking_ids
    # Log self-unassignment on the picking
    message = _(
        "Remove assignment of %(user_name)s (#%(user_id)s) for delivery (#%(picking_id)s) on %(timestamp)s",
        user_name=current_user.username,
        user_id=odoo_user.id,
        picking_id=picking.id,
        timestamp=datetime.now().isoformat(),
    )
    message += "<br/>" + request_body.message
    picking._message_log(body=message)
    # Log self-unassignment on the order
    order_obj._message_log(body=message)
    # Remove driver assignment to picking
    picking.write({"user_id": False})
    return {"object_id": order_obj.id}


@router.get("/", response_model=Page[Order])
async def list_orders(
    state: Optional[list[PickingState]] = Query(
        default=[PickingState.assigned],
        # choices=[s.value for s in PickingState],
        choices=[s.value for s in PickingState],
        description=STATE_DESCRIPTION,
    ),
    env: odoo.api.Environment = Depends(odoo_env),
    current_user: User = Security(get_current_active_user, scopes=["orders:list"]),
):
    domain = [
        ("picking_ids", "!=", False)
    ]  # Must only return those that have pickings already
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
        # Picking status is "ready" (assigned) but no one really is set as responsible
        orders |= all_orders.filtered(
            lambda o: not o.picking_ids.state
            or (
                o.picking_ids.state == PickingState.assigned
                and o.picking_ids.user_id.id is False
            )
        )
    # TODO Paginate `orders` instead?
    # TODO BUG size is returning length of array instead of matched states/query. total and size are both correct.
    return paginate([Order.from_sale_order(order, env) for order in orders])
