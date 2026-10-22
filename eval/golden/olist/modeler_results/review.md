# Olist Modeler baseline

Reference design: unavailable; comparison pending.

Confirmed test choices:
- Grain: one row per order.
- Revenue: sum of item price + freight_value.
- Statuses: exclude canceled and unavailable.
- Reporting date: order_purchase_timestamp.

Observed successes:
- Asked about grain, revenue, statuses and reporting date.

Observed failure:
- The second response failed reference validation.
- Keys referenced undeclared target tables: orders, products.
- Relationships referenced undeclared target tables:
  order_items, orders, products.
- The invalid design was rejected before propose_design returned.

Remaining business ambiguity:
- For orders containing multiple product categories, category attribution
  is still unspecified. "Summarizing categories or using a primary category"
  does not select an allocation rule. Further clarification is needed.

Prompt revision to consider after all three baselines:
- Require key and relationship table names to match declared target tables.
- Ask about category attribution when an order-level grain spans categories.

Status: failed baseline; not compared against a canonical design.