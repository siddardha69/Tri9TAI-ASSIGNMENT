from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class NodeBase(BaseModel):
    section_num: str
    heading: str
    level: int
    body_text: str
    path_key: str
    parent_path_key: Optional[str] = None
    content_hash: str
    logical_node_id: str

class NodeResponse(NodeBase):
    id: int
    version_id: int
    
    class Config:
        from_attributes = True

class NodeWithChildrenResponse(NodeResponse):
    children: List[NodeResponse] = []

class DocumentVersionResponse(BaseModel):
    id: int
    version_label: str
    created_at: datetime
    is_latest: bool
    
    class Config:
        from_attributes = True

class DocumentResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
    versions: List[DocumentVersionResponse] = []
    
    class Config:
        from_attributes = True

class DiffResponse(BaseModel):
    path_key: str
    heading: str
    has_changed: bool
    v1_version: str
    v2_version: str
    v1_text: Optional[str] = None
    v2_text: Optional[str] = None
    diff_summary: Optional[str] = None

class SelectionCreate(BaseModel):
    name: str
    version_id: int
    node_ids: List[int]

class SelectionResponse(BaseModel):
    id: str
    name: str
    version_id: int
    version_label: str
    created_at: datetime
    nodes: List[NodeResponse] = []
    
    class Config:
        from_attributes = True

class TestCaseResponse(BaseModel):
    id: str
    steps: str
    expected_result: str
    target_node_path_key: str
    original_node_hash: str
    staleness_status: str # "valid", "stale", "orphaned"
    latest_node_hash: Optional[str] = None
    diff_summary: Optional[str] = None

class TestCaseGenerationResponse(BaseModel):
    generation_id: str
    selection_id: str
    selection_name: str
    document_version_label: str
    created_at: datetime
    test_cases: List[TestCaseResponse]
