"""
delivery_agent.py - Delivery variance and seller handoff analysis.
"""

from datetime import datetime
from agent_base import BaseAgent
from data_loader import OlistData


def parse_timestamp(ts: str) -> datetime | None:
    """Parse timestamp string from CSV. Returns None if invalid."""
    if not ts or str(ts) == "nan" or str(ts) == "NaT":
        return None
    try:
        return datetime.strptime(str(ts).strip(), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def hours_diff(dt1: datetime, dt2: datetime) -> float:
    """Calculate hours difference between two datetimes, rounded to 2 decimals."""
    if dt1 is None or dt2 is None:
        return None
    delta = dt1 - dt2
    return round(delta.total_seconds() / 3600, 2)


class DeliveryAgent(BaseAgent):
    """Agent responsible for delivery timeline analysis."""

    def __init__(self):
        super().__init__(name="DeliveryAgent", role="Delivery Analysis")

    def process(self, case_id: str, order_id: str, db: OlistData, items_raw: list) -> dict:
        """
        Calculate delivery variance and seller handoff analysis.
        Returns delivery_analysis dict.
        """
        self.log_action(case_id, "analyze_delivery", {"order_id": order_id})

        order = db.get_order(order_id)
        if not order:
            return self._empty_delivery()

        delivered_at = parse_timestamp(order.get("order_delivered_customer_date"))
        estimated_at = parse_timestamp(order.get("order_estimated_delivery_date"))
        carrier_handoff_at = parse_timestamp(order.get("order_delivered_carrier_date"))

        # delivery_variance_hours = delivered - estimated
        delivery_variance = hours_diff(delivered_at, estimated_at)

        # Seller handoff analysis
        seller_handoff_analysis = []
        late_handoff_seller_ids = []

        if items_raw:
            # Maintain insertion order of sellers from items_raw
            seller_limits = {}
            for item in items_raw:
                seller_id = item.get("seller_id")
                limit_str = item.get("shipping_limit_date")
                if not seller_id or str(seller_id) == "nan":
                    continue
                seller_id = str(seller_id)
                limit_dt = parse_timestamp(limit_str)
                if seller_id not in seller_limits or (
                    limit_dt and (seller_limits[seller_id]["dt"] is None or limit_dt < seller_limits[seller_id]["dt"])
                ):
                    seller_limits[seller_id] = {"dt": limit_dt, "str": limit_str}

            for seller_id, limit_info in seller_limits.items():
                limit_dt = limit_info["dt"]

                # handoff_variance_hours = carrier_handoff - shipping_limit
                handoff_variance = hours_diff(carrier_handoff_at, limit_dt)
                late_handoff = handoff_variance is not None and handoff_variance > 0

                shipping_limit_at = limit_dt.strftime("%Y-%m-%d %H:%M:%S") if limit_dt else None

                seller_handoff_analysis.append({
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit_at,
                    "handoff_variance_hours": handoff_variance,
                    "late_handoff": late_handoff,
                })

                if late_handoff and seller_id not in late_handoff_seller_ids:
                    late_handoff_seller_ids.append(seller_id)

        def fmt_ts(dt, raw):
            if dt is not None:
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            raw_str = str(raw).strip() if raw and str(raw) != "nan" and str(raw) != "NaT" else None
            return raw_str

        result = {
            "delivered_at": fmt_ts(delivered_at, order.get("order_delivered_customer_date")),
            "estimated_delivery_at": fmt_ts(estimated_at, order.get("order_estimated_delivery_date")),
            "carrier_handoff_at": fmt_ts(carrier_handoff_at, order.get("order_delivered_carrier_date")),
            "delivery_variance_hours": delivery_variance,
            "seller_handoff_analysis": seller_handoff_analysis,
            "late_handoff_seller_ids": late_handoff_seller_ids,
        }

        self.log_action(case_id, "delivery_analyzed", {
            "delivery_variance_hours": delivery_variance,
            "late_sellers": len(late_handoff_seller_ids),
        })

        return result

    def _empty_delivery(self) -> dict:
        return {
            "delivered_at": None,
            "estimated_delivery_at": None,
            "carrier_handoff_at": None,
            "delivery_variance_hours": None,
            "seller_handoff_analysis": [],
            "late_handoff_seller_ids": [],
        }
