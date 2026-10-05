from flighttrack.faa import build_faa_db, FaaLookup

MASTER_CSV = """N-NUMBER,MFR MDL CODE,YEAR MFR,MODE S CODE HEX
770TR,2072003,1979,A1B2C3
123AB,1151554,2015,ABCDEF
NOHEX,1151554,2015,
"""

REF_CSV = """CODE,MFR,MODEL
2072003,FAIRCHILD,SA227-AC
1151554,CESSNA,172S
"""


def test_build_and_lookup(tmp_path):
    (tmp_path / "MASTER.txt").write_text(MASTER_CSV)
    (tmp_path / "ACFTREF.txt").write_text(REF_CSV)
    db = tmp_path / "faa.db"
    n = build_faa_db(str(tmp_path / "MASTER.txt"), str(tmp_path / "ACFTREF.txt"), str(db))
    assert n == 2   # the row with no hex is skipped

    lk = FaaLookup(str(db))
    r = lk.lookup("A1B2C3")          # case-insensitive hex
    assert r["make"] == "FAIRCHILD" and r["model"] == "SA227-AC"
    assert r["year"] == "1979" and r["n_number"] == "N770TR"
    r2 = lk.lookup("abcdef")
    assert r2["make"] == "CESSNA" and r2["model"] == "172S"
    assert lk.lookup("FFFFFF") is None
    lk.close()


def test_missing_db_is_graceful(tmp_path):
    lk = FaaLookup(str(tmp_path / "does-not-exist.db"))
    assert lk.lookup("A1B2C3") is None
    lk.close()
