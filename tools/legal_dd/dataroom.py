from __future__ import annotations
from pathlib import Path
from .utils import sha256_file, utc_now, read_json, write_json

class DataroomAdapter:
    def list_items(self): raise NotImplementedError
    def read_item(self, item_id): raise NotImplementedError
    def get_updates(self): raise NotImplementedError

class LocalDataroomAdapter(DataroomAdapter):
    def __init__(self, root):
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.json"
    def _scan(self):
        items=[]
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or p.name == "manifest.json":
                continue
            rel=p.relative_to(self.root).as_posix()
            st=p.stat()
            items.append({"id":rel,"name":p.name,"path":rel,"size":st.st_size,"mtime_ns":st.st_mtime_ns,"sha256":sha256_file(p)})
        return items
    def list_items(self):
        return self._scan()
    def get_updates(self):
        old=read_json(self.manifest_path,{"items":[]}) or {"items":[]}
        oldm={x["id"]:x for x in old.get("items",[])}
        current=self._scan(); curm={x["id"]:x for x in current}
        added=[x for k,x in curm.items() if k not in oldm]
        removed=[x for k,x in oldm.items() if k not in curm]
        changed=[curm[k] for k in (curm.keys() & oldm.keys()) if curm[k]["sha256"] != oldm[k].get("sha256")]
        write_json(self.manifest_path,{"scanned_at":utc_now(),"items":current})
        return {"added":added,"changed":changed,"removed":removed,"all":current}
    def read_item(self,item_id):
        root = self.root.resolve()
        target = (root / item_id).resolve()
        if target != root and root not in target.parents:
            raise ValueError("item_id resolves outside the dataroom")
        return target.read_bytes()

class ExternalAdapterContract:
    required_methods=["list_items","read_item","get_metadata","search"]
    optional_methods=["get_updates","get_locator"]
