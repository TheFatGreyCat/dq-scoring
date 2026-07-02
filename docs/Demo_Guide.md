# DQ Score Dashboard Demo Guide

## 1. Install Dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Generate Demo Data

Run scoring for all sample datasets:

```powershell
.\.venv\Scripts\python.exe dashboard\generate_demo_data.py --datasets all
```

This writes:

- `data/rules_store/dq_rules.db`
- `data/score_store/dq_scores.db`
- JSON score artifacts under `data/score_store/`

The generator supports one or more dataset ids:

```powershell
.\.venv\Scripts\python.exe dashboard\generate_demo_data.py --datasets customer_master amazon_products
```

## 3. Run Dashboard

```powershell
.\.venv\Scripts\streamlit.exe run dashboard\app.py
```

The Streamlit app opens with:

- Overview of latest DQ Core Score per dataset.
- Dataset detail and rule breakdown.
- Issue samples joined from the Rules Engine store.
- Score trend by run timestamp.
- Methodology notes for Phase 1 scoring.

## 4. Expected Demo Checks

After generating demo data for all datasets:

- The overview contains `customer_master`, `amazon_products`, and
  `retail_sales_dataset`.
- `customer_master` includes failed rules and issue samples from the intentional
  sample data quality issues.
- `amazon_products` includes product catalog checks for required fields, price
  parsing, rating ranges, uniqueness, and price consistency.
- `retail_sales_dataset` includes transaction checks for required fields,
  domains, uniqueness, non-negative numeric values, and total amount
  consistency.

## 5. Run Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
