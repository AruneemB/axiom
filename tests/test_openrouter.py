import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from lib.openrouter import _validate_idea, OPENROUTER_BASE, SYSTEM_PROMPT


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestModuleConstants:

    def test_openrouter_base_url(self):
        assert OPENROUTER_BASE == "https://openrouter.ai/api/v1"

    def test_system_prompt_loaded(self):
        assert "quantitative researcher" in SYSTEM_PROMPT
        assert SYSTEM_PROMPT.endswith("No preamble, no markdown fences.")

    def test_system_prompt_no_markdown_fences(self):
        assert "```" not in SYSTEM_PROMPT


class TestValidateIdeaRejectsMissingFields:

    def test_rejects_hypothesis_only(self):
        assert _validate_idea({"hypothesis": "x"}) is None

    def test_rejects_missing_scores(self):
        result = _validate_idea({
            "hypothesis": "We hypothesize that...",
            "method": "OLS regression...",
            "dataset": "CRSP...",
        })
        assert result is None

    def test_rejects_missing_dataset(self):
        result = _validate_idea({
            "hypothesis": "We hypothesize that...",
            "method": "OLS regression...",
            "novelty_score": 7,
            "feasibility_score": 8,
        })
        assert result is None

    def test_rejects_empty_dict(self):
        assert _validate_idea({}) is None


class TestValidateIdeaAcceptsValid:

    def test_returns_valid_idea(self):
        idea = {
            "hypothesis": "We hypothesize that...",
            "method": "We run an OLS regression...",
            "dataset": "CRSP daily returns...",
            "novelty_score": 7,
            "feasibility_score": 8,
        }
        result = _validate_idea(idea)
        assert result is not None
        assert result["novelty_score"] == 7
        assert result["feasibility_score"] == 8

    def test_returns_stripped_strings(self):
        idea = {
            "hypothesis": "  We hypothesize that...  ",
            "method": "  OLS regression  ",
            "dataset": "  CRSP  ",
            "novelty_score": 5,
            "feasibility_score": 6,
        }
        result = _validate_idea(idea)
        assert result["hypothesis"] == "We hypothesize that..."
        assert result["method"] == "OLS regression"
        assert result["dataset"] == "CRSP"

    def test_casts_scores_to_int(self):
        idea = {
            "hypothesis": "h",
            "method": "m",
            "dataset": "d",
            "novelty_score": "7",
            "feasibility_score": "8",
        }
        result = _validate_idea(idea)
        assert result["novelty_score"] == 7
        assert isinstance(result["novelty_score"], int)

    def test_boundary_scores_1_and_10(self):
        for n, f in [(1, 1), (10, 10), (1, 10), (10, 1)]:
            idea = {
                "hypothesis": "h",
                "method": "m",
                "dataset": "d",
                "novelty_score": n,
                "feasibility_score": f,
            }
            result = _validate_idea(idea)
            assert result is not None, f"Failed for novelty={n}, feasibility={f}"


class TestValidateIdeaPicksBestFromList:

    def test_picks_highest_combined_score(self):
        raw = {
            "ideas": [
                {"hypothesis": "a", "method": "m", "dataset": "d",
                 "novelty_score": 5, "feasibility_score": 6},
                {"hypothesis": "b", "method": "m", "dataset": "d",
                 "novelty_score": 8, "feasibility_score": 9},
            ]
        }
        result = _validate_idea(raw)
        assert result is not None
        assert result["novelty_score"] == 8
        assert result["feasibility_score"] == 9

    def test_picks_from_single_item_list(self):
        raw = {
            "ideas": [
                {"hypothesis": "a", "method": "m", "dataset": "d",
                 "novelty_score": 6, "feasibility_score": 7},
            ]
        }
        result = _validate_idea(raw)
        assert result is not None
        assert result["novelty_score"] == 6

    def test_fixture_llm_response(self):
        with open(FIXTURES_DIR / "sample_llm_response.json") as f:
            raw = json.load(f)
        result = _validate_idea(raw)
        assert result is not None
        # First idea has higher combined score (6+9=15 vs 7+7=14)
        assert result["novelty_score"] == 6
        assert result["feasibility_score"] == 9


class TestValidateIdeaRejectsOutOfRangeScores:

    def test_rejects_novelty_zero(self):
        idea = {
            "hypothesis": "h", "method": "m", "dataset": "d",
            "novelty_score": 0, "feasibility_score": 5,
        }
        assert _validate_idea(idea) is None

    def test_rejects_novelty_eleven(self):
        idea = {
            "hypothesis": "h", "method": "m", "dataset": "d",
            "novelty_score": 11, "feasibility_score": 5,
        }
        assert _validate_idea(idea) is None

    def test_rejects_feasibility_zero(self):
        idea = {
            "hypothesis": "h", "method": "m", "dataset": "d",
            "novelty_score": 5, "feasibility_score": 0,
        }
        assert _validate_idea(idea) is None

    def test_rejects_feasibility_eleven(self):
        idea = {
            "hypothesis": "h", "method": "m", "dataset": "d",
            "novelty_score": 5, "feasibility_score": 11,
        }
        assert _validate_idea(idea) is None

    def test_rejects_negative_scores(self):
        idea = {
            "hypothesis": "h", "method": "m", "dataset": "d",
            "novelty_score": -1, "feasibility_score": 5,
        }
        assert _validate_idea(idea) is None


class TestSynthesizeIdea:

    @patch("lib.openrouter.httpx.post")
    def test_sends_correct_request(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "hypothesis": "h", "method": "m", "dataset": "d",
                "novelty_score": 7, "feasibility_score": 8,
            })}}]
        }
        mock_post.return_value = mock_response

        from lib.openrouter import synthesize_idea
        result, debug = synthesize_idea(
            title="Test Paper",
            abstract="Test abstract about momentum.",
            model="google/gemini-flash-1.5",
            api_key="test-key",
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test-key"
        assert call_kwargs[1]["headers"]["HTTP-Referer"] == "https://axiom.app"
        assert call_kwargs[1]["headers"]["X-Title"] == "Axiom"
        assert call_kwargs[1]["json"]["model"] == "google/gemini-flash-1.5"
        assert call_kwargs[1]["json"]["temperature"] == 0.7
        assert call_kwargs[1]["json"]["max_tokens"] == 1000
        assert result is not None
        assert result["novelty_score"] == 7

    @patch("lib.openrouter.httpx.post")
    def test_returns_none_on_invalid_json(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "not valid json"}}]
        }
        mock_post.return_value = mock_response

        from lib.openrouter import synthesize_idea
        result, debug = synthesize_idea(
            title="Test", abstract="Test", model="m", api_key="k",
        )
        assert result is None

    @patch("lib.openrouter.httpx.post")
    def test_includes_title_and_abstract_in_prompt(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "hypothesis": "h", "method": "m", "dataset": "d",
                "novelty_score": 7, "feasibility_score": 8,
            })}}]
        }
        mock_post.return_value = mock_response

        from lib.openrouter import synthesize_idea
        synthesize_idea(
            title="My Paper Title",
            abstract="My paper abstract content.",
            model="m",
            api_key="k",
        )

        call_kwargs = mock_post.call_args
        messages = call_kwargs[1]["json"]["messages"]
        user_content = messages[1]["content"]
        assert "My Paper Title" in user_content
        assert "My paper abstract content." in user_content
