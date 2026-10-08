# LeadPilot AI 🎯

**LeadPilot AI** is an autonomous lead discovery, enrichment, and ICP scoring pipeline. It takes a description of what you sell and your target customers, discovers matching companies from public sources, extracts verified contact information deterministically, and scores every lead with clear rationales.

---

## ⚡ Quick Start

### 1. Installation

```bash
# Clone repository
git clone https://github.com/adityaaaa342/Lead_generation_tool.git
cd Lead_generation_tool

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Set your LLM configuration in `.env` (supports Ollama locally, Groq, or Gemini):

```ini
# Local Ollama (Default)
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=ollama
```

---

## 🚀 Running the Application

### 1. Launch Web Dashboard (Streamlit)

```bash
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser.

### 2. Run via CLI

```bash
python main.py --brief "Custom ERP and inventory management software for manufacturing SMBs" --limit 25
```

---

## 🧪 Tests

```bash
python -m pytest tests/ -v
```

---

## 📁 Project Structure

```
├── app.py              # Streamlit dashboard interface
├── main.py             # CLI entrypoint
├── requirements.txt    # Project dependencies
├── .env.example        # Environment variables template
├── .gitignore          # Git ignore rules
├── leadpilot/          # Core package
│   ├── collectors/     # Lead collectors (Reddit, OSM, Web)
│   ├── llm/            # LLM client & prompt templates
│   ├── nodes/          # Pipeline nodes (enrich, score, dedupe, verify)
│   ├── storage/        # Database & cache handlers
│   ├── ui/             # Dashboard UI components
│   ├── utils/          # HTTP & helper utilities
│   ├── config.py       # Configuration settings
│   ├── graph.py        # LangGraph workflow definition
│   └── models.py       # Data models & schemas
└── tests/              # Test suite & gold set evaluation
```
