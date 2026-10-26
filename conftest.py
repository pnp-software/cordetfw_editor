import pytest


@pytest.fixture(autouse=True)
def isolated_temp_dir(monkeypatch, tmp_path):
    """Redirect the temp_dir used by CSV/ZIP import and export to a per-test directory."""
    from editor.configs import configs
    monkeypatch.setitem(configs['general'], 'temp_dir', str(tmp_path))
    return tmp_path
