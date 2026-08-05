"""
policy_agent.py - EC_POLICY_V2 policy evaluation engine.
Implements primary issue priority, secondary issues, root cause, responsible parties, and actions.
"""

from agent_base import BaseAgent


class PolicyAgent(BaseAgent):
    """Agent responsible for applying EC_POLICY_V2 business logic."""

    def __init__(self):
        super().__init__(name="PolicyAgent", role="Policy Evaluation")

    def process(
        self,
        case_id: str,
        order: dict,
        customer_context: dict,
        order_product_result: dict,
        payment_recon_result: dict,
        delivery_result: dict,
    ) -> dict:
        """
        Evaluate EC_POLICY_V2 rules deterministically.
        """
        self.log_action(case_id, "evaluate_policy")

        order_status = order.get("order_status", "") if order else ""
        items_raw = order_product_result.get("items_raw", [])
        payments_raw = payment_recon_result.get("payments_raw", [])
        payment_recon = payment_recon_result.get("payment_reconciliation", {})
        delivery = delivery_result.get("delivery_analysis", {})

        payment_total = payment_recon.get("payment_total_brl", 0.0) or 0.0
        reconciled = payment_recon.get("reconciled")
        freight_total = payment_recon.get("freight_total_brl", 0.0) or 0.0

        delivery_variance = delivery.get("delivery_variance_hours")
        late_handoff_seller_ids = delivery.get("late_handoff_seller_ids", [])

        is_late_delivery = delivery_variance is not None and delivery_variance > 0
        has_late_seller = len(late_handoff_seller_ids) > 0

        # ── 1. Primary Issue Determination ──
        primary_issue = None
        recommended_refund = 0.0
        root_cause_code = None
        responsible_party_type = None
        primary_action = None

        if order_status == "canceled" and payment_total > 0:
            primary_issue = "canceled_order_paid"
            recommended_refund = payment_total
            root_cause_code = "ORDER_CANCELED_AFTER_PAYMENT"
            responsible_party_type = "platform"
            primary_action = "issue_full_refund"

        elif order_status == "unavailable" and payment_total > 0:
            primary_issue = "unavailable_order_paid"
            recommended_refund = payment_total
            root_cause_code = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
            responsible_party_type = "platform"
            primary_action = "issue_full_refund"

        elif is_late_delivery and has_late_seller:
            primary_issue = "late_delivery_seller"
            recommended_refund = freight_total
            root_cause_code = "SELLER_HANDOFF_AFTER_LIMIT"
            responsible_party_type = "seller"
            primary_action = "refund_freight"

        elif is_late_delivery and not has_late_seller:
            primary_issue = "late_delivery_logistics"
            recommended_refund = freight_total
            root_cause_code = "CARRIER_DELIVERED_AFTER_ESTIMATE"
            responsible_party_type = "logistics_provider"
            primary_action = "refund_freight"

        elif len(payments_raw) >= 2 and reconciled is True:
            primary_issue = "valid_split_payment"
            recommended_refund = 0.0
            root_cause_code = "MULTIPLE_PAYMENTS_RECONCILED"
            responsible_party_type = None
            primary_action = "explain_valid_split_payment"

        else:
            primary_issue = "unsupported_late_claim"
            recommended_refund = 0.0
            root_cause_code = "DELIVERY_WITHIN_ESTIMATE"
            responsible_party_type = None
            primary_action = "reject_late_refund"

        case_status = "action_required" if recommended_refund > 0 else "no_action"

        # ── 2. Secondary Issues Determination (Strict Priority 1->5) ──
        secondary_issues = []

        # Priority 1: multi_item_order (có từ 2 item row)
        if len(items_raw) >= 2:
            secondary_issues.append("multi_item_order")

        # Priority 2: multi_seller_order (có từ 2 seller khác nhau)
        seller_ids_in_items = []
        for item in items_raw:
            sid = item.get("seller_id")
            if sid and str(sid) != "nan" and str(sid) not in seller_ids_in_items:
                seller_ids_in_items.append(str(sid))

        if len(seller_ids_in_items) >= 2:
            secondary_issues.append("multi_seller_order")

        # Priority 3: split_payment (có từ 2 payment row)
        if len(payments_raw) >= 2:
            secondary_issues.append("split_payment")

        # Priority 4: repeat_customer (cùng customer_unique_id có order khác)
        related_orders = customer_context.get("related_order_ids", []) or []
        if len(related_orders) >= 1:
            secondary_issues.append("repeat_customer")

        # Priority 5: multiple_categories (có từ 2 category khác nhau)
        categories = order_product_result.get("product_context", {}).get("category_names", []) or []
        if len(categories) >= 2:
            secondary_issues.append("multiple_categories")

        # Limit to max 3 secondary issues
        secondary_issues = secondary_issues[:3]

        # ── 3. Responsible Parties ──
        responsible_parties = []
        if responsible_party_type == "platform":
            responsible_parties.append({"party_type": "platform", "party_id": "OLIST_PLATFORM"})
        elif responsible_party_type == "logistics_provider":
            responsible_parties.append({"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"})
        elif responsible_party_type == "seller" and late_handoff_seller_ids:
            for sid in late_handoff_seller_ids[:3]:
                responsible_parties.append({"party_type": "seller", "party_id": sid})

        # ── 4. Resolution Actions (Strict Order per README lines 114-115) ──
        resolution_actions = [primary_action]

        # Additional action 1: review_seller_handoff / review_carrier_delay
        if primary_issue == "late_delivery_seller":
            resolution_actions.append("review_seller_handoff")
        elif primary_issue == "late_delivery_logistics":
            resolution_actions.append("review_carrier_delay")

        # Additional action 2: verify_refund_completion (if action_required)
        if case_status == "action_required":
            resolution_actions.append("verify_refund_completion")

        # Additional action 3: coordinate_multi_seller_case (if multi-seller)
        if len(seller_ids_in_items) >= 2:
            resolution_actions.append("coordinate_multi_seller_case")

        # Additional action 4: verify_payment_allocation (if split payment and primary != valid_split_payment)
        if len(payments_raw) >= 2 and primary_issue != "valid_split_payment":
            resolution_actions.append("verify_payment_allocation")

        resolution_actions = resolution_actions[:5]

        self.log_action(case_id, "policy_evaluated", {
            "primary_issue": primary_issue,
            "secondary_issues": secondary_issues,
            "refund": recommended_refund,
        })

        return {
            "primary_issue": primary_issue,
            "secondary_issues": secondary_issues,
            "case_status": case_status,
            "root_cause_code": root_cause_code,
            "responsible_parties": responsible_parties,
            "recommended_refund_brl": round(recommended_refund, 2),
            "resolution_actions": resolution_actions,
        }
