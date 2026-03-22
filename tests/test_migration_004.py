from pathlib import Path


MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "004_update_vector_dimensions.sql"


class TestMigration004:

    def test_migration_file_exists(self):
        assert MIGRATION_PATH.exists()

    def test_contains_vector_1536(self):
        sql = MIGRATION_PATH.read_text()
        assert "vector(1536)" in sql

    def test_alters_ideas_table(self):
        sql = MIGRATION_PATH.read_text()
        assert "ALTER TABLE ideas" in sql

    def test_alters_seed_corpus_table(self):
        sql = MIGRATION_PATH.read_text()
        assert "ALTER TABLE seed_corpus" in sql

    def test_drops_old_indexes(self):
        sql = MIGRATION_PATH.read_text()
        assert "DROP INDEX" in sql

    def test_creates_new_indexes(self):
        sql = MIGRATION_PATH.read_text()
        assert "CREATE INDEX" in sql
        assert "ivfflat" in sql
