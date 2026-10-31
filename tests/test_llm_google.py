"""
Author: Antigravity
Created: 2026-10-31
Scope: Unit tests for Google DeepMind Gemini API client and model registry (Slice 1).
"""

from unittest.mock import MagicMock, patch
import pytest


class TestConfigModelsGoogleShould:
    """Verifies the integrity and schema of the Google DeepMind model registry."""

    def test_given_google_models_registry_when_inspected_then_contains_required_models(self) -> None:
        """
        Scenario: Model registry discovery
        Slice: slice-1-gemini-api-client-and-registry
        Given the Google models configuration module
        When GOOGLE_MODELS is loaded
        Then it contains Gemini 4 Argon, 2.5 Flash, 2.5 Pro, and 3.8 Flash
        """
        ### Given
        from config_models_google import GOOGLE_MODELS

        ### When
        expected_models = [
            "google-gemini-4-argon",
            "google-gemini-2.5-flash",
            "google-gemini-2.5-pro",
            "google-gemini-3.8-flash",
        ]

        ### Then
        for model_key in expected_models:
            assert model_key in GOOGLE_MODELS, f"Expected {model_key} in GOOGLE_MODELS"

    def test_given_thinking_level_sweep_when_inspected_then_nine_variants_present(self) -> None:
        """
        Scenario: Thinking-level sweep registry coverage
        Slice: slice-1-gemini-api-client-and-registry
        Given the Google models configuration module
        When GOOGLE_MODELS is inspected for sweep entries
        Then all 9 thinking-level variants (3 models × 3 levels) are present with correct thinking_level values
        """
        ### Given
        from config_models_google import GOOGLE_MODELS

        ### When
        sweep_keys = [
            ("google-gemini-4-argon-think-low", "low"),
            ("google-gemini-4-argon-think-medium", "medium"),
            ("google-gemini-4-argon-think-high", "high"),
            ("google-gemini-3.1-pro-think-low", "low"),
            ("google-gemini-3.1-pro-think-medium", "medium"),
            ("google-gemini-3.1-pro-think-high", "high"),
            ("google-gemini-3.8-flash-think-low", "low"),
            ("google-gemini-3.8-flash-think-medium", "medium"),
            ("google-gemini-3.8-flash-think-high", "high"),
        ]

        ### Then
        for key, expected_level in sweep_keys:
            assert key in GOOGLE_MODELS, f"Expected sweep key {key} in GOOGLE_MODELS"
            assert GOOGLE_MODELS[key]["thinking_level"] == expected_level, (
                f"{key}: expected thinking_level={expected_level!r}, "
                f"got {GOOGLE_MODELS[key]['thinking_level']!r}"
            )

    def test_given_baseline_entries_when_inspected_then_thinking_level_is_none(self) -> None:
        """
        Scenario: Baseline entries have no thinking config
        Slice: slice-1-gemini-api-client-and-registry
        Given the three active baseline entries (no sweep suffix)
        When thinking_level is read
        Then it is None for all of them (API default)
        """
        ### Given
        from config_models_google import GOOGLE_MODELS

        ### When
        baseline_keys = [
            "google-gemini-4-argon",
            "google-gemini-3.1-pro",
            "google-gemini-3.8-flash",
        ]

        ### Then
        for key in baseline_keys:
            assert GOOGLE_MODELS[key]["thinking_level"] is None, (
                f"{key}: expected thinking_level=None, got {GOOGLE_MODELS[key]['thinking_level']!r}"
            )

    def test_given_model_entries_when_validated_then_each_has_required_metadata_keys(self) -> None:
        """
        Scenario: Model metadata validation
        Slice: slice-1-gemini-api-client-and-registry
        Given all entries in GOOGLE_MODELS
        When inspecting each model configuration
        Then each has required keys: model, tier, ctx, price_in, price_out, multimodal, modalities
        """
        ### Given
        from config_models_google import GOOGLE_MODELS
        required_keys = {"model", "tier", "ctx", "price_in", "price_out", "multimodal", "modalities"}

        ### When / Then
        for short_name, cfg in GOOGLE_MODELS.items():
            missing = required_keys - set(cfg.keys())
            assert not missing, f"Model {short_name} is missing keys: {missing}"
            assert isinstance(cfg["ctx"], int) and cfg["ctx"] > 0, f"{short_name} ctx must be positive int"
            assert isinstance(cfg["modalities"], list) and len(cfg["modalities"]) > 0


class TestLlmGoogleShould:
    """Verifies the behavior, context truncation, rate limiting, and output extraction of llm_google."""

    def test_given_extracted_text_exceeding_max_ctx_when_calling_llm_then_truncates_text(self) -> None:
        """
        Scenario: Context limit bounding
        Slice: slice-1-gemini-api-client-and-registry
        Given extracted text larger than the model context limit
        When call_llm is invoked with max_ctx_tokens
        Then the prompt is safely truncated before calling the API
        """
        ### Given
        import llm_google

        prompt_template = "Extract JSON: "
        huge_text = "A" * 50_000
        max_ctx = 3000

        mock_choice = MagicMock()
        mock_choice.message.content = '{"charity_number": "123456"}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 20

        ### When
        with patch.object(llm_google, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = llm_google.call_llm(
                model_name="google-gemini-2.5-flash",
                prompt_template=prompt_template,
                extracted_text=huge_text,
                max_ctx_tokens=max_ctx,
            )

            call_args = mock_client.chat.completions.create.call_args
            sent_messages = call_args.kwargs["messages"]
            user_content = sent_messages[1]["content"]

            ### Then
            # Max text chars = (3000 - 2000) * 4 - len(prompt_template) = 4000 - len(prompt_template)
            assert len(user_content) < len(prompt_template) + len(huge_text)
            assert result["prompt_tokens"] == 100
            assert result["completion_tokens"] == 20
            assert "123456" in result["text"]

    def test_given_api_response_with_markdown_backticks_when_called_then_extracts_clean_json(self) -> None:
        """
        Scenario: Markdown code block stripping
        Slice: slice-1-gemini-api-client-and-registry
        Given the model wraps its JSON in markdown backticks
        When call_llm receives the response
        Then it extracts the raw JSON text from inside the code block
        """
        ### Given
        import llm_google

        raw_output = "Here is the extracted information:\n```json\n{\n  \"charity_number\": \"1132766\"\n}\n```\nHope that helps!"
        mock_choice = MagicMock()
        mock_choice.message.content = raw_output
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 150
        mock_response.usage.completion_tokens = 30

        ### When
        with patch.object(llm_google, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = llm_google.call_llm(
                model_name="google-gemini-4-argon",
                prompt_template="Extract: ",
                extracted_text="Charity 1132766 details",
            )

            ### Then
            assert result["text"].strip().startswith("{")
            assert result["text"].strip().endswith("}")
            assert '"charity_number": "1132766"' in result["text"]

    def test_given_rate_limit_429_error_when_calling_llm_then_retries_with_exponential_backoff(self) -> None:
        """
        Scenario: 429 Rate limiting backoff
        Slice: slice-1-gemini-api-client-and-registry
        Given the Gemini API returns a 429 rate limit error on first attempt
        When call_llm runs
        Then it catches the 429, sleeps with backoff, and succeeds on the subsequent attempt
        """
        ### Given
        import llm_google

        mock_choice = MagicMock()
        mock_choice.message.content = '{"charity_number": "999"}'
        mock_success = MagicMock()
        mock_success.choices = [mock_choice]
        mock_success.usage.prompt_tokens = 50
        mock_success.usage.completion_tokens = 10

        ### When
        with patch.object(llm_google, "_get_client") as mock_get_client, \
             patch("time.sleep") as mock_sleep:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = [
                Exception("Error code: 429 - ResourceExhausted: Rate limit reached"),
                mock_success,
            ]
            mock_get_client.return_value = mock_client

            result = llm_google.call_llm(
                model_name="google-gemini-4-argon",
                prompt_template="Extract: ",
                extracted_text="Some text",
            )

            ### Then
            assert mock_client.chat.completions.create.call_count == 2
            mock_sleep.assert_called_once()
            # Initial attempt wait is 10s (2^0 * 10)
            assert mock_sleep.call_args[0][0] == 10
            assert "999" in result["text"]

    def test_given_missing_api_key_when_calling_llm_then_raises_runtime_error(self) -> None:
        """
        Scenario: Missing API key validation
        Slice: slice-1-gemini-api-client-and-registry
        Given neither GEMINI_API_KEY nor GOOGLE_API_KEY is present
        When _get_api_key is called
        Then it raises a clear ValueError instructing how to set it
        """
        ### Given
        import llm_google

        ### When / Then
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="GEMINI_API_KEY or GOOGLE_API_KEY must be set"):
                llm_google._get_api_key()

    def test_given_various_model_names_when_resolving_then_returns_correct_api_ids(self) -> None:
        """
        Scenario: Model name mapping resolution
        Slice: slice-1-gemini-api-client-and-registry
        Given registry names, custom google- prefixes, or direct API names
        When _resolve_api_model is called
        Then it resolves to the underlying Gemini API identifier
        """
        ### Given
        import llm_google

        ### When / Then
        assert llm_google._resolve_api_model("google-gemini-4-argon") == "gemini-4-argon"
        assert llm_google._resolve_api_model("google-experimental-model") == "experimental-model"
        assert llm_google._resolve_api_model("gemini-2.5-pro") == "gemini-2.5-pro"

    def test_given_valid_api_key_when_creating_client_then_returns_openai_instance(self) -> None:
        """
        Scenario: OpenAI client creation
        Slice: slice-1-gemini-api-client-and-registry
        Given GEMINI_API_KEY in environment
        When _get_client is called
        Then it configures base_url to Google endpoint and sets api_key
        """
        ### Given
        import llm_google

        ### When
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-123"}):
            client = llm_google._get_client()

            ### Then
            assert client.api_key == "test-key-123"
            assert str(client.base_url).startswith("https://generativelanguage.googleapis.com")

    def test_given_repeated_failures_when_calling_llm_then_raises_runtime_error(self) -> None:
        """
        Scenario: Exhausted retries
        Slice: slice-1-gemini-api-client-and-registry
        Given an API that repeatedly fails with non-retryable errors
        When call_llm runs
        Then it raises after exceeding retries
        """
        ### Given
        import llm_google

        ### When / Then
        with patch.object(llm_google, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = RuntimeError("Fatal API crash")
            mock_get_client.return_value = mock_client

            with pytest.raises(RuntimeError, match="Fatal API crash"):
                llm_google.call_llm("google-gemini-4-argon", "template", "text")

    def test_given_thinking_level_sweep_model_when_called_then_reasoning_effort_is_passed(self) -> None:
        """
        Scenario: thinking_level forwarded as reasoning_effort
        Slice: slice-1-gemini-api-client-and-registry
        Given a sweep entry with thinking_level='low'
        When call_llm is called
        Then reasoning_effort='low' is passed directly to chat.completions.create
        """
        ### Given
        import llm_google

        mock_choice = MagicMock()
        mock_choice.message.content = '{"charity_number": "123"}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 10

        ### When
        with patch.object(llm_google, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            llm_google.call_llm(
                model_name="google-gemini-3.8-flash-think-low",
                prompt_template="Extract: ",
                extracted_text="Some text",
            )

            call_kwargs = mock_client.chat.completions.create.call_args.kwargs

        ### Then
        assert "reasoning_effort" in call_kwargs, "reasoning_effort must be passed for thinking-level models"
        assert call_kwargs["reasoning_effort"] == "low"
        assert "extra_body" not in call_kwargs, "extra_body must NOT be used for reasoning_effort models"

    def test_given_baseline_model_when_called_then_extra_body_is_absent(self) -> None:
        """
        Scenario: No extra_body for baseline (thinking_level=None)
        Slice: slice-1-gemini-api-client-and-registry
        Given a baseline entry with thinking_level=None
        When call_llm is called
        Then extra_body is NOT passed to chat.completions.create
        """
        ### Given
        import llm_google

        mock_choice = MagicMock()
        mock_choice.message.content = '{"charity_number": "456"}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 10

        ### When
        with patch.object(llm_google, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            llm_google.call_llm(
                model_name="google-gemini-3.8-flash",
                prompt_template="Extract: ",
                extracted_text="Some text",
            )

            call_kwargs = mock_client.chat.completions.create.call_args.kwargs

        ### Then
        assert "extra_body" not in call_kwargs, (
            "extra_body must NOT be passed for baseline models with thinking_level=None"
        )
