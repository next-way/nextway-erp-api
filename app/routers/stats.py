from collections import namedtuple
from datetime import datetime

import odoo
from fastapi import APIRouter, Depends, Security
from pydantic import BaseModel

from app.dependencies import User, get_current_active_user, get_odoo_user, odoo_env

router = APIRouter(
    tags=["stats"],
)


class OrderStats(BaseModel):
    assigned: int
    completed: int
    completed_in_month: int
    current_period: str


class Statistics(BaseModel):
    orders: OrderStats


@router.get("/users/stats/", response_model=Statistics)
async def stats(
    env: odoo.api.Environment = Depends(odoo_env),
    current_user: User = Security(get_current_active_user, scopes=["me_profile"]),
):
    """User statistics"""
    __, odoo_user = get_odoo_user(current_user.username)
    order_stats = get_order_stats(env, odoo_user)
    return Statistics(orders=OrderStats(**order_stats))


Message = namedtuple("Message", "message, timestamp")


def get_order_stats(env: odoo.api.Environment, user):
    domain = [
        ("picking_ids", "!=", False)
    ]  # Must only return those that have pickings already
    # Get quick counts
    all_orders = env["sale.order"].search(domain)
    assigned = all_orders.filtered(lambda o: o.picking_ids.user_id.id == user.id)
    completed = all_orders.filtered(
        lambda o: o.picking_ids.user_id.id == user.id and o.picking_ids.state == "done"
    )
    # Get status from message logs
    today = datetime.now()
    start_of_month = today.replace(day=1).date()
    completed_messages = []
    for _order in all_orders:
        drop_off_message = None
        assignment_message = None
        # Retrieve from messages
        for message in _order.message_ids.filtered(
            lambda m: user in m.author_id.user_ids and m.date.date() >= start_of_month
        ):
            if drop_off_message is None and "Drop off by" in message.body:
                drop_off_message = Message(message=message.body, timestamp=message.date)
        # Save messages
        if drop_off_message:
            completed_messages.append(drop_off_message)

    return dict(
        assigned=len(assigned),
        completed=len(completed),
        completed_in_month=len(completed_messages),
        current_period=today.strftime("%B %Y"),
    )
