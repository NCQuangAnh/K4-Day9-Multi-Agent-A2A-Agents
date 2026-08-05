"""
coordinator_agent.py - Orchestrates all agents and assembles final output.
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
    """
    Central coordinator that dispatches work to specialized agents
    and assembles the final case output.
    """

    def __init__(self, db: OlistData):
        super().__init__(name="CoordinatorAgent", role="Case Coordination")
        self.db = db
        self.customer_agent = CustomerAgent()
        self.order_product_agent = OrderProductAgent()
        self.payment_agent = PaymentAgent()
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent()

    def process_case(self, case_input: dict) -> dict:
        """
        Process a single case end-to-end.
        Dispatches to all agents, assembles output, and verifies.
        """
        case_id = case_input.get("case_id", "UNKNOWN")
        order_id = case_input.get("customer_request", {}).get("claimed_order_id", "")

        self.log_action(case_id, "start_case", {"order_id": order_id})

        # Get order data
        order = self.db.get_order(order_id)

        # ── Step 1: Customer Agent ──
        print(f"  [{case_id}] CustomerAgent: looking up customer...")
        customer_context = self.customer_agent.process(case_id, order_id, self.db)

        # ── Step 2: Order & Product Agent ──
        print(f"  [{case_id}] OrderProductAgent: analyzing items...")
        order_product_result = self.order_product_agent.process(case_id, order_id, self.db)
        items_raw = order_product_result.get("items_raw", [])

        # ── Step 3: Payment Agent ──
        print(f"  [{case_id}] PaymentAgent: reconciling payments...")
        payment_result = self.payment_agent.process(case_id, order_id, self.db, items_raw)

        # ── Step 4: Delivery Agent ──
        print(f"  [{case_id}] DeliveryAgent: analyzing delivery timeline...")
        delivery_analysis = self.delivery_agent.process(case_id, order_id, self.db, items_raw)

        # ── Step 5: Policy Agent ──
        print(f"  [{case_id}] PolicyAgent: applying EC_POLICY_V2...")
        payments_raw = self.db.get_order_payments(order_id)
        policy_result = self.policy_agent.process(
            case_id=case_id,
            order=order or {},
            items_raw=items_raw,
            payments_raw=payments_raw,
            delivery_analysis=delivery_analysis,
            payment_reconciliation=payment_result["payment_reconciliation"],
            order_product_result=order_product_result,
            customer_context=customer_context,
        )

        # ── Step 6: Confidence Score Calculation ──
        print(f"  [{case_id}] CoordinatorAgent: evaluating confidence...")
        confidence = self._evaluate_confidence(order, delivery_analysis,
                                                payment_result["payment_reconciliation"],
                                                policy_result)

        policy_result["case_assessment"]["confidence"] = confidence

        # ── Merge payment_ids into affected_entities ──
        affected_entities = order_product_result["affected_entities"]
        affected_entities["payment_ids"] = payment_result["payment_ids"]

        # ── Assemble final output ──
        output = {
            "case_id": case_id,
            "case_assessment": policy_result["case_assessment"],
            "affected_entities": affected_entities,
            "customer_context": customer_context,
            "product_context": order_product_result["product_context"],
            "delivery_analysis": delivery_analysis,
            "payment_reconciliation": payment_result["payment_reconciliation"],
            "root_cause_analysis": policy_result["root_cause_analysis"],
            "evidence_ids": [],  # Will be built by verifier
            "financial_resolution": policy_result["financial_resolution"],
            "resolution_actions": policy_result["resolution_actions"],
        }

        # ── Step 7: Verifier Agent ──
        print(f"  [{case_id}] VerifierAgent: validating output...")
        output = self.verifier_agent.verify(case_id, output, self.db)

        self.log_action(case_id, "case_complete", {
            "primary_issue": policy_result["case_assessment"]["primary_issue"],
            "case_status": policy_result["case_assessment"]["case_status"],
        })

        return output

    def _evaluate_confidence(self, order, delivery, payment_recon, policy) -> float:
        """
        Calculate deterministic, high-precision confidence score
        based on evidence completeness and calculation accuracy.
        """
        score = 0.85  # Base confidence for clear policy match

        # Bonus for reconciled payments
        if payment_recon.get("reconciled") is True:
            score += 0.05

        # Bonus for complete delivery timestamps
        if delivery.get("delivered_at") and delivery.get("estimated_delivery_at"):
            score += 0.05

        # Cap confidence between 0.0 and 0.98
        score = max(0.0, min(0.98, score))
        return round(score, 2)
