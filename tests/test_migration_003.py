import os
import re

from tests.conftest import PROJECT_ROOT

MIGRATION_PATH = os.path.join(PROJECT_ROOT, "migrations", "003_add_topic_weights.sql")


def _read_sql():
    with open(MIGRATION_PATH) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Papers embedding column
# ---------------------------------------------------------------------------

class TestPapersEmbedding:

    def test_alters_papers_table(self):
        sql = _read_sql()
        assert re.search(r"ALTER\s+TABLE\s+papers", sql)

    def test_adds_embedding_vector_384(self):
        sql = _read_sql()
        assert re.search(r"ADD\s+COLUMN\s+embedding\s+vector\(384\)", sql)


# ---------------------------------------------------------------------------
# IVFFlat index on papers
# ---------------------------------------------------------------------------

class TestPapersIvfflatIndex:

    def test_creates_ivfflat_index_on_papers(self):
        sql = _read_sql()
        assert re.search(
            r"CREATE\s+INDEX\s+ON\s+papers\s+USING\s+ivfflat\s*\(\s*embedding\s+vector_cosine_ops\s*\)\s+WITH\s*\(\s*lists\s*=\s*10\s*\)",
            sql,
            re.IGNORECASE,
        )

    def test_uses_cosine_ops(self):
        sql = _read_sql()
        assert "vector_cosine_ops" in sql

    def test_uses_lists_10(self):
        sql = _read_sql()
        assert re.search(r"lists\s*=\s*10", sql)

    def test_exactly_one_index(self):
        sql = _read_sql()
        matches = re.findall(r"CREATE\s+INDEX", sql, re.IGNORECASE)
        assert len(matches) == 1


# ---------------------------------------------------------------------------
# Migration is minimal — no extra statements
# ---------------------------------------------------------------------------

class TestMigrationScope:

    def test_no_create_table(self):
        sql = _read_sql()
        assert "CREATE TABLE" not in sql

    def test_no_extension(self):
        sql = _read_sql()
        assert "CREATE EXTENSION" not in sql

    def test_alter_before_index(self):
        sql = _read_sql()
        alter_pos = sql.index("ALTER TABLE")
        index_pos = sql.index("CREATE INDEX")
        assert alter_pos < index_pos
