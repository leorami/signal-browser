from pathlib import Path
from importlib import resources as importlib_resources


ROOT = Path(__file__).resolve().parents[1]


def test_readme_states_archive_is_not_a_signal_restore():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## If you replace your phone" in text
    assert "It is not a Signal restore" in text
    assert "cannot write the vault into that database" in text
    assert "does not propagate to iPhone" in text
    assert "Android only" in text
    assert "Do **not** overwrite" in text


def test_tooling_and_future_reject_write_back():
    tooling = (ROOT / "docs" / "TOOLING.md").read_text(encoding="utf-8")
    future = (ROOT / "future" / "README.md").read_text(encoding="utf-8")
    assert "## Not a restore tool" in tooling
    assert "does not write the vault back into Signal Desktop" in tooling
    assert "not write-back to Signal Desktop or iOS" in future


def test_app_history_copy_matches_restore_limits():
    app = importlib_resources.files("signal_browser").joinpath("assets", "app.html").read_text(encoding="utf-8")
    assert "These snapshots live only in this vault." in app
    assert "They do not restore Signal Desktop, iPhone, or other linked devices." in app
