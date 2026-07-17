import os
import re
import hashlib
import pdfplumber

# Regex to match numbered headings, e.g. "1. Device Overview" or "2.1 General Specifications" or "2.1.1.1 Battery Life"
# Excludes colons to avoid matching list items (e.g., "1. Normal: ...")
HEADING_REGEX = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([^:]+)$")

def calculate_hash(heading: str, body_text: str) -> str:
    norm_head = heading.strip()
    norm_body = body_text.strip()
    content = f"{norm_head}||{norm_body}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def format_markdown_table(table_data) -> str:
    if not table_data or not table_data[0]:
        return ""
    
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
        
    return "\n" + "\n".join(md_lines) + "\n"

def parse_pdf_manual(pdf_path: str):
    """
    Parses the CT-200 technical PDF manual into a hierarchical tree of nodes.
    Returns a list of node dictionaries.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF manual file not found: {pdf_path}")
        
    raw_elements = [] # list of tuples (page_num, top_y, type, content)
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_num = page_idx + 1
            
            # 1. Detect and format tables
            tables = page.find_tables()
            md_tables = []
            if tables:
                # Keep only non-overlapping tables (taking the first/largest one in case of overlaps)
                sorted_tables = sorted(tables, key=lambda t: t.bbox[1])
                main_tables = []
                for t in sorted_tables:
                    overlap = False
                    for mt in main_tables:
                        # Overlap logic (if they intersect visually)
                        if not (t.bbox[2] < mt.bbox[0] or t.bbox[0] > mt.bbox[2] or t.bbox[3] < mt.bbox[1] or t.bbox[1] > mt.bbox[3]):
                            overlap = True
                            break
                    if not overlap:
                        main_tables.append(t)
                
                for t in main_tables:
                    data = t.extract()
                    md = format_markdown_table(data)
                    if md:
                        md_tables.append((t.bbox, md))
            
            # 2. Extract characters outside table bounding boxes
            chars = page.chars
            lines_dict = {}
            for c in chars:
                in_table = False
                for bbox, _ in md_tables:
                    margin = 1 # boundary tolerance
                    if (bbox[0] - margin <= c["x0"] <= bbox[2] + margin and 
                        bbox[1] - margin <= c["top"] <= bbox[3] + margin):
                        in_table = True
                        break
                if in_table:
                    continue
                    
                # Group chars into lines by rounding their top coordinate
                found = False
                for existing_top in lines_dict.keys():
                    if abs(existing_top - c["top"]) < 3: # group threshold
                        lines_dict[existing_top].append(c)
                        found = True
                        break
                if not found:
                    lines_dict[c["top"]] = [c]
                    
            # 3. Add page-level elements
            for top, line_chars in lines_dict.items():
                sorted_chars = sorted(line_chars, key=lambda c: c["x0"])
                line_str = "".join(c["text"] for c in sorted_chars)
                line_str = re.sub(r'\s+', ' ', line_str).strip()
                if line_str:
                    raw_elements.append((page_num, top, "text", line_str))
                    
            for bbox, md in md_tables:
                raw_elements.append((page_num, bbox[1], "table", md))
                
    # Sort all raw elements physically by page number and then vertically (top coordinate)
    # This preserves the exact reading order of the document.
    raw_elements.sort(key=lambda x: (x[0], x[1]))
    
    # 4. Parse elements into nodes based on headings
    return parse_elements_to_tree(raw_elements)

def parse_elements_to_tree(raw_elements) -> list:
    """
    Constructs the section hierarchy tree from physical raw document elements.
    """
    parsed_nodes = []
    
    # Initial root node to hold any text appearing before Section 1
    current_node = {
        "section_num": "0",
        "heading": "CardioTrack CT-200 Technical & User Manual",
        "level": 0,
        "path_key": "/0",
        "parent_path_key": None,
        "body_parts": []
    }
    
    existing_paths = {"/0"}
    
    for page_num, top, item_type, content in raw_elements:
        if item_type == "text":
            match = HEADING_REGEX.match(content)
            if match:
                # Close out current node
                body_text = "\n".join(current_node["body_parts"]).strip()
                body_text = re.sub(r' +', ' ', body_text)
                
                current_node["body_text"] = body_text
                current_node["content_hash"] = calculate_hash(current_node["heading"], body_text)
                del current_node["body_parts"]
                parsed_nodes.append(current_node)
                
                section_num = match.group(1)
                heading_title = match.group(2).strip()
                level = len(section_num.split("."))
                
                parts = section_num.split(".")
                path_key = "/" + "/".join(parts)
                existing_paths.add(path_key)
                
                # Dynamic parenting to handle skipped levels
                parent_path_key = "/0"
                for k in range(len(parts) - 1, 0, -1):
                    potential_parent_path = "/" + "/".join(parts[:k])
                    if potential_parent_path in existing_paths:
                        parent_path_key = potential_parent_path
                        break
                        
                current_node = {
                    "section_num": section_num,
                    "heading": f"{section_num} {heading_title}",
                    "level": level,
                    "path_key": path_key,
                    "parent_path_key": parent_path_key,
                    "body_parts": []
                }
            else:
                current_node["body_parts"].append(content)
        else:
            # It's a table. Append it directly to the body parts.
            current_node["body_parts"].append(content)
            
    # Close out the last node
    body_text = "\n".join(current_node["body_parts"]).strip()
    body_text = re.sub(r' +', ' ', body_text)
    current_node["body_text"] = body_text
    current_node["content_hash"] = calculate_hash(current_node["heading"], body_text)
    del current_node["body_parts"]
    parsed_nodes.append(current_node)
    
    return parsed_nodes

if __name__ == "__main__":
    nodes = parse_pdf_manual("ct200_manual.pdf")
    print(f"Parsed {len(nodes)} nodes.")
    for n in nodes[:5]:
        print(f"{n['heading']} (parent: {n['parent_path_key']}) -> hash: {n['content_hash']}")
