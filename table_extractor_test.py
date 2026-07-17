import pdfplumber
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

def format_markdown_table(table_data):
    if not table_data or not table_data[0]:
        return ""
    # Filter out empty/None rows
    clean_rows = []
    for r in table_data:
        if r and any(cell is not None for cell in r):
            clean_rows.append([str(cell or "").replace("\n", " ").strip() for cell in r])
            
    if not clean_rows:
        return ""
        
    col_widths = [max(len(cell) for cell in col) for col in zip(*clean_rows)]
    
    md_lines = []
    # Header
    header = clean_rows[0]
    md_lines.append("| " + " | ".join(cell.ljust(w) for cell, w in zip(header, col_widths)) + " |")
    # Separator
    md_lines.append("| " + " | ".join("-" * w for w in col_widths) + " |")
    # Body rows
    for row in clean_rows[1:]:
        if len(row) < len(col_widths):
            row += [""] * (len(col_widths) - len(row))
        md_lines.append("| " + " | ".join(cell.ljust(w) for cell, w in zip(row[:len(col_widths)], col_widths)) + " |")
        
    return "\n".join(md_lines) + "\n"

def extract_content_with_tables(filepath):
    print(f"=== Content for {filepath} ===")
    with pdfplumber.open(filepath) as pdf:
        for idx, page in enumerate(pdf.pages):
            print(f"\n--- Page {idx+1} ---")
            
            tables = page.find_tables()
            md_tables = []
            if tables:
                sorted_tables = sorted(tables, key=lambda t: t.bbox[1])
                main_tables = []
                for t in sorted_tables:
                    overlap = False
                    for mt in main_tables:
                        if not (t.bbox[2] < mt.bbox[0] or t.bbox[0] > mt.bbox[2] or t.bbox[3] < mt.bbox[1] or t.bbox[1] > mt.bbox[3]):
                            overlap = True
                            break
                    if not overlap:
                        main_tables.append(t)
                
                for t in main_tables:
                    data = t.extract()
                    md = format_markdown_table(data)
                    md_tables.append((t.bbox, md))
            
            chars = page.chars
            lines_dict = {}
            for c in chars:
                in_table = False
                for bbox, _ in md_tables:
                    margin = 1
                    if (bbox[0] - margin <= c["x0"] <= bbox[2] + margin and 
                        bbox[1] - margin <= c["top"] <= bbox[3] + margin):
                        in_table = True
                        break
                if in_table:
                    continue
                    
                top_rounded = round(c["top"], 1)
                found = False
                for existing_top in lines_dict.keys():
                    if abs(existing_top - c["top"]) < 3:
                        lines_dict[existing_top].append(c)
                        found = True
                        break
                if not found:
                    lines_dict[c["top"]] = [c]
            
            items = []
            for top, line_chars in lines_dict.items():
                sorted_chars = sorted(line_chars, key=lambda c: c["x0"])
                line_str = "".join(c["text"] for c in sorted_chars)
                line_str = re.sub(r'\s+', ' ', line_str).strip()
                if line_str:
                    items.append((top, "text", line_str))
                    
            for bbox, md in md_tables:
                items.append((bbox[1], "table", md))
                
            items_sorted = sorted(items, key=lambda x: x[0])
            
            for item in items_sorted:
                if item[1] == "table":
                    print("[TABLE RENDERING]")
                    print(item[2])
                else:
                    print(f"  {item[2]}")

if __name__ == "__main__":
    extract_content_with_tables("ct200_manual.pdf")
