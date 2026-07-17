import unittest
import sys
import os
from fastapi.testclient import TestClient

# Adjust path to import app package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import SessionLocal, Node, DocumentVersion

class TestRESTAPI(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Ensure database is initialized (it was populated by ingest_manuals.py)
        cls.db = SessionLocal()
        
    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        
    def test_get_top_level_nodes(self):
        """
        Test that we can list level 1 sections for v1 and v2.
        """
        # Test default (latest version: v2)
        response = self.client.get("/api/nodes/top-level")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) > 0)
        # Ensure they are all level 1
        for node in data:
            self.assertEqual(node["level"], 1)
            
        # Test explicit v1
        response_v1 = self.client.get("/api/nodes/top-level?version_label=v1")
        self.assertEqual(response_v1.status_code, 200)
        data_v1 = response_v1.json()
        self.assertTrue(len(data_v1) > 0)
        
    def test_get_node_by_id_and_children(self):
        """
        Test getting a specific node by ID and retrieving its children ordered correctly.
        """
        # Get section 3 in v1
        section_3 = self.db.query(Node).join(DocumentVersion).filter(
            DocumentVersion.version_label == "v1",
            Node.path_key == "/3"
        ).first()
        
        self.assertIsNotNone(section_3)
        
        response = self.client.get(f"/api/nodes/{section_3.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["heading"], "3 Device Operation")
        self.assertTrue(len(data["children"]) > 0)
        
        # Verify children section numbers (e.g. 3.1, 3.2, 3.4, 3.3 in v1 physical order)
        child_sections = [c["section_num"] for c in data["children"]]
        # In our SQLite, the physical order should be retained by Python's sorting
        self.assertIn("3.1", child_sections)
        self.assertIn("3.2", child_sections)
        self.assertIn("3.4", child_sections)
        self.assertIn("3.3", child_sections)
        
    def test_search_nodes(self):
        """
        Test searching for terms across section headings and body text.
        """
        response = self.client.get("/api/nodes/search/filter?query=overpressure")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) > 0)
        self.assertTrue(any("Overpressure" in n["heading"] or "overpressure" in n["body_text"].lower() for n in data))
        
    def test_node_diff(self):
        """
        Test that we can compute diffs of a node's text between its version and the latest version.
        For battery life (2.1.1.1), it changed, so diff should show changes.
        """
        node_v1 = self.db.query(Node).join(DocumentVersion).filter(
            DocumentVersion.version_label == "v1",
            Node.path_key == "/2/1/1/1"
        ).first()
        
        self.assertIsNotNone(node_v1)
        
        response = self.client.get(f"/api/nodes/{node_v1.id}/diff")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data["has_changed"], True)
        self.assertEqual(data["v1_version"], "v1")
        self.assertEqual(data["v2_version"], "v2")
        self.assertIn("300", data["v1_text"]) # v1 has 300 cycles
        self.assertIn("250", data["v2_text"]) # v2 has 250 cycles
        self.assertIsNotNone(data["diff_summary"])
        self.assertIn("-batteries provide approximately 300", data["diff_summary"])
        self.assertIn("+batteries provide approximately 250", data["diff_summary"])

    def test_selection_pinning_and_staleness_lifecycle(self):
        """
        Test the entire selection-pinning and LLM QA generation lifecycle:
        1. Pin a selection to v1 containing:
           - A changed node: 2.1.1.1 (Battery Life)
           - An unchanged node: 5.1 (Local Storage)
        2. Generate QA test cases from the selection.
        3. Retrieve test cases and verify staleness status (stale for 2.1.1.1, valid for 5.1).
        4. Test cache hit on double-submission.
        """
        # Find nodes in v1
        node_battery = self.db.query(Node).join(DocumentVersion).filter(
            DocumentVersion.version_label == "v1",
            Node.path_key == "/2/1/1/1"
        ).first()
        
        node_storage = self.db.query(Node).join(DocumentVersion).filter(
            DocumentVersion.version_label == "v1",
            Node.path_key == "/5/1"
        ).first()
        
        v1_version = self.db.query(DocumentVersion).filter(DocumentVersion.version_label == "v1").first()
        
        self.assertIsNotNone(node_battery)
        self.assertIsNotNone(node_storage)
        self.assertIsNotNone(v1_version)
        
        # 1. Create selection pinned to v1
        payload = {
            "name": "E2E Integration Test Selection",
            "version_id": v1_version.id,
            "node_ids": [node_battery.id, node_storage.id]
        }
        
        response = self.client.post("/api/selections", json=payload)
        self.assertEqual(response.status_code, 200)
        sel_data = response.json()
        selection_id = sel_data["id"]
        
        # Verify selection is created and pinned
        self.assertEqual(sel_data["name"], "E2E Integration Test Selection")
        self.assertEqual(sel_data["version_label"], "v1")
        self.assertEqual(len(sel_data["nodes"]), 2)
        
        # 2. Generate QA test cases from selection (triggers mock LLM fallback)
        gen_response = self.client.post(f"/api/selections/{selection_id}/generate-tests")
        self.assertEqual(gen_response.status_code, 200)
        gen_data = gen_response.json()
        
        self.assertEqual(gen_data["selection_id"], selection_id)
        self.assertEqual(gen_data["document_version_label"], "v1")
        self.assertTrue(len(gen_data["test_cases"]) >= 3)
        
        # 3. Retrieve test cases and verify staleness status
        # Since v2 is the latest version, battery test cases (targeting /2/1/1/1)
        # must be stale, and storage test cases (targeting /5/1) must be valid.
        retrieve_response = self.client.get(f"/api/test-cases?selection_id={selection_id}")
        self.assertEqual(retrieve_response.status_code, 200)
        retrieved_tc = retrieve_response.json()
        
        self.assertEqual(len(retrieved_tc), len(gen_data["test_cases"]))
        
        battery_tc = [tc for tc in retrieved_tc if tc["target_node_path_key"] == "/2/1/1/1"]
        storage_tc = [tc for tc in retrieved_tc if tc["target_node_path_key"] == "/5/1"]
        
        self.assertTrue(len(battery_tc) > 0)
        self.assertTrue(len(storage_tc) > 0)
        
        # Battery test cases should be marked "stale" because /2/1/1/1 text changed in v2
        for tc in battery_tc:
            self.assertEqual(tc["staleness_status"], "stale")
            self.assertIsNotNone(tc["diff_summary"])
            # Ensure the diff reflects battery spec reduction
            self.assertIn("300", tc["diff_summary"])
            self.assertIn("250", tc["diff_summary"])
            
        # Storage test cases should be marked "valid" because /5/1 text is identical in v2
        for tc in storage_tc:
            self.assertEqual(tc["staleness_status"], "valid")
            self.assertIsNone(tc["diff_summary"])
            
        # 4. Double submission caching policy check
        # Generating tests again for the same selection without forcing should return cached results
        gen_response_2 = self.client.post(f"/api/selections/{selection_id}/generate-tests")
        self.assertEqual(gen_response_2.status_code, 200)
        gen_data_2 = gen_response_2.json()
        
        self.assertEqual(gen_data_2["generation_id"], gen_data["generation_id"]) # Identical ID implies cache hit

if __name__ == "__main__":
    unittest.main()
