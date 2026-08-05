"""
policy_agent.py - Applies EC_POLICY_V2 business rules to determine
primary/secondary issues, root causes, responsibilities, refunds, and actions.
"""

from agent_base import BaseAgent


class PolicyAgent(BaseAgent):
    """Agent responsible for applying EC_POLICY_V2 business rules."""

    def __init__(self):
        super().__init__(name="PolicyAgent", role="Policy Application")

    def process(
        self,
        case_id: str,
        order: dict,
        items_raw: list,
        payments_raw: list,
        delivery_analysis: dict,
        payment_reconciliation: dict,
        order_product_result: dict,
        customer_context: dict,
    ) -> dict:
        """
        Apply EC_POLICY_V2 rules in priority order.
        Returns case_assessment, root_cause_analysis, financial_resolution, resolution_actions.
        """
        self.log_action(case_id, "apply_policy", {"order_id": order.get("order_id") if order else None})

        order_status = order.get("order_status", "") if order else ""
        payment_total = payment_reconciliation.get("payment_total_brl", 0) or 0
        freight_total = payment_reconciliation.get("freight_total_brl", 0) or 0
        reconciled = payment_reconciliation.get("reconciled")
        delivery_variance = delivery_analysis.get("delivery_variance_hours")
        late_handoff_seller_ids = delivery_analysis.get("late_handoff_seller_ids", [])

        # ── Determine primary issue (priority order 1-6) ──
        primary_issue = None
        root_cause_code = None
        responsible_party_type = None
        responsible_party_id = None
        recommended_refund = 0.0
        primary_action = None
        case_status = "no_action"

        # 1. canceled_order_paid
        if order_status == "canceled" and payment_total > 0:
            primary_issue = "canceled_order_paid"
            root_cause_code = "ORDER_CANCELED_AFTER_PAYMENT"
            responsible_party_type = "platform"
            responsible_party_id = "OLIST_PLATFORM"
            recommended_refund = payment_total
            primary_action = "issue_full_refund"
            case_status = "action_required"

        # 2. unavailable_order_paid
        elif order_status == "unavailable" and payment_total > 0:
            primary_issue = "unavailable_order_paid"
            root_cause_code = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
            responsible_party_type = "platform"
            responsible_party_id = "OLIST_PLATFORM"
            recommended_refund = payment_total
            primary_action = "issue_full_refund"
            case_status = "action_required"

        # 3. late_delivery_seller
        elif (delivery_variance is not None and delivery_variance > 0 and len(late_handoff_seller_ids) > 0):
            primary_issue = "late_delivery_seller"
            root_cause_code = "SELLER_HANDOFF_AFTER_LIMIT"
            responsible_party_type = "seller"
            responsible_party_id = None  # will use late_handoff_seller_ids
            recommended_refund = freight_total if freight_total else 0.0
            primary_action = "refund_freight"
            case_status = "action_required"

        # 4. late_delivery_logistics
        elif (delivery_variance is not None and delivery_variance > 0 and len(late_handoff_seller_ids) == 0):
            primary_issue = "late_delivery_logistics"
            root_cause_code = "CARRIER_DELIVERED_AFTER_ESTIMATE"
            responsible_party_type = "logistics_provider"
            responsible_party_id = "LOGISTICS_PROVIDER"
            recommended_refund = freight_total if freight_total else 0.0
            primary_action = "refund_freight"
            case_status = "action_required"

        # 5. valid_split_payment
        elif len(payments_raw) >= 2 and reconciled is True:
            primary_issue = "valid_split_payment"
            root_cause_code = "MULTIPLE_PAYMENTS_RECONCILED"
            responsible_party_type = None
            responsible_party_id = None
            recommended_refund = 0.0
            primary_action = "explain_valid_split_payment"
            case_status = "no_action"

        # 6. unsupported_late_claim (delivery within estimate and payment matches)
        else:
            primary_issue = "unsupported_late_claim"
            root_cause_code = "DELIVERY_WITHIN_ESTIMATE"
            responsible_party_type = None
            responsible_party_id = None
            recommended_refund = 0.0
            primary_action = "reject_late_refund"
            case_status = "no_action"

        recommended_refund = round(recommended_refund, 2)

        # ── Determine secondary issues (in exact business priority order 1-5) ──
        secondary_issues = []

        # 1. multi_item_order: có từ 2 item row
        if len(items_raw) >= 2:
            secondary_issues.append("multi_item_order")

        # 2. multi_seller_order: có từ 2 seller khác nhau
        seller_ids_in_items = []
        for item in items_raw:
            sid = item.get("seller_id")
            if sid and str(sid) != "nan" and str(sid) not in seller_ids_in_items:
                seller_ids_in_items.append(str(sid))
        if len(seller_ids_in_items) >= 2:
            secondary_issues.append("multi_seller_order")

        # 3. split_payment: có từ 2 payment row
        if len(payments_raw) >= 2:
            secondary_issues.append("split_payment")

        # 4. repeat_customer: cùng customer_unique_id có order khác
        related_orders = customer_context.get("related_order_ids", []) or []
        if len(related_orders) >= 1:
            secondary_issues.append("repeat_customer")

        # 5. multiple_categories: có từ 2 category khác nhau
        categories = order_product_result.get("product_context", {}).get("category_names", []) or []
        if len(categories) >= 2:
            secondary_issues.append("multiple_categories")

        # ── Root cause analysis ──
        ranked_causes = [{"cause_code": root_cause_code, "rank": 1}]

        responsible_parties = []
        if responsible_party_type == "seller" and late_handoff_seller_ids:
            for sid in late_handoff_seller_ids[:3]:
                responsible_parties.append({"party_type": "seller", "party_id": sid})
        elif responsible_party_type and responsible_party_id:
            responsible_parties.append({
                "party_type": responsible_party_type,
                "party_id": responsible_party_id,
            })

        # ── Resolution actions (in exact business priority order) ──
        resolution_actions = [primary_action]

        # Additional actions in order:
        # review_seller_handoff OR review_carrier_delay
        if primary_issue == "late_delivery_seller":
            resolution_actions.append("review_seller_handoff")
        elif primary_issue == "late_delivery_logistics":
            resolution_actions.append("review_carrier_delay")

        # verify_refund_completion
        if case_status == "action_required":
            resolution_actions.append("verify_refund_completion")

        # coordinate_multi_seller_case
        if len(seller_ids_in_items) >= 2:
            resolution_actions.append("coordinate_multi_seller_case")

        # verify_payment_allocation (not when primary is valid_split_payment)
        if len(payments_raw) >= 2 and primary_issue != "valid_split_payment":
            resolution_actions.append("verify_payment_allocation")

        # Limit to 5 actions
        resolution_actions = resolution_actions[:5]

        result = {
            "case_assessment": {
                "primary_issue": primary_issue,
                "secondary_issues": secondary_issues,
                "case_status": case_status,
                "confidence": None,
            },
            "root_cause_analysis": {
                "ranked_causes": ranked_causes[:3],
                "responsible_parties": responsible_parties[:3],
            },
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": recommended_refund,
            },
            "resolution_actions": resolution_actions,
        }

        self.log_action(case_id, "policy_applied", {
            "primary_issue": primary_issue,
            "case_status": case_status,
            "refund": recommended_refund,
        })

        return result
