# table-qa evaluation (api)

Backend: `api`.


- **model:** qwen2.5-coder-1.5b-instruct-q4_k_m
- **backend:** api

| Id | Question | Expected | Got | value_ok | Time (s) | Notes |
|---|---|---|---|---|---|---|
| latest_order_date | What is the latest order date? | 2026-09-15 | 2026-09-15 | True | 24.9 | — |
| total_revenue | What is the total revenue? | 43290 | 43290 | True | 31.0 | — |
| top_region | Which region has the highest total revenue? | North | East | False | 60.3 | expected North, got East |
| top_product | Which product sold the most units? | Ash | Ash | True | 51.4 | — |
| fastest_growth | Which region grew fastest last quarter? | East | East | True | 103.5 | — |
| most_returns | Which region has the most returned units? | South | South | True | 38.4 | — |
| csv_total_revenue | What is the total revenue? | 43290 | 43290 | True | 20.1 | — |
| **All** | | | | **6/7** | **20.1–103.5** | |
