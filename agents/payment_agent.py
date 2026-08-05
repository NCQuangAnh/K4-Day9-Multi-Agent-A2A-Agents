"""
payment_agent.py - Payment reconciliation against items + freight.
"""

from agent_base import BaseAgent
from data_loader import OlistData


class PaymentAgent(BaseAgent):
    """Agent responsible for payment reconciliation."""

    def __init__(self):
        super().__init__(name="PaymentAgent", role="Payment Reconciliation")

    def process(self, case_id: str, order_id: str, db: OlistData, items_raw: list) -> dict:
        """
        Calculate payment reconciliation.
        Returns payment_reconciliation dict and payment_ids.
        """
        self.log_action(case_id, "reconcile_payments", {"order_id": order_id})

        payments = db.get_order_payments(order_id)

        # Payment IDs: format is "order_id:payment_sequential"
        payment_ids = []
        payment_total = 0.0
        payment_types = []

        for p in payments:
            seq = p.get("payment_sequential")
            payment_ids.append(f"{order_id}:{seq}")
            val = p.get("payment_value", 0)
            payment_total += float(val) if val and str(val) != "nan" else 0.0
            ptype = p.get("payment_type")
            if ptype and str(ptype) != "nan" and ptype not in payment_types:
                payment_types.append(ptype)

        payment_total = round(payment_total, 2)

        # Calculate expected total from items
        if not items_raw:
            # No item rows -> null values per README
            result = {
                "payment_reconciliation": {
                    "currency": "BRL",
                    "item_total_brl": None,
                    "freight_total_brl": None,
                    "expected_total_brl": None,
                    "payment_total_brl": payment_total,
                    "difference_brl": None,
                    "reconciled": None,
                    "payment_types": payment_types,
                },
                "payment_ids": payment_ids[:5],
            }
        else:
            item_total = sum(
                float(i.get("price", 0)) for i in items_raw
                if i.get("price") and str(i.get("price")) != "nan"
            )
            freight_total = sum(
                float(i.get("freight_value", 0)) for i in items_raw
                if i.get("freight_value") and str(i.get("freight_value")) != "nan"
            )

            item_total = round(item_total, 2)
            freight_total = round(freight_total, 2)
            expected_total = round(item_total + freight_total, 2)
            difference = round(payment_total - expected_total, 2)
            reconciled = abs(difference) <= 0.10

            result = {
                "payment_reconciliation": {
                    "currency": "BRL",
                    "item_total_brl": item_total,
                    "freight_total_brl": freight_total,
                    "expected_total_brl": expected_total,
                    "payment_total_brl": payment_total,
                    "difference_brl": difference,
                    "reconciled": reconciled,
                    "payment_types": payment_types,
                },
                "payment_ids": payment_ids[:5],
            }

        self.log_action(case_id, "payment_reconciled", {
            "payment_total": payment_total,
            "payment_count": len(payments),
            "reconciled": result["payment_reconciliation"].get("reconciled"),
        })

        return result
