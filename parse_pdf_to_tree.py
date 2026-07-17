import re
import hashlib
import json

HEADING_REGEX = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([^:]+)$")

def clean_text(text_list):
    text = " ".join(text_list)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def calculate_hash(heading, body_text):
    norm_head = heading.strip()
    norm_body = body_text.strip()
    content = f"{norm_head}||{norm_body}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def parse_manual(filepath):
    nodes = []
    
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    current_node = {
        "section_num": "0",
        "heading": "CardioTrack CT-200 Technical & User Manual",
        "level": 0,
        "path_key": "/0",
        "parent_path_key": None,
        "body_lines": []
    }
    
    for line in lines:
        line_str = line.strip()
        
        # Skip debug markers from the inspection txt
        if line_str.startswith("=== ct200_manual") or line_str.startswith("Total pages:") or line_str.startswith("--- Page"):
            continue
            
        match = HEADING_REGEX.match(line_str)
        if match:
            # Save current node first
            current_node["body_text"] = clean_text(current_node["body_lines"])
            del current_node["body_lines"]
            current_node["content_hash"] = calculate_hash(current_node["heading"], current_node["body_text"])
            nodes.append(current_node)
            
            section_num = match.group(1)
            heading_text = match.group(2).strip()
            level = len(section_num.split("."))
            
            parts = section_num.split(".")
            path_key = "/" + "/".join(parts)
            
            # Parent path logic: find the longest matching ancestor in current parsed list
            # Since the section numbers are prefix-based, we look up components
            parent_path_key = "/0"
            for k in range(len(parts) - 1, 0, -1):
                parent_parts = parts[:k]
                parent_path_key = "/" + "/".join(parent_parts)
                break
                
            current_node = {
                "section_num": section_num,
                "heading": f"{section_num} {heading_text}",
                "level": level,
                "path_key": path_key,
                "parent_path_key": parent_path_key,
                "body_lines": []
            }
        else:
            if line_str:
                current_node["body_lines"].append(line_str)
                
    # Save the final node
    current_node["body_text"] = clean_text(current_node["body_lines"])
    del current_node["body_lines"]
    current_node["content_hash"] = calculate_hash(current_node["heading"], current_node["body_text"])
    nodes.append(current_node)
    
    return nodes

if __name__ == "__main__":
    v1_nodes = parse_manual("ct200_manual_extracted.txt")
    v2_nodes = parse_manual("ct200_manual_v2_extracted.txt")
    
    with open("v1_parsed.json", "w", encoding="utf-8") as f:
        json.dump(v1_nodes, f, indent=2, ensure_ascii=False)
    with open("v2_parsed.json", "w", encoding="utf-8") as f:
        json.dump(v2_nodes, f, indent=2, ensure_ascii=False)
        
    print(f"Parsed V1: {len(v1_nodes)} nodes, V2: {len(v2_nodes)} nodes. Dumped to JSON.")
