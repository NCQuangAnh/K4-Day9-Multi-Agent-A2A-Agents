"""
payment_agent.py - Payment reconciliation and ID extraction.
"""

from agent_base import BaseAgent
from data_loader import OlistData


class PaymentAgent(BaseAgent):
    """Agent responsible for payment reconciliation."""

    def __init__(self):
        super().__init__(name="PaymentAgent", role="Payment Reconciliation")

    def process(self, case_id: str, order_id: str, db: OlistData, items_raw: list) -> dict:
        """
        Reconcile payments against items + freight.
        Returns payment_reconciliation, payment_ids, and payments_raw dict.
        """
        self.log_action(case_id, "reconcile_payments", {"order_id": order_id})

        payments = db.get_order_payments(order_id)

        if not payments:
            return {
                "payment_reconciliation": {
                    "currency": "BRL",
                    "item_total_brl": 0.0 if items_raw else None,
                    "freight_total_brl": 0.0 if items_raw else None,
                    "expected_total_brl": 0.0 if items_raw else None,
                    "payment_total_brl": 0.0,
                    "difference_brl": 0.0 if items_raw else None,
                    "reconciled": True if items_raw else None,
                    "payment_types": [],
                },
                "payment_ids": [],
                "payments_raw": [],
            }

        # Sort payments by payment_sequential ascending (1, 2, 3...)
        sorted_payments = sorted(
            payments,
            key=lambda x: int(x.get("payment_sequential", 0)) if str(x.get("payment_sequential", "")).isdigit() else 0
        )

        payment_ids = []
        payment_types = []
        payment_total = 0.0

        for p in sorted_payments:
            seq = p.get("payment_sequential")
            if seq is not None:
                payment_ids.append(f"{order_id}:{seq}")

            ptype = p.get("payment_type")
            if ptype and str(ptype) != "nan" and ptype not in payment_types:
                payment_types.append(str(ptype))

            val = p.get("payment_value", 0)
            if val and str(val) != "nan":
                payment_total += float(val)

        payment_total = round(payment_total, 2)

        if not items_raw:
            # No item rows -> null values per README lines 112-113
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
                "payments_raw": payments,
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
                "payments_raw": payments,
            }

        self.log_action(case_id, "payments_reconciled", {
            "payment_total": payment_total,
            "reconciled": result["payment_reconciliation"]["reconciled"],
        })

        return result
