"""
data_loader.py - Data access layer for Olist e-commerce dataset.
Loads 9 CSV files once into memory with indexed lookups.
"""

import os
import pandas as pd


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class OlistData:
    """Singleton-style data loader for Olist CSV datasets."""

    def __init__(self):
        print("[DataLoader] Loading Olist datasets...")
        self.orders = pd.read_csv(os.path.join(DATA_DIR, "olist_orders_dataset.csv"))
        self.order_items = pd.read_csv(os.path.join(DATA_DIR, "olist_order_items_dataset.csv"))
        self.order_payments = pd.read_csv(os.path.join(DATA_DIR, "olist_order_payments_dataset.csv"))
        self.customers = pd.read_csv(os.path.join(DATA_DIR, "olist_customers_dataset.csv"))
        self.products = pd.read_csv(os.path.join(DATA_DIR, "olist_products_dataset.csv"))
        self.sellers = pd.read_csv(os.path.join(DATA_DIR, "olist_sellers_dataset.csv"))
        self.reviews = pd.read_csv(os.path.join(DATA_DIR, "olist_order_reviews_dataset.csv"))
        self.geolocation = pd.read_csv(os.path.join(DATA_DIR, "olist_geolocation_dataset.csv"))
        self.category_translation = pd.read_csv(
            os.path.join(DATA_DIR, "product_category_name_translation.csv")
        )

        # Build indexes for fast lookup
        self._orders_by_id = self.orders.set_index("order_id")
        self._customers_by_id = self.customers.set_index("customer_id")
        self._items_by_order = self.order_items.groupby("order_id")
        self._payments_by_order = self.order_payments.groupby("order_id")
        self._products_by_id = self.products.set_index("product_id")
        self._sellers_by_id = self.sellers.set_index("seller_id")
        self._reviews_by_order = self.reviews.groupby("order_id")

        # Customer unique ID index: customer_unique_id -> list of customer_ids
        self._customers_by_unique = self.customers.groupby("customer_unique_id")

        print(f"[DataLoader] Loaded {len(self.orders)} orders, {len(self.order_items)} items, "
              f"{len(self.order_payments)} payments, {len(self.customers)} customers")

    def get_order(self, order_id: str) -> dict | None:
        """Get order record by order_id."""
        try:
            row = self._orders_by_id.loc[order_id]
            result = row.to_dict()
            result["order_id"] = order_id
            return result
        except KeyError:
            return None

    def get_order_items(self, order_id: str) -> list[dict]:
        """Get all order items for an order_id."""
        try:
            group = self._items_by_order.get_group(order_id)
            return group.to_dict("records")
        except KeyError:
            return []

    def get_order_payments(self, order_id: str) -> list[dict]:
        """Get all payment rows for an order_id."""
        try:
            group = self._payments_by_order.get_group(order_id)
            return group.to_dict("records")
        except KeyError:
            return []

    def get_customer(self, customer_id: str) -> dict | None:
        """Get customer record by customer_id."""
        try:
            row = self._customers_by_id.loc[customer_id]
            result = row.to_dict()
            result["customer_id"] = customer_id
            return result
        except KeyError:
            return None

    def get_customer_history(self, customer_unique_id: str) -> list[str]:
        """Get all order_ids for a customer_unique_id (via customer_id join)."""
        try:
            customer_rows = self._customers_by_unique.get_group(customer_unique_id)
            customer_ids = customer_rows["customer_id"].tolist()
            # Find all orders for these customer_ids
            related_orders = self.orders[
                self.orders["customer_id"].isin(customer_ids)
            ]["order_id"].tolist()
            return related_orders
        except KeyError:
            return []

    def get_product(self, product_id: str) -> dict | None:
        """Get product record by product_id."""
        try:
            row = self._products_by_id.loc[product_id]
            result = row.to_dict()
            result["product_id"] = product_id
            return result
        except KeyError:
            return None

    def get_seller(self, seller_id: str) -> dict | None:
        """Get seller record by seller_id."""
        try:
            row = self._sellers_by_id.loc[seller_id]
            result = row.to_dict()
            result["seller_id"] = seller_id
            return result
        except KeyError:
            return None

    def get_order_reviews(self, order_id: str) -> list[dict]:
        """Get all reviews for an order_id."""
        try:
            group = self._reviews_by_order.get_group(order_id)
            return group.to_dict("records")
        except KeyError:
            return []
