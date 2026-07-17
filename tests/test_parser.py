import unittest
import sys
import os

# Adjust path to import app package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.parser import parse_elements_to_tree

class TestManualParser(unittest.TestCase):
    
    def test_duplicate_headings(self):
        """
        Test that sections with identical heading titles but different section numbers
        (e.g., '4.2 Error Codes' and '7.1 Error Codes') are resolved uniquely in path_key
        and are mapped to their correct distinct parent nodes.
        """
        # Mock raw elements
        raw_elements = [
            (1, 10, "text", "4. Alarms and Safety Behavior"),
            (1, 15, "text", "Some alarms text..."),
            (1, 20, "text", "4.2 Error Codes"),
            (1, 25, "text", "E1, E2, E3 details..."),
            (1, 30, "text", "7. Troubleshooting"),
            (1, 35, "text", "Troubleshooting overview..."),
            (1, 40, "text", "7.1 Error Codes"),
            (1, 45, "text", "Contact support if E5 persists...")
        ]
        
        nodes = parse_elements_to_tree(raw_elements)
        
        # We expect:
        # - Node for "4"
        # - Node for "4.2"
        # - Node for "7"
        # - Node for "7.1"
        # - Plus root node (0)
        
        # Verify node counts
        self.assertEqual(len(nodes), 5)
        
        # Find the specific nodes by path_key
        node_4_2 = next(n for n in nodes if n["path_key"] == "/4/2")
        node_7_1 = next(n for n in nodes if n["path_key"] == "/7/1")
        
        self.assertEqual(node_4_2["heading"], "4.2 Error Codes")
        self.assertEqual(node_4_2["parent_path_key"], "/4")
        self.assertEqual(node_4_2["body_text"], "E1, E2, E3 details...")
        
        self.assertEqual(node_7_1["heading"], "7.1 Error Codes")
        self.assertEqual(node_7_1["parent_path_key"], "/7")
        self.assertEqual(node_7_1["body_text"], "Contact support if E5 persists...")
        
    def test_skipped_levels(self):
        """
        Test that a section with a skipped hierarchy level (e.g., '2.1.1.1' where '2.1.1'
        does not exist) dynamically parents itself to the closest existing ancestor (e.g., '/2/1')
        rather than linking to a non-existent parent path.
        """
        raw_elements = [
            (1, 10, "text", "2. Physical and Electrical Specifications"),
            (1, 20, "text", "2.1 General Specifications"),
            (1, 25, "text", "Param/Value specs..."),
            # 2.1.1.1 appears next. 2.1.1 does NOT exist.
            (1, 30, "text", "2.1.1.1 Battery Life Under Typical Use"),
            (1, 35, "text", "300 cycles battery life...")
        ]
        
        nodes = parse_elements_to_tree(raw_elements)
        
        node_2_1_1_1 = next(n for n in nodes if n["path_key"] == "/2/1/1/1")
        
        # The parent of 2.1.1.1 should be 2.1 (/2/1) because 2.1.1 (/2/1/1) doesn't exist
        self.assertEqual(node_2_1_1_1["parent_path_key"], "/2/1")
        
    def test_out_of_order_layouts(self):
        """
        Test that sections appearing out of numerical order in the PDF layout (e.g.,
        '3.4 Auto Shutoff' appearing physically before '3.3 Result Display' due to multi-column
        or page-break layout anomalies) are preserved in their physical reading order
        while maintaining correct parenting.
        """
        raw_elements = [
            (1, 10, "text", "3. Device Operation"),
            (1, 15, "text", "3.2 Cuff Inflation Sequence"),
            (1, 20, "text", "Cuff inflates to 180..."),
            # 3.4 appears physically before 3.3
            (1, 30, "text", "3.4 Auto Shutoff"),
            (1, 35, "text", "Powers off after 60 seconds..."),
            (1, 40, "text", "3.3 Result Display and Classification"),
            (1, 45, "text", "Displays systolic, diastolic...")
        ]
        
        nodes = parse_elements_to_tree(raw_elements)
        
        # Verify physical order is preserved in the flat list
        headings_in_order = [n["heading"] for n in nodes if n["section_num"] != "0"]
        expected_headings = [
            "3 Device Operation",
            "3.2 Cuff Inflation Sequence",
            "3.4 Auto Shutoff",
            "3.3 Result Display and Classification"
        ]
        self.assertEqual(headings_in_order, expected_headings)
        
        # Verify all child nodes are parented to the correct parent (/3)
        for n in nodes:
            if n["section_num"] in ["3.2", "3.3", "3.4"]:
                self.assertEqual(n["parent_path_key"], "/3")
                
    def test_list_items_ignored_as_headings(self):
        """
        Test that numbered items within a list (e.g. '1. Normal: systolic < 120')
        which contain a colon are correctly treated as body text and NOT matched as
        headings, avoiding artificial fragmentation of sections.
        """
        raw_elements = [
            (1, 10, "text", "3.3 Result Display and Classification"),
            (1, 15, "text", "Classifications:"),
            (1, 20, "text", "1. Normal: systolic < 120 and diastolic < 80"),
            (1, 25, "text", "2. Elevated: systolic 120–129 and diastolic < 80")
        ]
        
        nodes = parse_elements_to_tree(raw_elements)
        
        # We expect only the root node and section 3.3 (2 nodes total)
        self.assertEqual(len(nodes), 2)
        
        node_3_3 = nodes[1]
        self.assertEqual(node_3_3["section_num"], "3.3")
        
        # Verify list items are in the body text
        self.assertIn("1. Normal: systolic < 120", node_3_3["body_text"])
        self.assertIn("2. Elevated: systolic 120–129", node_3_3["body_text"])

if __name__ == "__main__":
    unittest.main()
