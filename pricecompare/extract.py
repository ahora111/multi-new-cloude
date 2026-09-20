"""Text normalisation + structured attribute extraction (Persian/English titles)."""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml

DEFAULT_DICT = Path(__file__).parent / "data" / "dictionaries.yaml"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CHARS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ؤ": "و", "أ": "ا", "إ": "ا"})
_INVIS = dict.fromkeys(map(ord, "\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u00a0"), " ")
_FA_RANGE = "\u0600-\u06FF"


@dataclass
class Attrs:
    brand: str = ""
    core: list = field(default_factory=list)
    tiers: list = field(default_factory=list)
    storage_gb: Optional[int] = None
    ram_gb: Optional[int] = None
    color: str = ""
    region: str = ""
    network: str = ""
    condition: str = ""


def parse_price(value) -> Optional[float]:
    """'49٬799٬000 تومان' / '23.190.000' / 4.98e7 -> float. None if not a price."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).translate(_DIGITS).translate(_INVIS)
    s = re.sub(r"[^\d.,٬،٫/]", "", s)
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}([.,٬،٫]\d{3})+", s):        # thousands separators
        return float(re.sub(r"[.,٬،٫]", "", s))
    if re.fullmatch(r"\d+([.,]\d{1,2})", s):               # decimal
        return float(s.replace(",", "."))
    digits = re.sub(r"\D", "", s)
    return float(digits) if digits else None


class Extractor:
    def __init__(self, dict_path: Optional[str] = None):
        d = yaml.safe_load(open(dict_path or DEFAULT_DICT, encoding="utf-8"))
        self.d = d
        self.tiers = set(d["tiers"])
        self.generic = set(map(str, d["generic_words"]))
        self.drop_brand = set(d["brand_drop_words"])
        self.phrases = sorted(d.get("phrase_map", {}).items(), key=lambda kv: -len(kv[0]))
        self.tokmap = sorted(d.get("token_map", {}).items(), key=lambda kv: -len(kv[0]))
        self.brand_alias = {a: b for b, al in d["brands"].items() for a in al}
        self._colors = self._table(d["colors"])
        self._regions = self._table(d["regions"])

    def _table(self, mapping):
        rows = []
        for canon, syns in mapping.items():
            for s in [canon] + list(syns):
                rows.append((self.normalize_text(s), canon))
        return sorted(rows, key=lambda r: -len(r[0]))

    # ---------- normalisation ----------
    def normalize_text(self, s) -> str:
        s = unicodedata.normalize("NFKC", str(s or ""))
        s = s.translate(_DIGITS).translate(_CHARS).lower().translate(_INVIS)
        s = re.sub(rf"(\d)(?=[{_FA_RANGE}])", r"\1 ", s)
        for fa, en in self.phrases:
            s = s.replace(fa, f" {en} ")
        for fa, en in self.tokmap:
            s = re.sub(rf"(?<!\w){re.escape(fa)}(?!\w)", en, s)
        # Apple sales-region codes: CH/A, ZA/A, LL/A, AE/A, HN/A, KH/A, J/A, B/A ...  ->  cha, zaa, lla ...
        s = re.sub(r"(?<!\w)(ch|za|ll|ae|hn|kh|j|b)\s*[/\-.]?\s*a(?!\w)", lambda m: m.group(1) + "a", s)
        s = re.sub(r"non[\s\-]*active", "nonactive", s)
        s = re.sub(r"(?<!\w)(1|2|3|4|6|8|12|16|18|24)\s*/\s*(32|64|128|256|512|1024)(?![\d/])", r"ram \1 \2gb", s)
        s = re.sub(r"(?<=\w)\+", " plus ", s)
        s = re.sub(r"[()\[\]{}،؛:;,|_\\\"'«»!?*]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    def _find(self, table, s):
        for syn, canon in table:
            if syn and re.search(rf"(?<!\w){re.escape(syn)}(?!\w)", s):
                return canon, syn
        return "", ""

    def color_of(self, text, explicit=False) -> str:
        t = self.normalize_text(text)
        canon, _ = self._find(self._colors, t)
        return canon or (t if explicit else "")

    @staticmethod
    def _gb(num, unit):
        v = float(num) * (1024 if unit == "tb" else 1)
        return int(round(v))

    def capacity_of(self, text) -> Optional[int]:
        t = self.normalize_text(text)
        m = re.findall(r"(\d+(?:\.\d+)?)\s*(gb|tb)", t)
        if m:
            return max(self._gb(n, u) for n, u in m)
        m = re.fullmatch(r"\D*(\d+(?:\.\d+)?)\D*", t)
        return int(float(m.group(1))) if m else None

    # ---------- attribute extraction ----------
    def parse(self, title, raw_brand="", raw_color="", raw_storage="", raw_ram="") -> Attrs:
        t = " " + self.normalize_text(title) + " "
        a = Attrs()

        m = re.search(r"(?<!\w)(nonactive|active)(?!\w)", t)
        if m:
            a.condition = m.group(1)
            t = t.replace(m.group(0), " ", 1)
        canon, syn = self._find(self._regions, t.strip())
        if canon:
            a.region = canon
            t = re.sub(rf"(?<!\w){re.escape(syn)}(?!\w)", " ", t)
        m = re.search(r"(?<!\w)([45])\s*g(?!\w)", t)
        if m:
            a.network = f"{m.group(1)}g"
            t = t.replace(m.group(0), " ", 1)

        m = (re.search(r"ram\s*[:=]?\s*(\d+)\s*(?:gb)?", t) or re.search(r"(\d+)\s*gb\s*ram", t))
        if m:
            a.ram_gb = int(m.group(1))
            t = t.replace(m.group(0), " ", 1)
        caps = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(gb|tb)(?!\w)", t))
        if caps:
            a.storage_gb = max(self._gb(c.group(1), c.group(2)) for c in caps)
            for c in reversed(caps):
                t = t[:c.start()] + " " + t[c.end():]

        canon, syn = self._find(self._colors, t.strip())
        if canon:
            a.color = canon
            t = re.sub(rf"(?<!\w){re.escape(syn)}(?!\w)", " ", t)

        brand_hint = self.normalize_text(raw_brand)
        toks = t.split()
        for tok in toks:
            if tok in self.brand_alias:
                a.brand = self.brand_alias[tok]
                break
        if not a.brand and brand_hint:
            for tok in brand_hint.split():
                if tok in self.brand_alias:
                    a.brand = self.brand_alias[tok]
                    break
            else:
                a.brand = brand_hint

        core, tiers = [], []
        for tok in t.split():
            tok = tok.strip("-./")
            if not tok or tok in self.generic or tok in self.drop_brand:
                continue
            if tok in self.tiers:
                tiers.append(tok)
                continue
            core.append(tok)
        a.core, a.tiers = core, sorted(set(tiers))

        # explicit fields (e.g. a spec table) win over title inference
        if raw_color:
            a.color = self.color_of(raw_color, explicit=True)
        if raw_storage and self.capacity_of(raw_storage):
            a.storage_gb = self.capacity_of(raw_storage)
        if raw_ram and self.capacity_of(raw_ram):
            a.ram_gb = self.capacity_of(raw_ram)
        return a
