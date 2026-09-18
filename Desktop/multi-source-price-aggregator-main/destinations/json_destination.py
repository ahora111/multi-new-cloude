import json
import os
from dataclasses import asdict
from .base import Destination

class JsonDestination(Destination):
    name = "json"

    def __init__(self, path):
        self.path = path

    def publish(self, products):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = [asdict(p) for p in products]
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
