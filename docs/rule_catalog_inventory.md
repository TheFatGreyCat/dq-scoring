# Rule Catalog Inventory

Runtime V2 catalog now exposes lifecycle, revision, family, backend support, applicability, exclusions, parameter schema and recommendation metadata.

Generated baseline expectations:

- At least 15 active rules.
- At least 6 rule families.
- Active rules must have backend support.
- Recommendation score is ranking score, not probability.
- Business and cross-field rules require review.

Use:

```powershell
.\.venv\Scripts\python.exe -m dq_core.cli catalog_inventory
```