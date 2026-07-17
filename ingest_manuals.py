import os
from sqlalchemy.orm import Session
from app.database import engine, Base, init_db, get_db, Document, DocumentVersion, Node
from app.parser import parse_pdf_manual
from app.database import SessionLocal

def ingest_all():
    print("Initializing Database...")
    init_db()
    
    db = SessionLocal()
    
    try:
        # Ingest V1
        v1_pdf = "ct200_manual.pdf"
        print(f"Ingesting {v1_pdf} as v1...")
        parsed_v1 = parse_pdf_manual(v1_pdf)
        
        # Check if Document group exists
        doc = db.query(Document).filter(Document.name == "CardioTrack CT-200").first()
        if not doc:
            doc = Document(name="CardioTrack CT-200")
            db.add(doc)
            db.commit()
            db.refresh(doc)
            
        # Check if v1 exists
        v1_version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.version_label == "v1"
        ).first()
        
        if not v1_version:
            v1_version = DocumentVersion(
                document_id=doc.id,
                version_label="v1",
                is_latest=False
            )
            db.add(v1_version)
            db.commit()
            db.refresh(v1_version)
            
            for p_node in parsed_v1:
                db_node = Node(
                    version_id=v1_version.id,
                    section_num=p_node["section_num"],
                    heading=p_node["heading"],
                    level=p_node["level"],
                    body_text=p_node["body_text"],
                    path_key=p_node["path_key"],
                    parent_path_key=p_node["parent_path_key"],
                    content_hash=p_node["content_hash"],
                    logical_node_id=p_node["path_key"]
                )
                db.add(db_node)
            db.commit()
            print(f"Successfully ingested {len(parsed_v1)} nodes into version v1.")
        else:
            print("Version v1 already ingested. Skipping.")
            
        # Ingest V2
        v2_pdf = "ct200_manual_v2.pdf"
        print(f"Ingesting {v2_pdf} as v2...")
        parsed_v2 = parse_pdf_manual(v2_pdf)
        
        # Check if v2 exists
        v2_version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.version_label == "v2"
        ).first()
        
        if not v2_version:
            # Set all other versions is_latest to False
            db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).update({"is_latest": False})
            
            v2_version = DocumentVersion(
                document_id=doc.id,
                version_label="v2",
                is_latest=True
            )
            db.add(v2_version)
            db.commit()
            db.refresh(v2_version)
            
            for p_node in parsed_v2:
                db_node = Node(
                    version_id=v2_version.id,
                    section_num=p_node["section_num"],
                    heading=p_node["heading"],
                    level=p_node["level"],
                    body_text=p_node["body_text"],
                    path_key=p_node["path_key"],
                    parent_path_key=p_node["parent_path_key"],
                    content_hash=p_node["content_hash"],
                    logical_node_id=p_node["path_key"]
                )
                db.add(db_node)
            db.commit()
            print(f"Successfully ingested {len(parsed_v2)} nodes into version v2.")
        else:
            print("Version v2 already ingested. Skipping.")
            
    except Exception as e:
        print(f"Error during ingestion: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    ingest_all()
