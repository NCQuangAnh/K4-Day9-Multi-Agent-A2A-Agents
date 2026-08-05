"""
customer_agent.py - Retrieves customer identity and historical order context.
"""

from agent_base import BaseAgent
from data_loader import OlistData


class CustomerAgent(BaseAgent):
    """Agent responsible for customer lookup and historical context."""

    def __init__(self):
        super().__init__(name="CustomerAgent", role="Customer Context")

    def process(self, case_id: str, order_id: str, db: OlistData) -> dict:
        """
        Lookup customer_unique_id and related historical order IDs.
        Returns customer_context dict.
        """
        self.log_action(case_id, "lookup_customer", {"order_id": order_id})

        order = db.get_order(order_id)
        if not order:
            return {"customer_unique_id": None, "related_order_ids": []}

        customer_id = order.get("customer_id")
        customer = db.get_customer(customer_id) if customer_id else None

        if not customer:
            return {"customer_unique_id": None, "related_order_ids": []}

        customer_unique_id = customer.get("customer_unique_id")
        all_orders = db.get_customer_history_detailed(customer_unique_id) if hasattr(db, 'get_customer_history_detailed') else []

        if not all_orders:
            all_order_ids = db.get_customer_history(customer_unique_id)
            related_order_ids = [oid for oid in all_order_ids if oid != order_id]
        else:
            # Sort historical orders by order_purchase_timestamp ascending
            sorted_orders = sorted(
                all_orders,
                key=lambda x: str(x.get("order_purchase_timestamp", ""))
            )
            related_order_ids = [o["order_id"] for o in sorted_orders if o.get("order_id") != order_id]

        related_order_ids = related_order_ids[:5]

        self.log_action(case_id, "customer_found", {
            "customer_unique_id": customer_unique_id,
            "related_orders_count": len(related_order_ids),
        })

        return {
            "customer_unique_id": customer_unique_id,
            "related_order_ids": related_order_ids,
        }
