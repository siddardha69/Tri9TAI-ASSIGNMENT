# CT-200 Technical Manual QA Pipeline: Approach Document

This document outlines the design decisions, data models, parsing algorithms, versioning strategy, and LLM orchestration chosen for the CardioTrack CT-200 Technical Manual QA Pipeline assignment.

---

## 1. Data Model & Storage Decison

### Relational Schema (SQLite: `ct200_document_tree.db`)
We utilized SQLite via SQLAlchemy for the structured manual hierarchy. This matches the relational nature of structured technical documents:
*   `Document`: Represents the device documentation group ("CardioTrack CT-200").
*   `DocumentVersion`: Tracks manual editions (`v1` and `v2`). Tracks `is_latest` to know which version is the current baseline.
*   `Node`: Represents individual sections (e.g. `2.1.1.1`). Includes parent links (`parent_path_key`) to build the recursive parent-child tree, physical order sorting (`section_num`), and content checksums (`content_hash`).
*   `Selection` & `SelectionNode`: Pins user-pinned requirements to a specific manual version.

### NoSQL Document Store (`data/nosql_store.json`)
The assignment requires a NoSQL store for generated test cases. We implemented a local, thread-safe JSON-based NoSQL store.
*   **Justification:** A MongoDB instance requires local installation, user authentication, or active cloud Atlas keys, which adds setup friction for evaluation. A localized JSON store provides a serverless, zero-setup, self-contained NoSQL database that can be parsed instantly, tracked in version control, and maintains full relational mapping through UUIDs.
*   **Saved Schema:**
    ```json
    {
      "generation_id": "uuid",
      "selection_id": "uuid",
      "document_version_label": "v1",
      "test_cases": [
        {
          "id": "tc_id",
          "steps": "Step 1...",
          "expected_result": "Output...",
          "target_node_path_key": "/2/1/1/1",
          "original_node_hash": "sha256_hash_here"
        }
      ]
    }
    ```

---

## 2. Tree-Parsing Decisions & Layout Irregularities

Parsing a technical PDF manual involves several layout irregularities. Here is how our custom parser (`app/parser.py`) handled them:

### A. Duplicate Headings
*   **Irregularity:** Multiple sections share the same heading name (e.g., `4.2 Error Codes` and `7.1 Error Codes`).
*   **Solution:** We mapped nodes using logical `path_key` values constructed from their numbering prefix (e.g., `/4/2` and `/7/1`) rather than their name. This guarantees absolute uniqueness and avoids cross-linking parent-child relationships.

### B. Skipped Hierarchy Levels
*   **Irregularity:** The PDF contains sections like `2.1.1.1 Battery Life` without defining a parent section `2.1.1`.
*   **Solution:** When resolving the parent for a path key (e.g., `/2/1/1/1`), we traverse backward through the path parts (checking `/2/1/1`, then `/2/1`). The node automatically binds to the closest existing ancestor `/2/1` in the database, avoiding broken links.

### C. Out-of-Order Layouts
*   **Irregularity:** Due to multi-column text flow or page-break splits, text blocks for section `3.4` might appear physically higher on the page than section `3.3`.
*   **Solution:** We extract text characters and group them into lines by vertical `top` coordinates, then sort all items strictly by `(page_num, top_y)`. This preserves the logical reading order before rebuilding the section tree.

### D. Ignored List Items
*   **Irregularity:** Standard numbered lists (e.g., `1. Normal: systolic < 120`) can confuse regex matchers and trigger false new section nodes.
*   **Solution:** Our heading matcher regex:
    ```python
    re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([^:]+)$")
    ```
    explicitly ignores lines containing colons (`:`). This ensures lists are safely treated as body text under their parent section.

### E. Tables
*   **Irregularity:** Extracting tables as raw text destroys column-to-row relationships.
*   **Solution:** We locate tables visually using `pdfplumber.find_tables()`, strip out character blocks within those table bounds, format the tabular data into standard Markdown tables, and inject them as body text.

---

## 3. Version-Matching & Staleness Flow

### Logical Node Mapping
Because sections can move or change, we link nodes across versions using their logical `path_key` (e.g., `/2/1/1/1`).

### Staleness Identification
When a user requests test cases for a pinned selection, the API executes a real-time comparison:
1. It looks up the current baseline node in the latest document version using the test case's `target_node_path_key`.
2. It compares the `original_node_hash` (saved inside the NoSQL test case) with the `content_hash` of the latest node.
3. If they don't match, the test case is marked **`Stale`**, and a line-by-line diff is generated.
4. If the section path is missing in the latest version, it is marked **`Orphaned`**.

### Known Failure Modes
*   **Major Renumbering:** If the manufacturer renumbers section `/2/1/1/1` to `/2/1/2` in v2 but leaves the text identical, the system will flag the old path as *Orphaned* and won't automatically carry over the test case to the new path.
*   **Table-to-Text Conversion:** If a specifications table is modified, the Markdown layout text changes. While the diff viewer highlights the raw line edit, it is visually less intuitive than a graphical table diff.

---

### Prompt Engineering
The system prompt feeds the target section headings and body texts into the model, instructing it to act as a medical QA engineer. It mandates returning a strict JSON object mapping steps, expected results, and traceability path keys.

### LLM Providers & Output Validation
The system supports multiple LLM providers:
1. **Groq Free-Tier (Default if key provided):** Integrates the ultra-fast `llama-3.3-70b-specdec` model via OpenAI-compatible endpoint.
2. **Gemini API:** Uses `gemini-1.5-flash`.
3. **OpenAI API:** Uses `gpt-4o-mini`.

We implemented strict validation:
1. **JSON Cleaning:** A utility function to strip out markdown blocks (` ```json ... ``` `).
2. **Pydantic Validation:** The output is fed into a Pydantic model (`TestCasesList`).
3. **Corrective Feedback Loop:** If parsing fails, the system automatically starts a retry loop (up to 3 attempts), feeding the error message back to the LLM so it can correct its schema.
4. **Fallback:** If all retries fail, it invokes the local mock generator to guarantee service uptime.

---

## 5. What We'd Do Differently with More Time

---

## 6. Decision Log (Mandatory Task 12)

### Q1: Which part of your system is most likely to silently produce incorrect results? How would you detect it?
*   **Silent Failure Point:** The **PDF Hierarchy Parser**. If a manual contains sections numbered non-standardly (e.g. `"Section A-1"` or roman numerals `"IV. Specifications"`), the header regex (`HEADING_REGEX`) will fail to identify them. These sections will silently be merged into the body text of the preceding section, causing incorrect logical grouping.
*   **How to Detect It:** We can run an **extraction integrity check** after parsing: calculate the total text character count extracted from the PDF pages, and compare it against the sum of the text lengths of all parsed nodes. A mismatch greater than a threshold (e.g., 5%) indicates that text was incorrectly grouped or skipped.

### Q2: Where did you simplify the implementation due to time constraints, and what would likely fail first in production?
*   **Simplification:** We implemented the NoSQL document store using a local, file-based JSON store (`data/nosql_store.json`) with an in-memory lock instead of a containerized MongoDB or cloud-based PostgreSQL instance.
*   **Production Failure Point:** Under high concurrency (multiple QA engineers pinning selections and generating test cases simultaneously), the file-based JSON store will become a write-bottleneck. File lock contentions or raw read/write race conditions could result in data corruption or slow request timeouts. 

### Q3: Name one type of input your parser, version matcher, or LLM handling does not support, and explain how your system behaves when it encounters it.
*   **Unsupported Input Type:** **Scanned PDF manuals (pure image PDFs)**.
*   **System Behavior:** Our parser uses character-coordinate mapping through `pdfplumber` to extract text and tables. If a manual is a scanned image with no embedded text layer, `pdfplumber` will return empty text blocks. The system will fail to extract any nodes, resulting in an empty database hierarchy and log warnings. To support this, an OCR pre-processing layer (such as `pytesseract` or `easyocr`) would be required.
