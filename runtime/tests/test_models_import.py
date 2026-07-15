from runtime.models import Result, Account
from runtime.paths import DATA, DB_PATH

def test_result_defaults():
    r = Result(ok=True)
    assert r.ok is True
    assert r.need_relogin is False
    assert r.retryable is False
    assert r.message == ""

def test_data_paths_under_repo():
    assert DATA.name == "data"
    assert DB_PATH.name == "xpage.db"
