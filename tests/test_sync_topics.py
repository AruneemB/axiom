from unittest.mock import MagicMock, call

import pytest

from scripts.sync_topics import sync_topic_weights


class TestSyncTopicWeights:

    def test_inserts_new_topics(self):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.fetchone.return_value = {"count": 3}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        topics = ["momentum", "volatility", "arbitrage"]
        result = sync_topic_weights(mock_conn, topics)

        assert result["inserted"] == 3
        assert result["total"] == 3
        assert mock_cursor.execute.call_count == 4  # 3 inserts + 1 count query

    def test_lowercases_and_strips_topics(self):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.fetchone.return_value = {"count": 2}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        topics = ["  Momentum  ", "VOLATILITY"]
        result = sync_topic_weights(mock_conn, topics)

        # Check that topics were lowercased and stripped
        insert_calls = [c for c in mock_cursor.execute.call_args_list if "INSERT" in c[0][0]]
        assert len(insert_calls) == 2
        assert insert_calls[0][0][1] == ("momentum",)
        assert insert_calls[1][0][1] == ("volatility",)

    def test_uses_on_conflict_do_nothing(self):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0  # No rows inserted (already exists)
        mock_cursor.fetchone.return_value = {"count": 1}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        topics = ["momentum"]
        result = sync_topic_weights(mock_conn, topics)

        assert result["inserted"] == 0  # Already existed
        assert result["total"] == 1
        # Verify ON CONFLICT DO NOTHING is in the query
        insert_query = mock_cursor.execute.call_args_list[0][0][0]
        assert "ON CONFLICT" in insert_query
        assert "DO NOTHING" in insert_query

    def test_commits_transaction(self):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.fetchone.return_value = {"count": 1}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        topics = ["momentum"]
        sync_topic_weights(mock_conn, topics)

        mock_conn.commit.assert_called_once()

    def test_handles_empty_topic_list(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"count": 0}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        topics = []
        result = sync_topic_weights(mock_conn, topics)

        assert result["inserted"] == 0
        assert result["total"] == 0
        # Should only run the count query, no inserts
        assert mock_cursor.execute.call_count == 1

    def test_handles_multiple_topics(self):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor.fetchone.return_value = {"count": 3}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        topics = ["topic1", "topic2", "topic3"]
        result = sync_topic_weights(mock_conn, topics)

        # All topics inserted
        assert result["inserted"] == 3
        assert result["total"] == 3
        # Should execute 3 inserts + 1 count query
        assert mock_cursor.execute.call_count == 4
