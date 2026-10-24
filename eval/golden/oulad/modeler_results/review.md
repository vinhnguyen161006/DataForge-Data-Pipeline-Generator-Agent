# OULAD Modeler evaluation — baseline

Scope: student outcomes by module and presentation.

Confirmed business rules:
- Grain: one student enrollment per module and presentation.
- Pass rate: Pass + Distinction divided by non-withdrawn enrollments.
- Output scale: percentage.

Observed successes:
- Asked for grain and metric clarification before returning a design.
- Returned consistent table and metric references.
- Used snapshot_replace and supported dashboard card types.

Issues:
1. pass_rate references final_result without specifying its availability
   in the fact table or the required dimension join.
2. Derived fact measures have no explicit derivation rules.
3. Empty cleaning_rules has no explanation despite missing values in the profile.
4. The bar-card title promises enrollments and pass rate but references only pass_rate.

Status:
- Baseline output reviewed.
- Comparison against Tuấn's approved reference is still pending.
- This case does not evaluate studentVle grain or fan-out handling.