from typing import Dict


def customer_agent_prompt(case: Dict[str, str]) -> str:
    return (
        f"You are a Customer Agent. Analyze the claimed order and customer history.\n"
        f"Order ID: {case['claimed_order_id']}\n"
        "Provide customer_unique_id and related_order_ids only from data."
    )


def order_agent_prompt(order_id: str) -> str:
    return (
        f"You are an Order Agent. Summarize order items, sellers, products, categories for order {order_id}."
    )


def payment_agent_prompt(order_id: str) -> str:
    return (
        f"You are a Payment Agent. Reconcile payment rows for order {order_id}."
    )


def delivery_agent_prompt(order_id: str) -> str:
    return (
        f"You are a Delivery Agent. Analyze delivery, estimate, and seller handoff for order {order_id}."
    )


def policy_agent_prompt(order_id: str) -> str:
    return (
        f"You are a Policy Agent. Apply EC_POLICY_V2 and decide primary issue, cause code, responsible party, and actions for order {order_id}."
    )
