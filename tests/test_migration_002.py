import os
import re

from tests.conftest import PROJECT_ROOT

MIGRATION_PATH = os.path.join(PROJECT_ROOT, "migrations", "002_add_pgvector.sql")


def _read_sql():
    with open(MIGRATION_PATH) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Extension
# ---------------------------------------------------------------------------

class TestVectorExtension:

    def test_enables_vector_extension(self):
        sql = _read_sql()
        assert re.search(r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+vector", sql)


# ---------------------------------------------------------------------------
# Ideas embedding column
# ---------------------------------------------------------------------------

class TestIdeasEmbedding:

    def test_adds_embedding_column_to_ideas(self):
        sql = _read_sql()
        assert re.search(r"ALTER\s+TABLE\s+ideas", sql)

    def test_embedding_is_vector_384(self):
        sql = _read_sql()
        assert re.search(r"ADD\s+COLUMN\s+embedding\s+vector\(384\)", sql)


# ---------------------------------------------------------------------------
# Seed corpus table
# ---------------------------------------------------------------------------

class TestSeedCorpus:

    def test_creates_seed_corpus_table(self):
        sql = _read_sql()
        assert "CREATE TABLE seed_corpus" in sql

    def test_seed_corpus_id_serial_pk(self):
        sql = _read_sql()
        assert re.search(r"id\s+SERIAL\s+PRIMARY\s+KEY", sql)

    def test_seed_corpus_title_not_null(self):
        sql = _read_sql()
        assert re.search(r"title\s+TEXT\s+NOT\s+NULL", sql)

    def test_seed_corpus_abstract_not_null(self):
        sql = _read_sql()
        assert re.search(r"abstract\s+TEXT\s+NOT\s+NULL", sql)

    def test_seed_corpus_embedding_not_null(self):
        sql = _read_sql()
        assert re.search(r"embedding\s+vector\(384\)\s+NOT\s+NULL", sql)

    def test_seed_corpus_added_at_default_now(self):
        sql = _read_sql()
        assert re.search(r"added_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+NOW\(\)", sql)


# ---------------------------------------------------------------------------
# IVFFlat indexes
# ---------------------------------------------------------------------------

class TestIvfflatIndexes:

    def test_ideas_ivfflat_index(self):
        sql = _read_sql()
        assert re.search(
            r"CREATE\s+INDEX\s+ON\s+ideas\s+USING\s+ivfflat\s*\(\s*embedding\s+vector_cosine_ops\s*\)\s+WITH\s*\(\s*lists\s*=\s*10\s*\)",
            sql,
            re.IGNORECASE,
        )

    def test_seed_corpus_ivfflat_index(self):
        sql = _read_sql()
        assert re.search(
            r"CREATE\s+INDEX\s+ON\s+seed_corpus\s+USING\s+ivfflat\s*\(\s*embedding\s+vector_cosine_ops\s*\)\s+WITH\s*\(\s*lists\s*=\s*10\s*\)",
            sql,
            re.IGNORECASE,
        )

    def test_two_ivfflat_indexes_total(self):
        sql = _read_sql()
        matches = re.findall(r"USING\s+ivfflat", sql, re.IGNORECASE)
        assert len(matches) == 2

    def test_indexes_use_cosine_ops(self):
        sql = _read_sql()
        matches = re.findall(r"vector_cosine_ops", sql)
        assert len(matches) == 2

    def test_indexes_use_lists_10(self):
        sql = _read_sql()
        matches = re.findall(r"lists\s*=\s*10", sql)
        assert len(matches) == 2


# ---------------------------------------------------------------------------
# Ordering: extension must come before columns/indexes
# ---------------------------------------------------------------------------

class TestMigrationOrdering:

    def test_extension_before_alter_table(self):
        sql = _read_sql()
        ext_pos = sql.index("CREATE EXTENSION")
        alter_pos = sql.index("ALTER TABLE")
        assert ext_pos < alter_pos

    def test_extension_before_seed_corpus(self):
        sql = _read_sql()
        ext_pos = sql.index("CREATE EXTENSION")
        table_pos = sql.index("CREATE TABLE seed_corpus")
        assert ext_pos < table_pos
