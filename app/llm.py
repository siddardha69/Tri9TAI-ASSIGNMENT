import os
import json
import re
import uuid
from typing import List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, ValidationError
from app.nosql import nosql_store

class TestCaseItem(BaseModel):
    steps: str
    expected_result: str
    target_node_path_key: str

class TestCasesList(BaseModel):
    test_cases: List[TestCaseItem]

def clean_llm_json_response(raw_text: str) -> str:
    """
    Cleans markdown formatting (like ```json ... ```) from the LLM output.
    """
    text = raw_text.strip()
    # Match ```json ... ``` or ``` ... ``` block
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text

def generate_mock_test_cases(nodes_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generates highly realistic, context-specific mock test cases based on the node headings and content.
    """
    test_cases = []
    
    for i, node in enumerate(nodes_context):
        path_key = node["path_key"]
        heading = node["heading"]
        body = node["body_text"]
        
        # Specific mock test cases based on the content
        if "3.2" in path_key or "Cuff Inflation Sequence" in heading:
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": "1. Place the cuff on an arm simulator.\n2. Power on the device, select User 1 profile, and press the start button.\n3. Verify initial inflation behavior.",
                "expected_result": "The cuff should inflate to an initial target pressure of 180 mmHg. Controlled deflation should occur in steps of approximately 3 mmHg.",
                "target_node_path_key": path_key,
                "original_node_hash": node["content_hash"]
            })
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": "1. Set up the arm simulator to not return a pulse detection.\n2. Initiate a blood pressure reading.\n3. Verify device behavior when pulse is not detected by 180 mmHg.",
                "expected_result": "The device must inflate in incremental steps (40 mmHg for v1 / 30 mmHg for v2) up to a maximum of 299 mmHg before aborting with an error.",
                "target_node_path_key": path_key,
                "original_node_hash": node["content_hash"]
            })
        elif "4.1" in path_key or "Overpressure Protection" in heading:
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": "1. Simulate an overpressure condition exceeding 299 mmHg during inflation.\n2. Verify response time of the emergency deflation valve.",
                "expected_result": "The emergency deflation valve must trigger immediately, halting inflation and venting the cuff to under 15 mmHg within 2 seconds.",
                "target_node_path_key": path_key,
                "original_node_hash": node["content_hash"]
            })
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": "1. Simulate sensor fault maintaining pressure > 300 mmHg for 4 seconds.\n2. Verify emergency safety behavior.",
                "expected_result": "The device should trigger deflation within 3 seconds of exceeding the 300 mmHg threshold, venting the cuff to safety.",
                "target_node_path_key": path_key,
                "original_node_hash": node["content_hash"]
            })
        elif "4.2" in path_key or "Error Codes" in heading:
            # Table-based test cases
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": "1. Unplug the cuff air hose connector.\n2. Start a measurement.\n3. Observe the error code and device behavior.",
                "expected_result": "The device must abort the measurement and display error code E1.",
                "target_node_path_key": path_key,
                "original_node_hash": node["content_hash"]
            })
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": "1. Simulate a body movement during the oscillometric measurement phase.\n2. Observe screen indicator and error code.",
                "expected_result": "The measurement must abort, display error code E2, and prompt the user to retry.",
                "target_node_path_key": path_key,
                "original_node_hash": node["content_hash"]
            })
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": "1. Create an E3 overpressure condition.\n2. Measure the elapsed time from detection to cuff deflation.",
                "expected_result": f"The device must auto-deflate within safety limits (2 seconds for v1 / 1.5 seconds for v2) and display error code E3.",
                "target_node_path_key": path_key,
                "original_node_hash": node["content_hash"]
            })
            if "E6" in body or "Bluetooth" in body:
                test_cases.append({
                    "id": str(uuid.uuid4())[:8],
                    "steps": "1. Force a Bluetooth synchronization failure between the monitor and companion app.\n2. Observe the screen display.",
                    "expected_result": "The device displays E6 on the next sync attempt; it must not affect blood pressure measurements.",
                    "target_node_path_key": path_key,
                    "original_node_hash": node["content_hash"]
                })
        else:
            # Generic context-aware fallback
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": f"Verify compliance and correctness of specs described in: {heading}.",
                "expected_result": f"Device behavior matches section details: {body[:120]}...",
                "target_node_path_key": path_key,
                "original_node_hash": node["content_hash"]
            })
            
    # Limit to 3-5 test cases
    if len(test_cases) > 5:
        test_cases = test_cases[:5]
    elif len(test_cases) < 3:
        # Pad with generic ones if needed
        for i in range(len(test_cases), 3):
            test_cases.append({
                "id": str(uuid.uuid4())[:8],
                "steps": f"Verify device operation conforms to section {nodes_context[0]['heading']}.",
                "expected_result": f"The physical output matches text: {nodes_context[0]['body_text'][:100]}...",
                "target_node_path_key": nodes_context[0]["path_key"],
                "original_node_hash": nodes_context[0]["content_hash"]
            })
            
    return test_cases

def call_llm(prompt: str) -> str:
    """
    Dispatches the prompt to Groq, Gemini, or OpenAI if keys are available.
    Raises ValueError if no keys are found or if API fails.
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    
    if groq_key:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-specdec",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        return response.choices[0].message.content
    elif gemini_key:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    elif openai_key:
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        return response.choices[0].message.content
    else:
        raise ValueError("No API key available")

def generate_test_cases_from_selection(selection_id: str, selection_name: str, version_label: str, nodes_context: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generates 3-5 test cases from selection text, enforcing structural validation.
    Integrates retry loops and falls back to mock output on persistent failures.
    """
    
    # 1. Build context text
    context_text = ""
    for n in nodes_context:
        context_text += f"Section Path: {n['path_key']}\n"
        context_text += f"Heading: {n['heading']}\n"
        context_text += f"Body:\n{n['body_text']}\n"
        context_text += "=" * 40 + "\n\n"
        
    # 2. Build system instructions and prompt
    prompt = f"""You are a QA Engineer for high-reliability medical devices.
Your task is to generate 3 to 5 clear, concrete, and repeatable QA test cases based on the provided technical documentation from the CardioTrack CT-200 blood pressure monitor.

Each test case MUST contain:
1. "steps": Step-by-step instructions on what to simulate or perform.
2. "expected_result": The expected device response or display.
3. "target_node_path_key": The exact "Section Path" from the context that this test case was generated from.

Context:
{context_text}

You MUST return ONLY a JSON object that strictly adheres to the following structure:
{{
  "test_cases": [
    {{
      "steps": "Step 1: ...\\nStep 2: ...",
      "expected_result": "Device displays ...",
      "target_node_path_key": "/3/3.2"
    }}
  ]
}}

Ensure there is no markdown code blocks outside of the JSON unless wrapped in ```json ... ```. Do not include any conversational preamble or postscript.
"""

    has_api_key = "GROQ_API_KEY" in os.environ or "GEMINI_API_KEY" in os.environ or "OPENAI_API_KEY" in os.environ
    test_cases_list = None
    
    if has_api_key:
        attempts = 3
        current_prompt = prompt
        
        for attempt in range(attempts):
            try:
                raw_response = call_llm(current_prompt)
                cleaned_response = clean_llm_json_response(raw_response)
                
                # Try parsing and validating
                data = json.loads(cleaned_response)
                validated = TestCasesList.parse_obj(data)
                
                # Check that we got between 3 and 5 test cases
                if len(validated.test_cases) < 3 or len(validated.test_cases) > 5:
                    raise ValueError(f"Generated {len(validated.test_cases)} test cases, but must be between 3 and 5.")
                    
                test_cases_list = []
                for item in validated.test_cases:
                    # Find original content hash matching the path key
                    orig_hash = ""
                    for nc in nodes_context:
                        if nc["path_key"] == item.target_node_path_key:
                            orig_hash = nc["content_hash"]
                            break
                    if not orig_hash:
                        orig_hash = nodes_context[0]["content_hash"] # fallback
                        
                    test_cases_list.append({
                        "id": str(uuid.uuid4())[:8],
                        "steps": item.steps,
                        "expected_result": item.expected_result,
                        "target_node_path_key": item.target_node_path_key,
                        "original_node_hash": orig_hash
                    })
                break # Success!
                
            except Exception as e:
                print(f"[LLM ERROR] Attempt {attempt+1} failed: {str(e)}")
                # Provide feedback loop to LLM for corrective actions
                current_prompt = f"""{prompt}
---
The previous attempt failed validation with the following error:
{str(e)}

Please correct your output and ensure that you return valid, parsed JSON conforming EXACTLY to the schema.
"""
        
    # 3. Fallback to mock generation if LLM is disabled or failed all attempts
    if not test_cases_list:
        print("[LLM FALLBACK] Using deterministic mock test-case generator.")
        test_cases_list = generate_mock_test_cases(nodes_context)
        
    # 4. Save to NoSQL store
    generation = {
        "id": str(uuid.uuid4()),
        "selection_id": selection_id,
        "selection_name": selection_name,
        "document_version": version_label,
        "nodes_context": [
            {
                "node_id": n["id"],
                "path_key": n["path_key"],
                "heading": n["heading"],
                "body_text": n["body_text"],
                "content_hash": n["content_hash"]
            } for n in nodes_context
        ],
        "test_cases": test_cases_list,
        "created_at": datetime.utcnow().isoformat()
    }
    
    nosql_store.save_generation(generation)
    return generation
