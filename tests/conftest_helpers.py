"""Shared helpers (plain module so it works with pytest and the offline runner)."""
import shutil
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent


def make_project(tmp_path, settings=None, sources=None, watchlist=None):
    """Copy config + fixtures into tmp_path; paths inside settings are made absolute/temporary."""
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    shutil.copytree(ROOT / "fixtures", tmp_path / "fixtures")
    st = yaml.safe_load((cfg / "settings.yaml").read_text(encoding="utf-8"))
    st.update({"output_dir": str(tmp_path / "out"), "history_file": str(tmp_path / "history.jsonl"),
               "cache_dir": str(tmp_path / "cache"), "lock_file": str(tmp_path / "run.lock"),
               "telegram_state_file": str(tmp_path / "tg_state.json")})
    st.update(settings or {})
    (cfg / "settings.yaml").write_text(yaml.safe_dump(st, allow_unicode=True), encoding="utf-8")
    if sources is not None:
        (cfg / "sources.yaml").write_text(yaml.safe_dump({"sources": sources}, allow_unicode=True), encoding="utf-8")
    if watchlist is not None:
        (cfg / "watchlist.yaml").write_text(yaml.safe_dump({"products": watchlist}, allow_unicode=True), encoding="utf-8")
    # Unit/integration tests must never depend on live Farnaa HTTP data.
    # Only the default test project is redirected to the committed fixture.
    # Explicitly supplied source configurations are preserved verbatim so tests
    # can intentionally simulate broken/all-failed sources.
    if sources is None:
        src_path = cfg / "sources.yaml"
        src_data = yaml.safe_load(src_path.read_text(encoding="utf-8"))
        for source in src_data.get("sources", []):
            if source.get("type") == "farnaa":
                source.pop("url", None)
                source["path"] = "fixtures/farnaa_mobile.html"
        src_path.write_text(yaml.safe_dump(src_data, allow_unicode=True), encoding="utf-8")
    return str(cfg), str(tmp_path)


def load_sources_yaml(tmp_path):
    return yaml.safe_load((Path(tmp_path) / "config" / "sources.yaml").read_text(encoding="utf-8"))["sources"]
