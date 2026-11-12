# Evaluation

Figures in the README and on the case page come from this table. They were measured on 12 November 2026 (Asia/Singapore) on an 8-core CPU (15 GB RAM, no GPU).

A question counts as correct when the computed value matches the ground truth in [`samples/questions.json`](../samples/questions.json) (dates as ISO, numbers exact, strings case-insensitive). The value comes from running the generated pandas in the sandbox, not from the model’s wording of the sentence. “Last quarter” and “grew fastest” use the definitions in that file.

**Command:** `python scripts/evaluate.py`

## Headline run — API backend, 1.5B coder

- **Backend:** `api`, against a local llama.cpp server
- **Model:** Qwen2.5-Coder-1.5B-Instruct, Q4_K_M GGUF (`qwen2.5-coder-1.5b-instruct-q4_k_m`)
- **Workbook:** synthetic `samples/sales.xlsx` (and `sales.csv` for the last question). All names and figures are fictional.
- **Raw:** [`eval-api.md`](eval-api.md), [`eval-api.json`](eval-api.json)

| Id | Question | Expected | Got | Correct | Time (s) | Notes |
|---|---|---|---|---|---|---|
| latest_order_date | What is the latest order date? | 2026-09-15 | 2026-09-15 | yes | 24.9 | — |
| total_revenue | What is the total revenue? | 43290 | 43290 | yes | 31.0 | — |
| top_region | Which region has the highest total revenue? | North | East | no | 60.3 | — |
| top_product | Which product sold the most units? | Ash | Ash | yes | 51.4 | — |
| fastest_growth | Which region grew fastest last quarter? | East | East | yes | 103.5 | — |
| most_returns | Which region has the most returned units? | South | South | yes | 38.4 | — |
| csv_total_revenue | What is the total revenue? (sales.csv) | 43290 | 43290 | yes | 20.1 | — |
| **All** | | | | **6/7** | **20.1–103.5** | |

## Hugging Face backend, same 1.5B size

- **Code model:** `Qwen/Qwen2.5-Coder-1.5B-Instruct`
- **Sentence model:** `Qwen/Qwen2.5-1.5B-Instruct` (loaded one at a time)
- **Raw:** [`eval-hf.md`](eval-hf.md), [`eval-hf.json`](eval-hf.json)

| Id | Expected | Got | Correct | Time (s) | Notes |
|---|---|---|---|---|---|
| latest_order_date | 2026-09-15 | 2026-09-15 | yes | 34.5 | — |
| total_revenue | 43290 | 43290 | yes | 42.4 | — |
| top_region | North | North | yes | 61.8 | — |
| top_product | Ash | None | no | 137.9 | generated code looked up a `units` column that is not in the sales sheet |
| fastest_growth | East | None | no | 137.2 | sandbox returned the prompt instead of a value |
| most_returns | South | None | no | 107.1 | same missing `units` column |
| csv_total_revenue | 43290 | 43290 | yes | 41.4 | — |
| **All** | | | **4/7** | **34.5–137.9** | |

The 7B default models have not been measured here.
