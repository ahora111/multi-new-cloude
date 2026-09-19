"""Eways panel source (login required). Wraps the original, field-tested scraper in sources/vendor/.

sources.yaml:
  - name: eways
    type: eways
    currency_unit: rial            # the panel lists RIAL (the original project divided every price by 10)
    username_env: EWAYS_USERNAME   # credentials come from the environment only
    password_env: EWAYS_PASSWORD
    selected_ids: "16777:all-allz" # category selection string of the original project
    max_pages: 50
    details: candidates            # candidates | none  (spec pages are fetched only for watchlist candidates)
"""
from __future__ import annotations
import importlib
import os
from ..extract import Extractor
from .base import Source


def _legacy():
    try:
        return importlib.import_module("pricecompare.sources.vendor.eways_legacy")
    except ImportError as exc:                                        # pragma: no cover - env specific
        raise RuntimeError(f"Eways needs extra packages ({exc.name}); run: pip install -r requirements-sources.txt") from exc


class EwaysSource(Source):
    type_name = "eways"

    def _credentials(self):
        ue, pe = self.o.get("username_env", "EWAYS_USERNAME"), self.o.get("password_env", "EWAYS_PASSWORD")
        user, pw = os.environ.get(ue), os.environ.get(pe)
        if not user or not pw:
            raise RuntimeError(f"Eways credentials missing: set environment variables {ue} and {pe}")
        return user, pw

    @staticmethod
    def candidate_filter(watchlist):
        """Cheap pre-filter so spec pages are fetched only for products that could match the watchlist."""
        if not watchlist:
            return lambda name: True
        ex = Extractor()
        targets = [(w.brand, set(ex.parse(w.model).core)) for w in watchlist]

        def ok(name):
            a = ex.parse(name)
            toks = set(a.core)
            return any((not a.brand or a.brand == b) and core <= toks for b, core in targets)
        return ok

    def records(self, watchlist):
        legacy = _legacy()
        user, pw = self._credentials()
        session = legacy.login_eways(user, pw)
        if not session:
            raise RuntimeError("Eways login failed (check credentials / IP restrictions)")
        cats = legacy.get_and_parse_categories(session)
        if not cats:
            raise RuntimeError("Eways categories could not be loaded")
        legacy.init_category_index_global(cats)
        selected = self.o.get("selected_ids") or os.environ.get("SELECTED_IDS_STRING") or "16777:all-allz"
        chosen, _ = legacy.get_selected_categories_according_to_selection(legacy.parse_selected_ids_string(selected), cats)
        if not chosen:
            raise RuntimeError("No Eways categories selected (check selected_ids)")

        rows, failed = {}, 0
        for cat in chosen:
            try:
                for row in legacy.get_products_from_category_page(session, cat["id"], int(self.o.get("max_pages", 50)),
                                                                  float(self.o.get("delay", 0.5))):
                    rows[f"{row.get('id')}|{row.get('category_id')}"] = row
            except Exception:                                          # one category failing must not lose the rest
                failed += 1
        if failed and not rows:
            raise RuntimeError("All selected Eways categories failed")

        canonical = legacy.condense_products_to_leaf(rows, cats)
        self.raw_count = len(canonical)
        keep = self.candidate_filter(watchlist)
        candidates = {pid: r for pid, r in canonical.items() if keep(r.get("name") or "")}
        if candidates and self.o.get("details", "candidates") == "candidates":
            try:
                legacy.enrich_products_with_details(session, candidates, set(candidates))
            except Exception:                                          # specs are an enrichment only
                pass

        out = []
        for pid, r in candidates.items():
            specs = r.get("specs") or {}
            storage = ram = color = barcode = ""
            for k, v in specs.items():
                lk = str(k).lower()
                if "barcode" in lk or "بارکد" in lk:
                    barcode = str(v)
                elif "حافظه داخلی" in lk or "storage" in lk or lk == "حافظه":
                    storage = str(v)
                elif "ram" in lk or "رم" in lk:
                    ram = str(v)
                elif "رنگ" in lk or "color" in lk:
                    color = str(v)
            try:
                in_stock = bool(int(r.get("stock") or 0))
            except (TypeError, ValueError):
                in_stock = False
            out.append({
                "id": pid, "title": r.get("name") or "", "price": r.get("price"),
                "stock": "in_stock" if in_stock else "out_of_stock",
                "url": legacy.PRODUCT_DETAIL_URL_TEMPLATE.format(cat_id=r.get("detail_hint_cat_id") or r.get("category_id"), product_id=pid),
                "image": r.get("image") or "", "color": color, "storage": storage, "ram": ram,
                "extra": {"barcode": barcode} if barcode else {}})
        return out
