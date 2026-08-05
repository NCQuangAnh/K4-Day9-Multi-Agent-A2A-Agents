"""
verifier_agent.py - Schema validation, evidence ID verification, and null handling.
"""

from agent_base import BaseAgent
from data_loader import OlistData


class VerifierAgent(BaseAgent):
    """Agent responsible for final output validation."""

    def __init__(self):
        super().__init__(name="VerifierAgent", role="Output Verification")

    def verify(self, case_id: str, output: dict, db: OlistData) -> dict:
        """
        Validate and fix the final output JSON.
        - Check evidence ID format and existence
        - Enforce array limits
        - Ensure null handling for missing data
        Returns the corrected output dict.
        """
        self.log_action(case_id, "verify_output")

        # ── Array limits ──
        ae = output.get("affected_entities", {})
        ae["order_ids"] = (ae.get("order_ids") or [])[:5]
        ae["item_ids"] = (ae.get("item_ids") or [])[:5]
        ae["seller_ids"] = (ae.get("seller_ids") or [])[:3]
        ae["payment_ids"] = (ae.get("payment_ids") or [])[:5]
        output["affected_entities"] = ae

        cc = output.get("customer_context", {})
        cc["related_order_ids"] = (cc.get("related_order_ids") or [])[:5]
        output["customer_context"] = cc

        pc = output.get("product_context", {})
        pc["product_ids"] = (pc.get("product_ids") or [])[:5]
        pc["category_names"] = (pc.get("category_names") or [])[:5]
        output["product_context"] = pc

        rca = output.get("root_cause_analysis", {})
        rca["ranked_causes"] = (rca.get("ranked_causes") or [])[:3]
        rca["responsible_parties"] = (rca.get("responsible_parties") or [])[:3]
        output["root_cause_analysis"] = rca

        output["resolution_actions"] = (output.get("resolution_actions") or [])[:5]

        # ── Build and validate evidence IDs ──
        evidence_ids = []
        order_id = ae["order_ids"][0] if ae["order_ids"] else None

        if order_id:
            # order evidence
            order_data = db.get_order(order_id)
            if order_data:
                evidence_ids.append(f"order:{order_id}")

            # item evidence
            for item_id in ae.get("item_ids", []):
                evidence_ids.append(f"item:{item_id}")

            # payment evidence
            for payment_id in ae.get("payment_ids", []):
                evidence_ids.append(f"payment:{payment_id}")

            # seller evidence (only responsible sellers)
            rca = output.get("root_cause_analysis", {})
            for party in rca.get("responsible_parties", []):
                if party.get("party_type") == "seller":
                    evidence_ids.append(f"seller:{party['party_id']}")

        # policy evidence
        for cause in output.get("root_cause_analysis", {}).get("ranked_causes", []):
            evidence_ids.append(f"policy:{cause['cause_code']}")

        # Limit to 20 evidence IDs
        evidence_ids = evidence_ids[:20]
        output["evidence_ids"] = evidence_ids

        # ── Confidence bounds ──
        ca = output.get("case_assessment", {})
        conf = ca.get("confidence")
        if conf is not None:
            conf = max(0.0, min(1.0, float(conf)))
            ca["confidence"] = round(conf, 2)
        output["case_assessment"] = ca

        self.log_action(case_id, "verification_complete", {
            "evidence_count": len(evidence_ids),
        })

        return output
