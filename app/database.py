import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = "sqlite:///./ct200_document_tree.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")

class DocumentVersion(Base):
    __tablename__ = "document_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    version_label = Column(String, index=True) # e.g. "v1", "v2"
    created_at = Column(DateTime, default=datetime.utcnow)
    is_latest = Column(Boolean, default=False)
    
    document = relationship("Document", back_populates="versions")
    nodes = relationship("Node", back_populates="version", cascade="all, delete-orphan")
    selections = relationship("Selection", back_populates="version")

class Node(Base):
    __tablename__ = "nodes"
    
    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey("document_versions.id"))
    section_num = Column(String, index=True) # e.g., "2.1.1.1"
    heading = Column(String) # e.g., "2.1.1.1 Battery Life Under Typical Use"
    level = Column(Integer) # e.g., 0, 1, 2, 4
    body_text = Column(Text)
    path_key = Column(String, index=True) # e.g., "/2/1/1/1"
    parent_path_key = Column(String, nullable=True) # e.g., "/2/1"
    content_hash = Column(String) # sha256 hash of heading + body
    logical_node_id = Column(String, index=True) # Same as path_key, identifies the node across versions
    
    version = relationship("DocumentVersion", back_populates="nodes")
    selections = relationship("SelectionNode", back_populates="node", cascade="all, delete-orphan")

class Selection(Base):
    __tablename__ = "selections"
    
    id = Column(String, primary_key=True) # UUID string
    name = Column(String)
    version_id = Column(Integer, ForeignKey("document_versions.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    version = relationship("DocumentVersion", back_populates="selections")
    selection_nodes = relationship("SelectionNode", back_populates="selection", cascade="all, delete-orphan")

class SelectionNode(Base):
    __tablename__ = "selection_nodes"
    
    selection_id = Column(String, ForeignKey("selections.id"), primary_key=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), primary_key=True)
    
    selection = relationship("Selection", back_populates="selection_nodes")
    node = relationship("Node", back_populates="selections")

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
