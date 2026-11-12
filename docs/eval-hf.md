# table-qa evaluation (hf)

Backend: `hf`.


- **model:** Qwen/Qwen2.5-Coder-1.5B-Instruct + Qwen/Qwen2.5-1.5B-Instruct
- **backend:** hf

| Id | Question | Expected | Got | value_ok | Time (s) | Notes |
|---|---|---|---|---|---|---|
| latest_order_date | What is the latest order date? | 2026-09-15 | 2026-09-15 | True | 34.5 | — |
| total_revenue | What is the total revenue? | 43290 | 43290 | True | 42.4 | — |
| top_region | Which region has the highest total revenue? | North | North | True | 61.8 | — |
| top_product | Which product sold the most units? | Ash | None | False | 137.9 | Traceback (most recent call last): |
| fastest_growth | Which region grew fastest last quarter? | East | None | False | 137.2 | Compute percentage growth with to_period('Q'). Use this shape, with the sales sh |
| most_returns | Which region has the most returned units? | South | None | False | 107.1 | Traceback (most recent call last): |
| csv_total_revenue | What is the total revenue? | 43290 | 43290 | True | 41.4 | — |
| **All** | | | | **4/7** | **34.5–137.9** | |
