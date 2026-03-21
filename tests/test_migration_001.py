import os
import re

from tests.conftest import PROJECT_ROOT

MIGRATION_PATH = os.path.join(PROJECT_ROOT, "migrations", "001_initial_schema.sql")


def _read_sql():
    with open(MIGRATION_PATH) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Table existence
# ---------------------------------------------------------------------------

class TestTablesExist:

    def test_creates_papers_table(self):
        sql = _read_sql()
        assert "CREATE TABLE papers" in sql

    def test_creates_ideas_table(self):
        sql = _read_sql()
        assert "CREATE TABLE ideas" in sql

    def test_creates_idea_feedback_table(self):
        sql = _read_sql()
        assert "CREATE TABLE idea_feedback" in sql

    def test_creates_allowed_users_table(self):
        sql = _read_sql()
        assert "CREATE TABLE allowed_users" in sql

    def test_creates_topic_weights_table(self):
        sql = _read_sql()
        assert "CREATE TABLE topic_weights" in sql


# ---------------------------------------------------------------------------
# Papers table columns
# ---------------------------------------------------------------------------

class TestPapersColumns:

    def test_id_is_text_primary_key(self):
        sql = _read_sql()
        assert re.search(r"id\s+TEXT\s+PRIMARY\s+KEY", sql)

    def test_title_not_null(self):
        sql = _read_sql()
        assert re.search(r"title\s+TEXT\s+NOT\s+NULL", sql)

    def test_abstract_not_null(self):
        sql = _read_sql()
        assert re.search(r"abstract\s+TEXT\s+NOT\s+NULL", sql)

    def test_authors_is_text_array(self):
        sql = _read_sql()
        assert re.search(r"authors\s+TEXT\[\]", sql)

    def test_categories_is_text_array(self):
        sql = _read_sql()
        assert re.search(r"categories\s+TEXT\[\]", sql)

    def test_url_not_null(self):
        sql = _read_sql()
        assert re.search(r"url\s+TEXT\s+NOT\s+NULL", sql)

    def test_source_default_arxiv(self):
        sql = _read_sql()
        assert re.search(r"source\s+TEXT\s+NOT\s+NULL\s+DEFAULT\s+'arxiv'", sql)

    def test_published_at_timestamptz(self):
        sql = _read_sql()
        assert re.search(r"published_at\s+TIMESTAMPTZ", sql)

    def test_fetched_at_default_now(self):
        sql = _read_sql()
        assert re.search(r"fetched_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+NOW\(\)", sql)

    def test_relevance_score_float(self):
        sql = _read_sql()
        assert re.search(r"relevance_score\s+FLOAT", sql)

    def test_keyword_hits_text_array(self):
        sql = _read_sql()
        assert re.search(r"keyword_hits\s+TEXT\[\]", sql)

    def test_processed_default_false(self):
        sql = _read_sql()
        assert re.search(r"processed\s+BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+FALSE", sql)

    def test_skipped_default_false(self):
        sql = _read_sql()
        assert re.search(r"skipped\s+BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+FALSE", sql)

    def test_skip_reason_column(self):
        sql = _read_sql()
        assert re.search(r"skip_reason\s+TEXT", sql)


# ---------------------------------------------------------------------------
# Ideas table columns and constraints
# ---------------------------------------------------------------------------

class TestIdeasColumns:

    def test_id_serial_primary_key(self):
        sql = _read_sql()
        assert re.search(r"id\s+SERIAL\s+PRIMARY\s+KEY", sql)

    def test_paper_id_foreign_key(self):
        sql = _read_sql()
        assert re.search(r"paper_id\s+TEXT\s+NOT\s+NULL\s+REFERENCES\s+papers\(id\)", sql)

    def test_hypothesis_not_null(self):
        sql = _read_sql()
        assert re.search(r"hypothesis\s+TEXT\s+NOT\s+NULL", sql)

    def test_method_not_null(self):
        sql = _read_sql()
        assert re.search(r"method\s+TEXT\s+NOT\s+NULL", sql)

    def test_dataset_not_null(self):
        sql = _read_sql()
        assert re.search(r"dataset\s+TEXT\s+NOT\s+NULL", sql)

    def test_novelty_score_check_constraint(self):
        sql = _read_sql()
        assert re.search(
            r"novelty_score\s+INT\s+NOT\s+NULL\s+CHECK\s*\(\s*novelty_score\s+BETWEEN\s+1\s+AND\s+10\s*\)",
            sql,
        )

    def test_feasibility_score_check_constraint(self):
        sql = _read_sql()
        assert re.search(
            r"feasibility_score\s+INT\s+NOT\s+NULL\s+CHECK\s*\(\s*feasibility_score\s+BETWEEN\s+1\s+AND\s+10\s*\)",
            sql,
        )

    def test_combined_score_generated_column(self):
        sql = _read_sql()
        assert re.search(
            r"combined_score\s+INT\s+GENERATED\s+ALWAYS\s+AS\s*\(\s*novelty_score\s*\+\s*feasibility_score\s*\)\s*STORED",
            sql,
        )

    def test_sent_at_timestamptz(self):
        sql = _read_sql()
        assert re.search(r"sent_at\s+TIMESTAMPTZ", sql)

    def test_created_at_default_now(self):
        sql = _read_sql()
        assert re.search(r"created_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+NOW\(\)", sql)


# ---------------------------------------------------------------------------
# Idea feedback table
# ---------------------------------------------------------------------------

class TestIdeaFeedbackColumns:

    def test_idea_id_foreign_key(self):
        sql = _read_sql()
        assert re.search(r"idea_id\s+INT\s+NOT\s+NULL\s+REFERENCES\s+ideas\(id\)", sql)

    def test_user_id_bigint(self):
        sql = _read_sql()
        assert re.search(r"user_id\s+BIGINT\s+NOT\s+NULL", sql)

    def test_feedback_check_constraint(self):
        sql = _read_sql()
        assert re.search(
            r"feedback\s+SMALLINT\s+NOT\s+NULL\s+CHECK\s*\(\s*feedback\s+IN\s*\(\s*-1\s*,\s*1\s*\)\s*\)",
            sql,
        )

    def test_unique_idea_user_constraint(self):
        sql = _read_sql()
        assert re.search(r"UNIQUE\s*\(\s*idea_id\s*,\s*user_id\s*\)", sql)


# ---------------------------------------------------------------------------
# Allowed users table
# ---------------------------------------------------------------------------

class TestAllowedUsersColumns:

    def test_user_id_bigint_primary_key(self):
        sql = _read_sql()
        assert re.search(r"user_id\s+BIGINT\s+PRIMARY\s+KEY", sql)

    def test_paused_default_false(self):
        sql = _read_sql()
        assert re.search(r"paused\s+BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+FALSE", sql)

    def test_pause_until_timestamptz(self):
        sql = _read_sql()
        assert re.search(r"pause_until\s+TIMESTAMPTZ", sql)

    def test_added_at_default_now(self):
        sql = _read_sql()
        assert re.search(r"added_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+NOW\(\)", sql)


# ---------------------------------------------------------------------------
# Topic weights table
# ---------------------------------------------------------------------------

class TestTopicWeightsColumns:

    def test_topic_text_primary_key(self):
        sql = _read_sql()
        assert re.search(r"topic\s+TEXT\s+PRIMARY\s+KEY", sql)

    def test_weight_default_one(self):
        sql = _read_sql()
        assert re.search(r"weight\s+FLOAT\s+NOT\s+NULL\s+DEFAULT\s+1\.0", sql)

    def test_hit_count_default_zero(self):
        sql = _read_sql()
        assert re.search(r"hit_count\s+INT\s+NOT\s+NULL\s+DEFAULT\s+0", sql)

    def test_updated_at_default_now(self):
        sql = _read_sql()
        assert re.search(r"updated_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+NOW\(\)", sql)


# ---------------------------------------------------------------------------
# Performance indexes
# ---------------------------------------------------------------------------

class TestPerformanceIndexes:

    def test_idx_papers_processed(self):
        sql = _read_sql()
        assert re.search(
            r"CREATE\s+INDEX\s+idx_papers_processed\s+ON\s+papers\s*\(\s*processed\s*,\s*fetched_at\s+DESC\s*\)",
            sql,
        )

    def test_idx_papers_relevance_partial(self):
        sql = _read_sql()
        assert re.search(
            r"CREATE\s+INDEX\s+idx_papers_relevance\s+ON\s+papers\s*\(\s*relevance_score\s+DESC\s*\)\s+WHERE\s+NOT\s+processed\s+AND\s+NOT\s+skipped",
            sql,
        )

    def test_idx_ideas_sent_at(self):
        sql = _read_sql()
        assert re.search(
            r"CREATE\s+INDEX\s+idx_ideas_sent_at\s+ON\s+ideas\s*\(\s*sent_at\s+DESC\s*\)",
            sql,
        )

    def test_idx_feedback_idea(self):
        sql = _read_sql()
        assert re.search(
            r"CREATE\s+INDEX\s+idx_feedback_idea\s+ON\s+idea_feedback\s*\(\s*idea_id\s*\)",
            sql,
        )

    def test_idx_feedback_user(self):
        sql = _read_sql()
        assert re.search(
            r"CREATE\s+INDEX\s+idx_feedback_user\s+ON\s+idea_feedback\s*\(\s*user_id\s*\)",
            sql,
        )

    def test_all_five_indexes_present(self):
        sql = _read_sql()
        index_names = re.findall(r"CREATE\s+INDEX\s+(\w+)", sql)
        expected = {
            "idx_papers_processed",
            "idx_papers_relevance",
            "idx_ideas_sent_at",
            "idx_feedback_idea",
            "idx_feedback_user",
        }
        assert expected == set(index_names)
