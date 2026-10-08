# 📖 The Plain-English Guide to LeadPilot AI

> **"Turn any business idea into a verified, ranked list of real prospects — 100% free, zero paid APIs."**

---

## 1. 🌟 The Big Picture: What is LeadPilot AI?

Traditionally, finding sales leads meant paying **thousands of dollars** for subscriptions like ZoomInfo, Apollo, or Google Maps API, only to receive outdated, messy spreadsheets.

**LeadPilot AI** replaces that entire stack with an **autonomous agent** built on free, open-source tools:
1. You describe what you sell in plain English (e.g., *"Web design for cafes in Nagpur"* or *"Copywriting for clinics in Santa Monica"*).
2. The AI figures out who to target, searches global public registries and live web forums, scrapes websites, verifies emails, eliminates duplicates, and gives every lead a score with a clear reason.
3. It exports a beautiful, clean Excel sheet ready for immediate outreach.

---

## 2. 🏗️ The 8-Stage Execution Workflow

```
   +-------------------------------------------------------------------------+
   |                     YOUR NATURAL LANGUAGE BRIEF                         |
   |   "Copywriting and design for local clinics and cafes in Santa Monica"  |
   +------------------------------------+------------------------------------+
                                        |
                                        v
   +-------------------------------------------------------------------------+
   | 🧠 STAGE 1: ICP Builder (Pydantic + LLM)                                 |
   | - Converts text into strict criteria (Industries, Roles, Locations)     |
   +------------------------------------+------------------------------------+
                                        |
                                        v
   +-------------------------------------------------------------------------+
   | 🧭 STAGE 2: Source Router                                               |
   | - Intelligently picks sources: OpenStreetMap, Directories, Reddit, Web  |
   +------------------------------------+------------------------------------+
                                        |
                                        v
   +-------------------------------------------------------------------------+
   | 🚜 STAGE 3: Multi-Source Harvester                                      |
   | - Pulls real physical businesses, coordinates, phone numbers & domains  |
   +------------------------------------+------------------------------------+
                                        |
                                        v
   +-------------------------------------------------------------------------+
   | 🧹 STAGE 4: Clean & Deduplicate (RapidFuzz + Union-Find)                |
   | - Strips 'pvt ltd', 'inc' suffixes, merges duplicates, removes web junk |
   +------------------------------------+------------------------------------+
                                        |
                                        v
   +-------------------------------------------------------------------------+
   | 🕵️ STAGE 5: Web Enrichment & Decision Maker Extraction                  |
   | - Crawls homepage/about pages, uses LLM to find Founders & Directors    |
   +------------------------------------+------------------------------------+
                                        |
                                        v
   +-------------------------------------------------------------------------+
   | ✉️ STAGE 6: Live Email Verification (dnspython + SMTP)                   |
   | - Checks syntax, live DNS MX records, and generates email permutations  |
   +------------------------------------+------------------------------------+
                                        |
                                        v
   +-------------------------------------------------------------------------+
   | ⚖️ STAGE 7: 5-Criteria Rubric & Rationale Scoring                       |
   | - Calculates 0-100 fit score and writes tailored sales pitch hook       |
   +------------------------------------+------------------------------------+
                                        |
                                        v
   +-------------------------------------------------------------------------+
   | 📊 STAGE 8: Styled Excel & SQLite Database Export                       |
   | - Clean columns, color-coded rows, zero base64 or junk fields           |
   +-------------------------------------------------------------------------+
```

---

## 3. 🔍 How Each Stage Works (Under the Hood)

### 🧠 Stage 1: The Brain — ICP Builder (`icp_builder.py`)
* **What it does:** You give it raw English. It uses the LLM to extract a formal **Ideal Customer Profile (ICP)**.
* **Output:** Target industries, decision-maker job titles (e.g. *Founder, Creative Director*), geographic limits, and negative exclusions.

### 🧭 Stage 2: The Navigator — Source Router (`source_router.py`)
* **What it does:** Determines the best collection strategy based on your target:
  * **Local Retail / Clinics / Cafes** ➡️ Routes to OpenStreetMap / Nominatim.
  * **Tech Startups / SaaS** ➡️ Routes to Directory Collector & GitHub.
  * **Consumer Intent / Discussions** ➡️ Routes to Reddit Collector.

### 🚜 Stage 3: The Harvester — Public Collectors (`osm_collector.py`, `reddit_collector.py`)
* **What it does:** Collects raw records worldwide without Google Maps fees:
  * **OpenStreetMap**: Geocodes city names into bounding boxes and extracts addresses, phone numbers, and amenities.
  * **Reddit**: Queries public search feeds (`r/CarsIndia`, `r/startups`, etc.) for active buying/hiring intent posts.

### 🧹 Stage 4: The Janitor — Clean & Dedupe (`clean_dedupe.py`)
* **What it does:** Real-world data is messy. If two sources list `"TwinkLink - The Coffee Hub"` and `"Twinklink Coffee Hub Pvt Ltd"`, it:
  1. Iteratively strips legal suffixes (`" pvt ltd"`, `" inc"`, `" llc"`).
  2. Runs **RapidFuzz** string similarity matching.
  3. Uses **Union-Find Graph Clustering** to merge them into one enriched lead with zero duplicates.

### 🕵️ Stage 5: The Detective — Web Enrichment (`enrich.py`)
* **What it does:** Visits the business's website or live search engine snippet:
  * Scrapes Schema.org tags and about/team pages.
  * Prompts the LLM to extract the actual **Founder / Marketing Director's name** and background.

### ✉️ Stage 6: The Auditor — Email Verification (`email_finder.py`)
* **What it does:** Ensures you don't get high email bounce rates:
  1. Validates email syntax.
  2. Queries live DNS servers for **MX Records** (proving the email domain exists).
  3. Generates and tests standard business patterns (`first.last@company.com`, `first@company.com`).

### ⚖️ Stage 7: The Judge — Weighted Scoring & Rationale (`score.py`)
* **What it does:** Evaluates each lead across a 5-factor rubric:
  * **Industry Fit** (30 pts)
  * **Company Size Fit** (20 pts)
  * **Tech / Buying Signal Fit** (20 pts)
  * **Geographic Fit** (15 pts)
  * **Decision Maker Seniority** (15 pts)
* The LLM writes a **custom sales hook** for each prospect explaining *why* they are a fit.

### 📊 Stage 8: The Publisher — Excel & SQLite Export (`export.py`)
* **What it does:** Writes clean records to `data/leads.xlsx` and `data/leads.db` with styled headers, alternating row colors, and zero junk/base64 strings.

---

## 4. 💡 Real-World Use Cases

| Use Case | How LeadPilot Solves It | Target Outcome |
| :--- | :--- | :--- |
| **1. Creative & Design Agencies** | Targets local businesses (Salons, Clinics, Restaurants) in cities like Santa Monica, identifying Owners and pitch angles. | High-response copywriting & branding client leads. |
| **2. Web Developers & SEOs** | Finds local businesses that **do NOT have a website** (e.g. Cafes in Nagpur) via live domain probes. | Pitching 1-page mobile sites & QR digital menus. |
| **3. B2B SaaS Startups** | Scrapes startup ecosystems (TiE, Nasscom, GitHub) for CTOs and VPs of Engineering. | Finding qualified B2B enterprise software buyers. |
| **4. Consumer Buying Intent (B2C)** | Scans Reddit forums (`r/CarsIndia`, `r/UsedCars`) for live buyer posts with specific budgets. | Direct warm leads for used car sales & dealerships. |

---

## 5. 🚀 How to Run the App

### Option A: Interactive Web Dashboard (Visual & Easiest)
```powershell
streamlit run app.py
```
* Opens `http://localhost:8501` in your browser with search bars, filters, and 1-click Excel downloads.

### Option B: Command Line (CLI)
```powershell
python main.py --brief "B2B SaaS companies in India needing DevOps automation tools" --limit 25
```

### Option C: Run the Full Test Suite
```powershell
pytest -v
```
*(Runs 68 automated unit & integration tests across all pipeline stages)*
