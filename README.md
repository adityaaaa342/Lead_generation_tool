# LeadPilot AI 🎯

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![Architecture: LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)

**LeadPilot AI** is an autonomous lead discovery, enrichment, and ICP scoring pipeline. It takes a plain English description of what you sell and your target customers, discovers matching companies from public sources, extracts verified contact information deterministically, and scores every lead with explainable rationales.

---

## 🏗️ Architecture

LeadPilot uses a state-machine architecture powered by **LangGraph**, prioritizing deterministic code-based extraction before calling LLMs.

```
                           User Business Brief
                                   │
                                   ▼
                       [Node 1: ICP Builder]
                     (Structured Pydantic Model)
                                   │
                                   ▼
                      [Node 2: Source Router]
              (Rule-based routing to optimal collectors)
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
  [Reddit Collector]      [OSM / Geo Collector]    [Directory / Web Crawler]
         │                         │                         │
         └─────────────────────────┼─────────────────────────┘
                                   ▼
                       [Node 4: Clean & Dedupe]
         (Levenshtein / Token-Sort >= 92 + Geographic Verification)
                                   │
                                   ▼
                          [Node 5: Enrich]
          (1. mailto/tel links ➔ 2. Schema.org JSON-LD ➔ 3. Regex ➔ 4. LLM fallback)
                                   │
                                   ▼
                        [Node 6: Email Finder]
                (MX Check + SMTP Handshake + Provenance Gate)
                                   │
                                   ▼
                          [Node 7: Score]
                 (Rule-based 5-Criteria Rubric: 0-100 pts)
                                   │
                                   ▼
                          [Node 8: Export]
                  (SQLite Persistence + Multi-Tab Excel)
```

---

## ✨ Key Features

- **Deterministic-First Extraction**: Extracts emails, phone numbers, and addresses via `mailto:`, `tel:`, Schema.org JSON-LD (`extruct`), and strict regex before falling back to LLMs.
- **Provenance & Hallucination Guard**: Every extracted data point logs its extraction method (`html_mailto`, `schema_org_jsonld`, `regex_contact_page`, `llm_parsed`) and source URL.
- **Safer Deduplication**: High-precision fuzzy matching (threshold 92) combined with mandatory city/state validation prevents false merging of distinct businesses.
- **Rule-Based Routing & Scoring**: Transparent, deterministic routing and scoring eliminate LLM non-determinism, producing reliable, repeatable rankings.
- **Multi-Channel OSINT Discovery**: Public collectors for Reddit intent posts, OpenStreetMap (Nominatim/Overpass), and web crawlers.
- **Live Streamlit Dashboard**: Clean dark-mode UI for triggering discovery runs, filtering leads by score, and exporting structured Excel reports.
- **Built-in Benchmark Evaluator**: Automated gold-set evaluator (`tests/evaluate_accuracy.py`) to measure precision, domain accuracy, and hallucination rates.

---

## ⚡ Quick Start

### 1. Prerequisites
- Python 3.10+
- (Optional) [Ollama](https://ollama.ai) for local offline LLMs, or a free Groq / Google Gemini API key.

### 2. Installation

```bash
# Clone repository
git clone https://github.com/your-username/leadpilot.git
cd leadpilot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Configure your preferred LLM provider in `.env`:

```ini
# Option A: Local Ollama (Free & Private)
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=ollama

# Option B: Groq Free Tier
# LLM_BASE_URL=https://api.groq.com/openai/v1
# LLM_MODEL=llama-3.3-70b-versatile
# LLM_API_KEY=your_groq_api_key_here

# Option C: Google Gemini Free Tier
# LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# LLM_MODEL=gemini-2.0-flash
# LLM_API_KEY=your_gemini_api_key
```

---

## 🚀 Usage

### 1. Launch the Web Dashboard (Streamlit)

```bash
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501) to enter business briefs, run discoveries, and inspect scored leads.

### 2. Run via CLI

```bash
python main.py --brief "Custom ERP and inventory management software for manufacturing SMBs in India" --limit 25
```

### 3. Offline Mock Demo

Verify pipeline compilation and data flow without network calls:

```bash
python demo/run_demo.py
```

---

## 🧪 Testing & Evaluation

### Run Test Suite
LeadPilot includes a comprehensive test suite (99 unit & integration tests):

```bash
python -m pytest tests/ -v
```

### Run Gold-Set Accuracy Benchmark
Measure extraction accuracy, domain validity, and hallucination rates against the curated gold set:

```bash
python -m tests.evaluate_accuracy --pipeline-output data/leads.xlsx
```

---

## 📁 Repository Structure

```
leadpilot/
├── app.py                   # Streamlit web application
├── main.py                  # CLI entrypoint
├── pyproject.toml           # Project configuration & build metadata
├── requirements.txt         # Dependencies
├── leadpilot/               # Core package
│   ├── collectors/          # Public data collectors (Reddit, OSM, Web)
│   ├── llm/                 # LLM client & structured prompt templates
│   ├── nodes/               # LangGraph pipeline execution nodes
│   │   ├── icp_builder.py   # Brief -> Structured ICP conversion
│   │   ├── source_router.py # Rule-based collector selection
│   │   ├── clean_dedupe.py  # High-precision entity deduplication
│   │   ├── enrich.py        # Deterministic + LLM fallback enrichment
│   │   ├── email_finder.py  # MX & pattern email verification
│   │   ├── score.py         # Multi-criteria rule-based scoring rubric
│   │   └── export.py        # Database & Excel export
│   ├── storage/             # SQLite & cache storage managers
│   ├── ui/                  # Dashboard presentation components
│   ├── utils/               # HTTP client, rate limiter, robots.txt checker
│   ├── config.py            # Pydantic configuration & environment settings
│   ├── graph.py             # LangGraph state machine definition
│   └── models.py            # Pydantic data schemas with provenance
├── tests/                   # 99 Unit tests & gold-set evaluator
│   ├── gold_set.csv         # 20-entry ground-truth benchmark dataset
│   ├── evaluate_accuracy.py # Accuracy & hallucination evaluation runner
│   ├── test_dedupe.py       # Deduplication tests
│   ├── test_email_verification.py # Email verification tests
│   ├── test_gold_set.py     # Gold set evaluation tests
│   ├── test_pipeline.py     # End-to-end integration tests
│   └── test_scoring.py      # Rule-based scoring rubric tests
└── examples/                # Specific hunter & verification scripts
```
