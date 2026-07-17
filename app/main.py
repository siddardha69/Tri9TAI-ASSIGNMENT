import os
import difflib
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db, init_db, Document, DocumentVersion, Node, Selection, SelectionNode
from app.nosql import nosql_store
from app.parser import parse_pdf_manual
from app.llm import generate_test_cases_from_selection
import app.schemas as schemas

from fastapi.responses import FileResponse

app = FastAPI(
    title="CardioTrack CT-200 QA Traceability API",
    description="API for technical manual ingestion, versioning, hierarchy browsing, selection pinning, and QA test-case generation with staleness detection.",
    version="1.0.0"
)

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/")
def read_root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

def get_clean_diff(text1: str, text2: str) -> str:
    """
    Computes a clean unified line diff showing additions and deletions.
    """
    if not text1:
        return "Content added in new version."
    if not text2:
        return "Content deleted in new version."
    
    diff = difflib.unified_diff(
        text1.splitlines(),
        text2.splitlines(),
        fromfile="Previous",
        tofile="Current",
        lineterm=""
    )
    return "\n".join(diff)

# =====================================================================
# 1. INGESTION & VERSIONING API
# =====================================================================

@app.post("/api/documents/ingest", response_model=schemas.DocumentResponse)
def ingest_document(
    pdf_path: str = Query(..., description="Absolute or relative path to the PDF manual"),
    version_label: str = Query(..., description="Version identifier, e.g., 'v1', 'v2'"),
    document_name: str = Query("CardioTrack CT-200", description="Document name group"),
    db: Session = Depends(get_db)
):
    """
    Ingests a PDF manual, reconstructs its section tree hierarchy, 
    calculates hashes, and registers it as a new version.
    """
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail=f"PDF file not found at {pdf_path}")
        
    try:
        parsed_nodes = parse_pdf_manual(pdf_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse PDF: {str(e)}")
        
    # Check if Document group exists
    doc = db.query(Document).filter(Document.name == document_name).first()
    if not doc:
        doc = Document(name=document_name)
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
    # Check if this version label already exists for this document
    existing_version = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc.id,
        DocumentVersion.version_label == version_label
    ).first()
    
    if existing_version:
        raise HTTPException(
            status_code=400, 
            detail=f"Version '{version_label}' already exists for document '{document_name}'"
        )
        
    # Reset all previous versions 'is_latest' flag to False
    db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc.id
    ).update({"is_latest": False})
    
    # Create the new document version
    new_version = DocumentVersion(
        document_id=doc.id,
        version_label=version_label,
        is_latest=True,
        created_at=datetime.utcnow()
    )
    db.add(new_version)
    db.commit()
    db.refresh(new_version)
    
    # Save the parsed tree hierarchy
    for p_node in parsed_nodes:
        db_node = Node(
            version_id=new_version.id,
            section_num=p_node["section_num"],
            heading=p_node["heading"],
            level=p_node["level"],
            body_text=p_node["body_text"],
            path_key=p_node["path_key"],
            parent_path_key=p_node["parent_path_key"],
            content_hash=p_node["content_hash"],
            logical_node_id=p_node["path_key"] # path key acts as logical ID
        )
        db.add(db_node)
        
    db.commit()
    db.refresh(doc)
    return doc

# =====================================================================
# 2. BROWSE & DIFF API
# =====================================================================

@app.get("/api/nodes/top-level", response_model=List[schemas.NodeResponse])
def get_top_level_sections(
    version_label: Optional[str] = Query(None, description="Filter by version. If omitted, uses latest version"),
    document_name: str = Query("CardioTrack CT-200", description="Name of the document"),
    db: Session = Depends(get_db)
):
    """
    Lists top-level sections (level 1) of the document.
    Defaults to the latest version.
    """
    # Find Document
    doc = db.query(Document).filter(Document.name == document_name).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    # Find Version
    if version_label:
        version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.version_label == version_label
        ).first()
    else:
        version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.is_latest == True
        ).first()
        
    if not version:
        raise HTTPException(status_code=404, detail="Document version not found")
        
    # Query level 1 nodes (excluding level 0 root node, including level 1)
    nodes = db.query(Node).filter(
        Node.version_id == version.id,
        Node.level == 1
    ).all()
    
    return nodes

@app.get("/api/nodes/{node_id}", response_model=schemas.NodeWithChildrenResponse)
def get_node_by_id(node_id: int, db: Session = Depends(get_db)):
    """
    Retrieves a specific node by ID, including its children, full text, and content hash.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
        
    # Query children (nodes in the same version where parent_path_key is this node's path_key)
    children = db.query(Node).filter(
        Node.version_id == node.version_id,
        Node.parent_path_key == node.path_key
    ).order_by(Node.section_num.asc()) # ordered alphabetically/numerically
    
    # Sort children properly
    # In SQLite order_by by string can be tricky, so we sort in Python
    children_list = children.all()
    try:
        # Sort by split section components if numeric, else fallback to alpha
        children_list.sort(key=lambda n: [int(x) if x.isdigit() else x for x in n.section_num.split(".")])
    except Exception:
        children_list.sort(key=lambda n: n.section_num)
        
    response = schemas.NodeWithChildrenResponse.model_validate(node)
    response.children = children_list
    return response

@app.get("/api/nodes/search/filter", response_model=List[schemas.NodeResponse])
def search_nodes(
    query: str = Query(..., description="Text query to search for inside headings or text"),
    version_label: Optional[str] = Query(None, description="Optional version to filter by (defaults to latest)"),
    document_name: str = Query("CardioTrack CT-200", description="Name of the document"),
    db: Session = Depends(get_db)
):
    """
    Searches across headings or body text for a query in the selected/latest version.
    """
    doc = db.query(Document).filter(Document.name == document_name).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    if version_label:
        version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.version_label == version_label
        ).first()
    else:
        version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.is_latest == True
        ).first()
        
    if not version:
        raise HTTPException(status_code=404, detail="Document version not found")
        
    # Search within the selected version
    search_results = db.query(Node).filter(
        Node.version_id == version.id,
        (Node.heading.like(f"%{query}%") | Node.body_text.like(f"%{query}%"))
    ).all()
    
    return search_results

@app.get("/api/nodes/{node_id}/diff", response_model=schemas.DiffResponse)
def get_node_diff(node_id: int, db: Session = Depends(get_db)):
    """
    Given a node ID in some version, returns whether its content has changed
    compared to the latest version, providing a lightweight unified diff summary.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
        
    current_version = db.query(DocumentVersion).filter(DocumentVersion.id == node.version_id).first()
    
    # Get latest version for the same document
    latest_version = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == current_version.document_id,
        DocumentVersion.is_latest == True
    ).first()
    
    if not latest_version:
        raise HTTPException(status_code=404, detail="Latest version not found")
        
    # Find matching node in the latest version by path_key (logical_node_id)
    latest_node = db.query(Node).filter(
        Node.version_id == latest_version.id,
        Node.path_key == node.path_key
    ).first()
    
    if not latest_node:
        return schemas.DiffResponse(
            path_key=node.path_key,
            heading=node.heading,
            has_changed=True,
            v1_version=current_version.version_label,
            v2_version=latest_version.version_label,
            v1_text=node.body_text,
            v2_text=None,
            diff_summary="Node was deleted in the latest version."
        )
        
    has_changed = node.content_hash != latest_node.content_hash
    diff_summary = None
    if has_changed:
        diff_summary = get_clean_diff(node.body_text, latest_node.body_text)
        
    return schemas.DiffResponse(
        path_key=node.path_key,
        heading=node.heading,
        has_changed=has_changed,
        v1_version=current_version.version_label,
        v2_version=latest_version.version_label,
        v1_text=node.body_text,
        v2_text=latest_node.body_text,
        diff_summary=diff_summary
    )

# =====================================================================
# 3. SELECTION API
# =====================================================================

@app.post("/api/selections", response_model=schemas.SelectionResponse)
def create_selection(selection_in: schemas.SelectionCreate, db: Session = Depends(get_db)):
    """
    Submits a set of node IDs to form a version-pinned "selection".
    """
    # Verify version exists
    version = db.query(DocumentVersion).filter(DocumentVersion.id == selection_in.version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail="Document version not found")
        
    selection_id = str(uuid.uuid4())
    
    db_selection = Selection(
        id=selection_id,
        name=selection_in.name,
        version_id=selection_in.version_id,
        created_at=datetime.utcnow()
    )
    db.add(db_selection)
    
    # Add nodes to selection (verifying they belong to the correct version)
    nodes = []
    for node_id in selection_in.node_ids:
        node = db.query(Node).filter(
            Node.id == node_id, 
            Node.version_id == selection_in.version_id
        ).first()
        if not node:
            raise HTTPException(
                status_code=400, 
                detail=f"Node ID {node_id} does not exist or does not belong to version ID {selection_in.version_id}"
            )
        selection_node = SelectionNode(selection_id=selection_id, node_id=node_id)
        db.add(selection_node)
        nodes.append(node)
        
    db.commit()
    
    return schemas.SelectionResponse(
        id=selection_id,
        name=db_selection.name,
        version_id=db_selection.version_id,
        version_label=version.version_label,
        created_at=db_selection.created_at,
        nodes=nodes
    )

@app.get("/api/selections", response_model=List[schemas.SelectionResponse])
def get_all_selections(db: Session = Depends(get_db)):
    """
    Lists all pinned selections with their nodes and version details.
    """
    selections = db.query(Selection).all()
    results = []
    for sel in selections:
        version = db.query(DocumentVersion).filter(DocumentVersion.id == sel.version_id).first()
        sel_nodes = db.query(SelectionNode).filter(SelectionNode.selection_id == sel.id).all()
        node_ids = [sn.node_id for sn in sel_nodes]
        nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
        results.append(schemas.SelectionResponse(
            id=sel.id,
            name=sel.name,
            version_id=sel.version_id,
            version_label=version.version_label if version else "unknown",
            created_at=sel.created_at,
            nodes=nodes
        ))
    return results

@app.get("/api/selections/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """
    Returns high-level statistics for the dashboard.
    """
    versions_count = db.query(DocumentVersion).count()
    
    # Active sections = number of nodes in the latest version
    latest_version = db.query(DocumentVersion).filter(DocumentVersion.is_latest == True).first()
    active_sections_count = 0
    if latest_version:
        active_sections_count = db.query(Node).filter(Node.version_id == latest_version.id).count()
        
    selections_count = db.query(Selection).count()
    
    # Test cases count = total test cases across all saved generations in NoSQL
    all_gens = nosql_store.get_all_generations()
    test_cases_count = sum(len(gen.get("test_cases", [])) for gen in all_gens)
    
    return {
        "versions_count": versions_count,
        "active_sections_count": active_sections_count,
        "selections_count": selections_count,
        "test_cases_count": test_cases_count
    }

@app.get("/api/selections/{selection_id}", response_model=schemas.SelectionResponse)
def get_selection(selection_id: str, db: Session = Depends(get_db)):
    """
    Retrieves a pinned selection, including all its nodes and version info.
    """
    selection = db.query(Selection).filter(Selection.id == selection_id).first()
    if not selection:
        raise HTTPException(status_code=404, detail="Selection not found")
        
    version = db.query(DocumentVersion).filter(DocumentVersion.id == selection.version_id).first()
    
    # Query nodes
    sel_nodes = db.query(SelectionNode).filter(SelectionNode.selection_id == selection_id).all()
    node_ids = [sn.node_id for sn in sel_nodes]
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
    
    return schemas.SelectionResponse(
        id=selection.id,
        name=selection.name,
        version_id=selection.version_id,
        version_label=version.version_label,
        created_at=selection.created_at,
        nodes=nodes
    )

# =====================================================================
# 4. LLM GENERATION & STALENESS API
# =====================================================================

@app.post("/api/selections/{selection_id}/generate-tests", response_model=schemas.TestCaseGenerationResponse)
def generate_tests_from_selection(
    selection_id: str,
    force_regenerate: bool = Query(False, description="Force LLM calls, bypassing caching policy"),
    db: Session = Depends(get_db)
):
    """
    LLM-powered test case generation.
    Checks cache first unless force_regenerate is True.
    """
    # 1. Fetch selection details
    selection = db.query(Selection).filter(Selection.id == selection_id).first()
    if not selection:
        raise HTTPException(status_code=404, detail="Selection not found")
        
    # Check cache policy
    if not force_regenerate:
        cached_gen = nosql_store.get_generations_by_selection(selection_id)
        if cached_gen:
            print(f"[CACHE HIT] Returning cached generation for selection {selection_id}")
            # Map cached output to schemas.TestCaseGenerationResponse
            gen = cached_gen[0]
            
            # Re-map generated test cases to TestCaseResponse (calculating current staleness at retrieval)
            version = db.query(DocumentVersion).filter(DocumentVersion.id == selection.version_id).first()
            doc = db.query(Document).filter(Document.id == version.document_id).first()
            latest_version = db.query(DocumentVersion).filter(
                DocumentVersion.document_id == doc.id,
                DocumentVersion.is_latest == True
            ).first()
            
            test_cases = []
            for tc in gen["test_cases"]:
                target_path = tc["target_node_path_key"]
                orig_hash = tc["original_node_hash"]
                
                # Check status
                latest_node = db.query(Node).filter(
                    Node.version_id == latest_version.id,
                    Node.path_key == target_path
                ).first()
                
                status = "valid"
                diff_summary = None
                latest_hash = None
                
                if not latest_node:
                    status = "orphaned"
                elif latest_node.content_hash != orig_hash:
                    status = "stale"
                    # Find original text from context saved in generation
                    original_text = ""
                    for nc in gen["nodes_context"]:
                        if nc["path_key"] == target_path:
                            original_text = nc["body_text"]
                            break
                    diff_summary = get_clean_diff(original_text, latest_node.body_text)
                    latest_hash = latest_node.content_hash
                else:
                    latest_hash = latest_node.content_hash
                    
                test_cases.append(schemas.TestCaseResponse(
                    id=tc["id"],
                    steps=tc["steps"],
                    expected_result=tc["expected_result"],
                    target_node_path_key=target_path,
                    original_node_hash=orig_hash,
                    staleness_status=status,
                    latest_node_hash=latest_hash,
                    diff_summary=diff_summary
                ))
                
            return schemas.TestCaseGenerationResponse(
                generation_id=gen["id"],
                selection_id=selection_id,
                selection_name=selection.name,
                document_version_label=version.version_label,
                created_at=datetime.fromisoformat(gen["created_at"]),
                test_cases=test_cases
            )
            
    # 2. Gather context nodes
    sel_nodes = db.query(SelectionNode).filter(SelectionNode.selection_id == selection_id).all()
    node_ids = [sn.node_id for sn in sel_nodes]
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
    
    if not nodes:
        raise HTTPException(status_code=400, detail="Selection has no nodes.")
        
    version = db.query(DocumentVersion).filter(DocumentVersion.id == selection.version_id).first()
    
    nodes_context = [
        {
            "id": n.id,
            "path_key": n.path_key,
            "heading": n.heading,
            "body_text": n.body_text,
            "content_hash": n.content_hash
        } for n in nodes
    ]
    
    # 3. Call generator (this runs the LLM call / structured validation / mock fallback)
    generation = generate_test_cases_from_selection(
        selection_id=selection_id,
        selection_name=selection.name,
        version_label=version.version_label,
        nodes_context=nodes_context
    )
    
    # 4. Map to response (since it's just generated, everything is valid relative to context)
    response_tc = [
        schemas.TestCaseResponse(
            id=tc["id"],
            steps=tc["steps"],
            expected_result=tc["expected_result"],
            target_node_path_key=tc["target_node_path_key"],
            original_node_hash=tc["original_node_hash"],
            staleness_status="valid",
            latest_node_hash=tc["original_node_hash"]
        ) for tc in generation["test_cases"]
    ]
    
    return schemas.TestCaseGenerationResponse(
        generation_id=generation["id"],
        selection_id=selection_id,
        selection_name=selection.name,
        document_version_label=version.version_label,
        created_at=datetime.fromisoformat(generation["created_at"]),
        test_cases=response_tc
    )

# =====================================================================
# 5. RETRIEVAL & STALENESS API
# =====================================================================

@app.get("/api/test-cases", response_model=List[schemas.TestCaseResponse])
def get_test_cases(
    selection_id: Optional[str] = Query(None, description="Retrieve by selection ID"),
    node_path_key: Optional[str] = Query(None, description="Retrieve by node path key, e.g. '/3/3.2'"),
    node_id: Optional[int] = Query(None, description="Retrieve by node ID"),
    db: Session = Depends(get_db)
):
    """
    Fetches generated test cases and dynamically performs impact analysis / staleness checks.
    Must provide at least one filter.
    """
    if not selection_id and not node_path_key and not node_id:
        raise HTTPException(
            status_code=400, 
            detail="Must specify at least one query parameter: selection_id, node_path_key, or node_id"
        )
        
    generations = []
    
    # Filter by node ID (resolve to path_key first)
    if node_id:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            raise HTTPException(status_code=404, detail="Node ID not found")
        node_path_key = node.path_key
        
    if selection_id:
        generations = nosql_store.get_generations_by_selection(selection_id)
    elif node_path_key:
        generations = nosql_store.get_generations_by_node_path(node_path_key)
        
    # Dynamically perform staleness checks against latest version
    # Since we want to check against the absolute latest version of the document:
    # Get latest version:
    latest_version = db.query(DocumentVersion).filter(DocumentVersion.is_latest == True).first()
    
    all_test_cases = []
    
    for gen in generations:
        for tc in gen["test_cases"]:
            target_path = tc["target_node_path_key"]
            orig_hash = tc["original_node_hash"]
            
            # If we filtered by path key, skip test cases targeting other nodes
            if node_path_key and target_path != node_path_key:
                continue
                
            status = "valid"
            diff_summary = None
            latest_hash = None
            
            if latest_version:
                latest_node = db.query(Node).filter(
                    Node.version_id == latest_version.id,
                    Node.path_key == target_path
                ).first()
                
                if not latest_node:
                    status = "orphaned"
                elif latest_node.content_hash != orig_hash:
                    status = "stale"
                    # Find original text from context saved in generation
                    original_text = ""
                    for nc in gen["nodes_context"]:
                        if nc["path_key"] == target_path:
                            original_text = nc["body_text"]
                            break
                    diff_summary = get_clean_diff(original_text, latest_node.body_text)
                    latest_hash = latest_node.content_hash
                else:
                    latest_hash = latest_node.content_hash
            else:
                # No latest version registered
                status = "valid"
                
            all_test_cases.append(schemas.TestCaseResponse(
                id=tc["id"],
                steps=tc["steps"],
                expected_result=tc["expected_result"],
                target_node_path_key=target_path,
                original_node_hash=orig_hash,
                staleness_status=status,
                latest_node_hash=latest_hash,
                diff_summary=diff_summary
            ))
            
    return all_test_cases
