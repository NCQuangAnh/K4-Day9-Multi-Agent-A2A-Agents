"""
order_product_agent.py - Retrieves order items, products, sellers, and categories.
"""

from agent_base import BaseAgent
from data_loader import OlistData


class OrderProductAgent(BaseAgent):
    """Agent responsible for order items, products, sellers, and categories."""

    def __init__(self):
        super().__init__(name="OrderProductAgent", role="Order & Product Analysis")

    def process(self, case_id: str, order_id: str, db: OlistData) -> dict:
        """
        Retrieve order items, associated products, sellers, and categories.
        Returns affected_entities and product_context dicts.
        """
        self.log_action(case_id, "lookup_order_items", {"order_id": order_id})

        items = db.get_order_items(order_id)

        if not items:
            return {
                "affected_entities": {
                    "order_ids": [order_id],
                    "item_ids": [],
                    "seller_ids": [],
                    "payment_ids": [],  # Will be filled by payment agent
                },
                "product_context": {
                    "product_ids": [],
                    "category_names": [],
                },
                "items_raw": [],
            }

        # Extract item IDs: format is "order_id:order_item_id"
        item_ids = []
        seller_ids_set = set()
        product_ids_set = set()
        category_names_set = set()

        for item in items:
            order_item_id = item.get("order_item_id")
            item_ids.append(f"{order_id}:{order_item_id}")

            seller_id = item.get("seller_id")
            if seller_id and str(seller_id) != "nan":
                seller_ids_set.add(seller_id)

            product_id = item.get("product_id")
            if product_id and str(product_id) != "nan":
                product_ids_set.add(product_id)
                product = db.get_product(product_id)
                if product:
                    cat = product.get("product_category_name")
                    if cat and str(cat) != "nan":
                        category_names_set.add(cat)

        # Apply schema limits
        item_ids = item_ids[:5]
        seller_ids = list(seller_ids_set)[:3]
        product_ids = list(product_ids_set)[:5]
        category_names = list(category_names_set)[:5]

        self.log_action(case_id, "order_items_found", {
            "item_count": len(items),
            "seller_count": len(seller_ids),
            "product_count": len(product_ids),
        })

        return {
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids,
                "seller_ids": seller_ids,
                "payment_ids": [],  # Will be filled by payment agent
            },
            "product_context": {
                "product_ids": product_ids,
                "category_names": category_names,
            },
            "items_raw": items,
        }
