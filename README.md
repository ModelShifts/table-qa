<p align="center">
  <img src="assets/banner.svg" alt="table-qa" width="100%">
</p>

<p align="center"><em>Ask a spreadsheet a question in plain language and get the answer, a chart and the steps.</em></p>

<p align="center">
  <img alt="Status: in development" src="https://img.shields.io/badge/status-in%20development-8a3a24?style=flat-square">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-1c1a17?style=flat-square">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-1c1a17?style=flat-square">
  <img alt="Backends: API or Hugging Face" src="https://img.shields.io/badge/backends-API%20%7C%20Hugging%20Face-1c1a17?style=flat-square">
</p>

---

## Features

- **Excel and CSV**: upload a file; sheets and headers are detected automatically.
- **Plain-language questions**: "Which region grew fastest last quarter?"
- **Answer and chart**: a direct answer plus a chart when one helps.
- **The steps**: the exact operations used, shown as readable steps and as code you can rerun.
- **Sandboxed execution**: generated code runs in a restricted sandbox, never on your raw files.

> **Data.** Examples use synthetic or public data only.

## Architecture

```mermaid
%%{init: {"theme":"base","flowchart":{"curve":"basis","wrappingWidth":260},"themeVariables":{"fontFamily":"Georgia, Times New Roman, serif","fontSize":"14px","primaryColor":"#f3efe6","primaryTextColor":"#1c1a17","primaryBorderColor":"#1c1a17","lineColor":"#1c1a17","clusterBkg":"#faf7f0","clusterBorder":"#8a3a24","titleColor":"#8a3a24","edgeLabelBackground":"#f3efe6"}}}%%
flowchart TB
  F["Excel / CSV"]:::ink --> P["Profile sheet<br/>columns, types, samples"]:::ink
  Q["Question"]:::ink --> G
  P --> G["Plan + generate<br/>pandas code"]:::ink
  G --> X["Run in sandbox"]:::ink
  X --> A["Answer"]:::ink
  X --> C["Chart"]:::ink
  X --> ST["Steps + code"]:::ink
  subgraph BK["Backend · pick one"]
    direction LR
    A["<b>(a) Your API key</b><br/>OpenAI-compatible<br/>LLM"]:::rust
    H["<b>(b) Hugging Face</b><br/>Qwen2.5-Coder-7B-Instruct<br/>run locally"]:::rust
  end
  BK -.-> G

  classDef cl fill:#faf7f0,stroke:#8a3a24,stroke-dasharray:4 3,color:#8a3a24;
  classDef ink fill:#f3efe6,stroke:#1c1a17,color:#1c1a17,stroke-width:1px;
  classDef rust fill:#f3efe6,stroke:#8a3a24,color:#8a3a24,stroke-width:1.5px;
```

### Two interchangeable backends

Pick one with `MS_BACKEND` in `.env`. The rest of the pipeline does not change.

| | (a) Bring your own API key | (b) Open-source on Hugging Face |
|---|---|---|
| **What** | Any OpenAI-compatible endpoint | Open models, run locally or via Hugging Face Inference |
| **Set** | `MS_BACKEND=api`, `OPENAI_BASE_URL`, `OPENAI_API_KEY` | `MS_BACKEND=hf`, `HF_MODE=local` or `inference` |
| **Good for** | Fastest start, strongest hosted models | Data stays on your machines, no per-call cost |

**Default open-source models**

| Model | Used for | License |
|---|---|---|
| [`Qwen/Qwen2.5-Coder-7B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct) | planning and generating the analysis code | Apache-2.0 |
| [`Qwen/Qwen2.5-7B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) | writing the answer in plain language | Apache-2.0 |

## Quickstart

> **Coming soon.** The commands below show the planned interface.

```bash
git clone https://github.com/ModelShifts/table-qa
cd table-qa
cp .env.example .env   # choose a backend
pip install -e .
table-qa ask sales.xlsx "Which region grew fastest last quarter?"
```

## Try it

> **Coming soon.** A hosted demo will be linked here and on [modelshifts.com/work](https://modelshifts.com/work).

## Roadmap

- [x] Repository scaffold and README
- [ ] Sheet profiling
- [ ] Question to code with either backend
- [ ] Sandboxed execution
- [ ] Answer, chart and steps
- [ ] Web demo

## License

[MIT](LICENSE) © Modelshifts Technology Pte. Ltd.

<p align="center"><sub>Part of the <a href="https://modelshifts.com/work">Modelshifts</a> showcase.</sub></p>
