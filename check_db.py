from app.database import SessionLocal, Document, DocumentVersion, Node

def check():
    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        print(f"Total Documents: {len(docs)}")
        for d in docs:
            print(f"Document Name: {d.name}")
            versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == d.id).all()
            print(f"  Versions: {len(versions)}")
            for v in versions:
                nodes_count = db.query(Node).filter(Node.version_id == v.id).count()
                print(f"    Label: {v.version_label}, is_latest: {v.is_latest}, Nodes count: {nodes_count}")
                
    finally:
        db.close()

if __name__ == "__main__":
    check()
