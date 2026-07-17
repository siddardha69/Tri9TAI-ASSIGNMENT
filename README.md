# CardioTrack CT-200 Documentation QA Pipeline

A technical manual QA pipeline for the CardioTrack CT-200 medical device. This system ingests manual editions, parses their hierarchical structure, pins requirement selections, generates QA test cases using LLMs, and detects staleness/impact when manuals are updated.

The project features a **FastAPI backend**, a **SQLite relational store for document hierarchy**, a **NoSQL JSON document store for generated QA logs**, and a **ChatGPT-style dark-mode Single-Page Application (SPA)** interface.

---

## 🛠️ Tech Stack & Architecture

*   **FastAPI**: For clean, high-performance REST APIs.
*   **Pydantic v2**: For strict schema validation and structured LLM output parsing.
*   **SQLAlchemy + SQLite**: Stores documents, manual versions, and hierarchical section nodes.
*   **JSON Document Store**: Acts as a lightweight, serverless NoSQL database (`data/nosql_store.json`) to persist generated test cases and their historical content hashes.
*   **pdfplumber**: Custom physical layout parser that extracts headings, body text, tables, and lists.
*   **ChatGPT Minimalist UI**: Dark-themed SPA (served at `/`) built with raw HTML/CSS/JS.

---

## 🚀 Setup & Execution

### 1. Prerequisites
Ensure you have Python 3.9+ installed on your machine.

### 2. Install Dependencies
Initialize a virtual environment and install the required libraries:
```bash
# Create virtual environment
python -m venv venv

# Activate on Windows:
.\venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 3. Ingest Manual Documents (v1 → v2 Ingestion Flow)
The project comes with two technical manuals: `ct200_manual.pdf` (V1) and `ct200_manual_v2.pdf` (V2).

To build/rebuild the database and trigger the parsing/ingestion flow:
```bash
python ingest_manuals.py
```
*This script will:*
1. Initialize the SQLite database `ct200_document_tree.db`.
2. Extract all structural sections and Markdown tables from `ct200_manual.pdf` and link them under version label `v1`.
3. Extract all structural sections and Markdown tables from `ct200_manual_v2.pdf` and link them under version label `v2`.
4. Calculate content hashes for each section to compare differences.

### 4. Configure API Keys (Optional)
If you want to use live LLMs to generate QA test cases, set up your keys in a `.env` file in the root directory:
```env
GROQ_API_KEY=your-groq-api-key
# OR
GEMINI_API_KEY=your-gemini-api-key
# OR
OPENAI_API_KEY=your-openai-api-key
```
*If no keys are configured, the pipeline will gracefully fall back to a high-quality deterministic mock test case generator so that all features remain interactive and functional.*

### 5. Run the Server
Start the FastAPI server:
```bash
python -m uvicorn app.main:app --port 8000
```
Open **[http://localhost:8000/](http://localhost:8000/)** in your web browser.

---

## 🧪 Running the Test Suite

We have written 9 automated unit and integration tests to verify the pipeline.
To execute them:
```bash
python -m unittest discover tests
```
The suite verifies:
*   Duplicate section heading resolution.
*   Skipped hierarchy levels (e.g. `2.1.1.1` parenting correctly when `2.1.1` is absent).
*   Correct physical reading order layouts.
*   Ignored list items containing colons.
*   API endpoints for node loading, selection pinning, and dynamic staleness analysis.
