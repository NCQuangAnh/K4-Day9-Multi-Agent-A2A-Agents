"""
coordinator_agent.py - Orchestrates all agents to solve customer claims end-to-end.
"""

from agent_base import BaseAgent
from data_loader import OlistData
from agents.customer_agent import CustomerAgent
from agents.order_product_agent import OrderProductAgent
from agents.payment_agent import PaymentAgent
from agents.delivery_agent import DeliveryAgent
from agents.policy_agent import PolicyAgent
from agents.verifier_agent import VerifierAgent


class CoordinatorAgent(BaseAgent):
    """Central Orchestrator Agent linking specialized sub-agents."""

    def __init__(self, db: OlistData = None):
        super().__init__(name="CoordinatorAgent", role="Orchestration & Verification")
        self.db = db
        self.customer_agent = CustomerAgent()
        self.order_product_agent = OrderProductAgent()
        self.payment_agent = PaymentAgent()
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent()

    def process_case(self, case_input: dict, db: OlistData = None) -> dict:
        """
        End-to-end processing of a single investigation case.
        """
        if db is None:
            db = self.db

        case_id = case_input.get("case_id", "UNKNOWN")
        req = case_input.get("customer_request", {})
        order_id = req.get("claimed_order_id")

        self.log_action(case_id, "start_case_investigation", {"claimed_order_id": order_id})

        # ── Step 1: Customer Agent ──
        customer_context = self.customer_agent.process(case_id, order_id, db)

        # ── Step 2: Order & Product Agent ──
        order_product_result = self.order_product_agent.process(case_id, order_id, db)

        # ── Step 3: Payment Agent ──
        items_raw = order_product_result.get("items_raw", [])
        payment_recon_result = self.payment_agent.process(case_id, order_id, db, items_raw)

        # ── Step 4: Delivery Agent ──
        delivery_analysis = self.delivery_agent.process(case_id, order_id, db, items_raw)
        delivery_result = {"delivery_analysis": delivery_analysis}

        # ── Step 5: Policy Agent (EC_POLICY_V2) ──
        order = db.get_order(order_id)
        policy_result = self.policy_agent.process(
            case_id,
            order,
            customer_context,
            order_product_result,
            payment_recon_result,
            delivery_result,
        )

        # ── Step 6: Evaluate Confidence ──
        confidence = self._evaluate_confidence(order, delivery_analysis, payment_recon_result, policy_result)

        # ── Step 7: Assemble Final Output Schema ──
        ae_op = order_product_result.get("affected_entities", {})
        raw_output = {
            "case_id": case_id,
            "case_assessment": {
                "primary_issue": policy_result["primary_issue"],
                "secondary_issues": policy_result["secondary_issues"],
                "case_status": policy_result["case_status"],
                "confidence": confidence,
            },
            "affected_entities": {
                "order_ids": [order_id] if order_id else [],
                "item_ids": ae_op.get("item_ids", []),
                "seller_ids": ae_op.get("seller_ids", []),
                "payment_ids": payment_recon_result.get("payment_ids", []),
            },
            "customer_context": {
                "customer_unique_id": customer_context["customer_unique_id"],
                "related_order_ids": customer_context["related_order_ids"],
            },
            "product_context": order_product_result["product_context"],
            "delivery_analysis": delivery_analysis,
            "payment_reconciliation": payment_recon_result["payment_reconciliation"],
            "root_cause_analysis": {
                "ranked_causes": [
                    {"cause_code": policy_result["root_cause_code"], "rank": 1}
                ] if policy_result["root_cause_code"] else [],
                "responsible_parties": policy_result["responsible_parties"],
            },
            "evidence_ids": [],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": policy_result["recommended_refund_brl"],
            },
            "resolution_actions": policy_result["resolution_actions"],
        }

        # ── Step 8: Verifier Agent (schema, evidence IDs, bounds) ──
        final_output = self.verifier_agent.verify(case_id, raw_output, db)

        self.log_action(case_id, "case_completed", {
            "primary_issue": final_output["case_assessment"]["primary_issue"],
            "confidence": final_output["case_assessment"]["confidence"],
        })

        return final_output

    def _evaluate_confidence(self, order, delivery_analysis, payment_recon_result, policy_result) -> float:
        """
        Evaluate confidence score for assessment. Default to 0.92 per README.md line 142.
        """
        payment_recon = payment_recon_result.get("payment_reconciliation", {})
        score = 0.92

        if payment_recon.get("reconciled") is True:
            score += 0.03
        if delivery_analysis.get("delivered_at") and delivery_analysis.get("estimated_delivery_at"):
            score += 0.03

        score = max(0.0, min(0.98, score))
        return round(score, 2)
