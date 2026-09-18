from .base import Source

class DemoSource(Source):
    name = "demo"

    def __init__(self, products):
        self.products = products

    def fetch(self):
        return list(self.products)
