# Architecture

```text
Input case -> Coordinator
                |-- Customer agent ------ customer identity + related order IDs
                |-- Order/Product agent - items, sellers, products, categories
                |-- Payment agent ------- payment rows + reconciliation
                |-- Delivery agent ------ delivery and handoff variance
                `-> Policy agent -------- issue, responsibility, refund, actions
                                            |
                                            `-> Verifier -> output/EC_XXX.json
```

| Agent | Read access | Handoff to coordinator | Write access |
| --- | --- | --- | --- |
| Customer | `customers`, `orders` | `customer_unique_id`, stable related order IDs | None |
| Order/Product | `orders`, `order_items`, `products`, `sellers` | source-derived entities and product context | None |
| Payment | `order_payments`, `order_items` | totals, difference, reconciliation result | None |
| Delivery | `orders`, `order_items` | delivery variance, one earliest-limit analysis per seller | None |
| Policy | structured handoffs and `EC_POLICY_V2` | assessment, root cause, parties, refund, actions | None |
| Verifier | assembled output plus source-derived IDs | validation result | `output/` only |

The coordinator combines structured handoffs only; it does not create events
or evidence absent from the CSV files. The verifier rejects unsupported IDs,
bad null handling, unstable-limit violations, or an invalid schema before the
packager writes `output.zip`.

Policy calculations and all submitted values are produced from source CSV data
and deterministic rules.
