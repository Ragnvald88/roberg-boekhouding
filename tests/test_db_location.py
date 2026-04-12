"""Sanity: DB_PATH default must not sit inside a known cloud-sync folder."""
from database import _DEFAULT_DB_DIR


def test_default_db_dir_not_on_cloud_sync():
    path_str = str(_DEFAULT_DB_DIR.resolve())
    bad_markers = ['SynologyDrive', 'iCloud', 'Dropbox', 'Google Drive', 'OneDrive']
    for marker in bad_markers:
        assert marker not in path_str, (
            f"_DEFAULT_DB_DIR is inside {marker} — WAL+cloud-sync corruption risk. "
            f"Got: {path_str}"
        )


def test_default_db_dir_is_per_user_app_support():
    expected = 'Application Support/Boekhouding/data'
    assert expected in str(_DEFAULT_DB_DIR), (
        f"_DEFAULT_DB_DIR should live in ~/Library/Application Support/Boekhouding/data. "
        f"Got: {_DEFAULT_DB_DIR}"
    )
