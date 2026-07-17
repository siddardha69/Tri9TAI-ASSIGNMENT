import os
import json
from datetime import datetime

class JSONDocumentStore:
    def __init__(self, filepath="data/nosql_store.json"):
        self.filepath = filepath
        # Ensure the directory exists
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        # Create empty store if not exists
        if not os.path.exists(self.filepath):
            self._write_store({})
            
    def _read_store(self):
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
            
    def _write_store(self, data):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
    def save_generation(self, generation_data):
        """
        Saves a generation document.
        """
        store = self._read_store()
        gen_id = generation_data["id"]
        # Convert datetimes to strings if present
        if isinstance(generation_data.get("created_at"), datetime):
            generation_data["created_at"] = generation_data["created_at"].isoformat()
        store[gen_id] = generation_data
        self._write_store(store)
        return generation_data
        
    def get_generation(self, gen_id):
        store = self._read_store()
        return store.get(gen_id)
        
    def get_all_generations(self):
        store = self._read_store()
        return list(store.values())
        
    def get_generations_by_selection(self, selection_id):
        """
        Retrieves all generations linked to a specific selection.
        """
        all_gens = self.get_all_generations()
        return [g for g in all_gens if g.get("selection_id") == selection_id]
        
    def get_generations_by_node_path(self, path_key):
        """
        Retrieves all generations that included a specific node path_key in their context.
        """
        all_gens = self.get_all_generations()
        results = []
        for g in all_gens:
            # Check if this node path key was part of the context
            node_contexts = g.get("nodes_context", [])
            if any(nc.get("path_key") == path_key for nc in node_contexts):
                results.append(g)
            else:
                # Also check inside the generated test cases target paths
                test_cases = g.get("test_cases", [])
                if any(tc.get("target_node_path_key") == path_key for tc in test_cases):
                    results.append(g)
        return results

# Singleton instance
nosql_store = JSONDocumentStore()
