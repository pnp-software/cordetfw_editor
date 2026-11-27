import pytest


@pytest.fixture(autouse=True)
def isolated_temp_dir(settings, tmp_path):
    """Redirect the temp directory used by CSV/ZIP import and export (settings.TEMP_DIR) to a per-test directory."""
    settings.TEMP_DIR = str(tmp_path)
    return tmp_path
