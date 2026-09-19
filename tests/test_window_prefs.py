from types import SimpleNamespace

from signal_browser.app.window_prefs import clamp_window_prefs, load_window_prefs, save_window_prefs


def test_window_prefs_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNAL_BROWSER_HOME", str(tmp_path / "home"))
    save_window_prefs({"x": 40, "y": 80, "width": 1400, "height": 900, "maximized": False})
    loaded = load_window_prefs()
    assert loaded["x"] == 40
    assert loaded["y"] == 80
    assert loaded["width"] == 1400
    assert loaded["height"] == 900
    assert loaded["maximized"] is False


def test_window_prefs_default_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNAL_BROWSER_HOME", str(tmp_path / "home"))
    loaded = load_window_prefs()
    assert loaded["width"] == 1200
    assert loaded["height"] == 800
    assert loaded["x"] is None


def test_clamp_rejects_offscreen_position():
    screens = [SimpleNamespace(x=0, y=0, width=1440, height=900)]
    clamped = clamp_window_prefs(
        {"x": 8000, "y": 8000, "width": 1000, "height": 700, "maximized": False},
        screens,
    )
    assert clamped["x"] is None
    assert clamped["y"] is None
    assert clamped["width"] == 1000


def test_clamp_enforces_minimum_size():
    clamped = clamp_window_prefs({"x": 10, "y": 10, "width": 100, "height": 50, "maximized": False})
    assert clamped["width"] >= 800
    assert clamped["height"] >= 560
