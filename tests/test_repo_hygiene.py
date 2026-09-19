"""Guards against files that tests/runtime need but git would silently ignore (this really happened)."""
import shutil
import subprocess
from conftest_helpers import ROOT

REQUIRED = ["pricecompare/data/dictionaries.yaml", "config/sources.yaml", "config/watchlist.yaml", "config/settings.yaml",
            "fixtures/shop_a.json", "fixtures/shop_b.html", "fixtures/shop_c.csv", "config.real/sources.yaml",
            "pricecompare/sources/vendor/eways_legacy.py", "pricecompare/sources/vendor/hamrahtel_scraper.py"]


def test_required_files_exist():
    missing = [f for f in REQUIRED if not (ROOT / f).exists()]
    assert not missing, missing


def test_required_files_are_not_git_ignored():
    if not shutil.which("git") or not (ROOT / ".git").exists():
        return
    ignored = [f for f in REQUIRED if subprocess.run(["git", "check-ignore", "-q", "--no-index", f], cwd=ROOT).returncode == 0]
    assert not ignored, f"ignored by .gitignore (would be missing in CI): {ignored}"
