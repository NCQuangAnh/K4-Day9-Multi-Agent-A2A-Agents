"""
customer_agent.py - Identifies customer and retrieves order history.
"""

from agent_base import BaseAgent
from data_loader import OlistData


class CustomerAgent(BaseAgent):
    """Agent responsible for customer identification and history lookup."""

    def __init__(self):
        super().__init__(name="CustomerAgent", role="Customer Identity & History")

    def process(self, case_id: str, order_id: str, db: OlistData) -> dict:
        """
        Look up customer from order and find related orders.
        Returns customer_context dict.
        """
        self.log_action(case_id, "lookup_customer", {"order_id": order_id})

        order = db.get_order(order_id)
        if not order:
            return {
                "customer_unique_id": None,
                "related_order_ids": [],
            }

        customer_id = order.get("customer_id")
        customer = db.get_customer(customer_id)
        if not customer:
            return {
                "customer_unique_id": None,
                "related_order_ids": [],
            }

        customer_unique_id = customer.get("customer_unique_id")

        # Find all orders from this unique customer
        all_order_ids = db.get_customer_history(customer_unique_id)

        # Exclude the current order from related orders
        related_order_ids = [oid for oid in all_order_ids if oid != order_id]

        # Limit to 5 related orders per schema requirement
        related_order_ids = related_order_ids[:5]

        self.log_action(case_id, "customer_found", {
            "customer_unique_id": customer_unique_id,
            "related_order_count": len(related_order_ids),
        })

        return {
            "customer_unique_id": customer_unique_id,
            "related_order_ids": related_order_ids,
        }
