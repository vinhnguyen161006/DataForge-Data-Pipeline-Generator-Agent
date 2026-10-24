# TPC-H Modeler baseline

Status: returned a design and passed reference validation.
Canonical comparison: pending reference design from Tuấn.

Observed issues:
- Order grain includes a single product key without explaining how
  multi-product orders are represented or allocated.
- No fact-to-customer relationship is declared for customer-nation analysis.
- count(order_count) does not clearly implement distinct order counting.
- net_revenue derivation and treatment of orders with no eligible items
  are insufficiently specified.

Recurring findings across baselines:
- OULAD and TPC-H: incomplete measure derivation or join specification.
- Olist and TPC-H: order-level analysis by product/category requires
  an explicit attribution rule.
- Olist: keys and relationships referenced undeclared target tables.