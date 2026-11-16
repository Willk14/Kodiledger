from app.core.migrations import migration_files, pending, with_record


def test_record_goes_inside_explicit_transaction():
    sql = "BEGIN;\nALTER TABLE t ADD COLUMN c INT;\nCOMMIT;\n"
    out = with_record(sql, "0099_x")
    assert out.index("INSERT INTO schema_migrations") < out.index("COMMIT;")
    assert out.count("COMMIT;") == 1


def test_record_appended_when_file_has_no_transaction():
    out = with_record("CREATE TABLE t (id INT);\n", "0099_x")
    assert out.rstrip().endswith("VALUES ('0099_x');")


def test_record_uses_last_commit_only():
    sql = "BEGIN;\nSELECT 1;\nCOMMIT;\nBEGIN;\nSELECT 2;\nCOMMIT;\n"
    out = with_record(sql, "0099_x")
    assert out.index("INSERT") > out.index("SELECT 2")


def test_pending_lists_unapplied_in_order():
    versions = [p.stem for p in migration_files()]
    assert versions == sorted(versions)
    assert pending(set(versions[:-1])) == [versions[-1]]
    assert pending(set(versions)) == []


def test_every_explicit_transaction_file_records_before_commit():
    for path in migration_files():
        out = with_record(path.read_text(encoding="utf-8"), path.stem)
        if "COMMIT;" in path.read_text(encoding="utf-8").upper():
            assert out.rfind("INSERT INTO schema_migrations") < out.upper().rfind("COMMIT;"), path.name
