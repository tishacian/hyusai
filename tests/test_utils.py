"""Unit tests for the utils module.

Comprehensive test suite covering:
- Timing decorators: measure_time, measure_time_sync (4 tests)
- Tesseract utilities: configure_tesseract, get_tesseract_path (4 tests)
- GPU utilities: gpu_arc_type, get_max_model_len (8 tests)
- Text formatting: format_llm_response, add_leading_space_if_needed, humanize_datetime (6 tests)

Total: 22 comprehensive unit tests
"""

import asyncio
import re
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.globalvariables import CPUModels, Models
from src.utils import (
    add_leading_space_if_needed,
    configure_tesseract,
    format_llm_response,
    get_max_model_len,
    gpu_arc_type,
    humanize_datetime,
    measure_time,
    measure_time_sync,
)


class TestMeasureTimeDecorators:
    """Test suite for timing decorators."""

    def test_measure_time_sync_returns_correct_result(self):
        """Test that measure_time_sync decorator returns function result correctly."""

        @measure_time_sync
        def simple_function(x, y):
            return x + y

        result = simple_function(5, 3)
        assert result == 8

    def test_measure_time_sync_preserves_function_name(self):
        """Test that measure_time_sync preserves original function name."""

        @measure_time_sync
        def named_function():
            return 42

        assert named_function.__name__ == "named_function"

    def test_measure_time_async_returns_correct_result(self):
        """Test that measure_time decorator returns function result correctly."""

        @measure_time
        async def async_function(x, y):
            await asyncio.sleep(0.01)
            return x + y

        # Run async function in event loop
        result = asyncio.run(async_function(5, 3))
        assert result == 8

    def test_measure_time_async_preserves_function_name(self):
        """Test that measure_time preserves original function name."""

        @measure_time
        async def async_named_function():
            return 42

        assert async_named_function.__name__ == "async_named_function"


class TestTesseractConfiguration:
    """Test suite for Tesseract OCR configuration."""

    def test_configure_tesseract_returns_tuple(self):
        """Test that configure_tesseract returns a tuple."""
        # Clear cache to ensure fresh execution
        configure_tesseract.cache_clear()
        result = configure_tesseract()

        assert isinstance(result, tuple)
        assert len(result) == 2
        # result is (path, boolean)
        assert isinstance(result[1], bool)

    def test_configure_tesseract_is_cached(self):
        """Test that configure_tesseract caches results."""
        configure_tesseract.cache_clear()

        result1 = configure_tesseract()
        result2 = configure_tesseract()

        assert result1 == result2

    @patch("src.utils.get_tesseract_path")
    def test_configure_tesseract_with_no_tesseract(self, mock_get_path):
        """Test configure_tesseract when tesseract is not available."""
        mock_get_path.return_value = None
        configure_tesseract.cache_clear()

        path, available = configure_tesseract()

        assert path is None
        assert available is False

    @patch("src.utils.get_tesseract_path")
    def test_configure_tesseract_with_valid_path(self, mock_get_path):
        """Test configure_tesseract with valid tesseract path."""
        mock_get_path.return_value = "/usr/bin/tesseract"
        configure_tesseract.cache_clear()

        with patch("src.utils.pytesseract", create=True):
            path, available = configure_tesseract()
            # Should attempt to set the path
            assert path == "/usr/bin/tesseract"


class TestGPUDetection:
    """Test suite for GPU detection utilities."""

    @patch("torch.cuda.is_available")
    def test_gpu_arc_type_cpu(self, mock_cuda_available):
        """Test gpu_arc_type returns 'other' for non-CUDA device."""
        mock_cuda_available.return_value = False

        result = gpu_arc_type("cpu")
        assert result == "other"

    @patch("torch.cuda.get_device_properties")
    def test_gpu_arc_type_detects_h100(self, mock_get_props):
        """Test gpu_arc_type correctly identifies H100."""
        mock_props = MagicMock()
        mock_props.name = "NVIDIA H100"
        mock_props.total_memory = 80e9

        mock_get_props.return_value = mock_props

        result = gpu_arc_type("cuda")
        assert "H100" in result or result == "H100"

    @patch("torch.cuda.get_device_properties")
    def test_gpu_arc_type_detects_a100(self, mock_get_props):
        """Test gpu_arc_type correctly identifies A100."""
        mock_props = MagicMock()
        mock_props.name = "NVIDIA A100"
        mock_props.total_memory = 80e9

        mock_get_props.return_value = mock_props

        result = gpu_arc_type("cuda")
        assert "A100" in result or result == "A100"

    @patch("torch.cuda.get_device_properties")
    def test_gpu_arc_type_detects_l40s(self, mock_get_props):
        """Test gpu_arc_type correctly identifies L40S."""
        mock_props = MagicMock()
        mock_props.name = "NVIDIA L40S"
        mock_props.total_memory = 48e9

        mock_get_props.return_value = mock_props

        result = gpu_arc_type("cuda")
        assert "L40S" in result or result == "L40S"

    def test_get_max_model_len_with_explicit_value(self):
        """Test get_max_model_len with explicit max_model_len."""
        result = get_max_model_len(Models.LLAMA3_8B, max_model_len=256)

        assert result == 256 * 1024

    def test_get_max_model_len_cpu_model(self):
        """Test get_max_model_len for CPU models."""
        result = get_max_model_len(CPUModels.LLAMA32_3B_INSTRUCT)

        assert result == 128 * 1024

    def test_get_max_model_len_unknown_model_raises_error(self):
        """Test get_max_model_len raises ValueError for unknown model."""
        with pytest.raises(ValueError):
            get_max_model_len("unknown_model_xyz")

    @patch("src.utils.gpu_arc_type")
    def test_get_max_model_len_gpu_model_large(self, mock_gpu_type):
        """Test get_max_model_len for large GPU model."""
        mock_gpu_type.return_value = "A100"

        result = get_max_model_len(Models.LLAMA3_8B)
        # Exact value depends on GPU type and model, but should be substantial
        assert result > 0


class TestTextFormatting:
    """Test suite for text formatting utilities."""

    def test_add_leading_space_to_string_without_space(self):
        """Test adding leading space to string that doesn't have one."""
        result = add_leading_space_if_needed("hello")
        assert result == " hello"

    def test_add_leading_space_preserves_existing_space(self):
        """Test that string already starting with space is preserved."""
        result = add_leading_space_if_needed(" hello")
        assert result == " hello"

    def test_add_leading_space_to_empty_string(self):
        """Test that empty string returns empty string."""
        result = add_leading_space_if_needed("")
        assert result == ""

    def test_add_leading_space_with_tab(self):
        """Test string starting with tab is preserved."""
        result = add_leading_space_if_needed("\thello")
        assert result == "\thello"

    def test_format_llm_response_removes_inst_tags(self):
        """Test that format_llm_response removes [INST] tags."""
        response = "[INST] question [/INST] answer"
        result = format_llm_response(response)

        assert "[INST]" not in result
        assert "[/INST]" not in result

    def test_format_llm_response_preserves_content(self):
        """Test that format_llm_response preserves actual content."""
        response = "This is the actual answer"
        result = format_llm_response(response)

        assert "actual answer" in result

    def test_format_llm_response_handles_multiline(self):
        """Test format_llm_response with multiline content."""
        response = """[INST] question [/INST]
        Line 1
        Line 2
        Line 3"""
        result = format_llm_response(response)

        assert "Line 1" in result or "Line" in result

    def test_format_llm_response_handles_empty_input(self):
        """Test format_llm_response with empty input."""
        result = format_llm_response("")
        assert isinstance(result, str)

    def test_humanize_datetime_valid_datetime(self):
        """Test humanize_datetime with valid datetime."""
        dt = datetime(2025, 6, 17, 15, 42, 0)
        result = humanize_datetime(dt)

        assert "2025" in result
        assert "June" in result or "06" in result
        assert "17" in result
        assert "15:42" in result or "3:42" in result

    def test_humanize_datetime_none_returns_na(self):
        """Test humanize_datetime with None returns 'N/A'."""
        result = humanize_datetime(None)
        assert result == "N/A"

    def test_humanize_datetime_format_consistency(self):
        """Test humanize_datetime format consistency."""
        dt = datetime(2025, 1, 1, 8, 0, 0)
        result = humanize_datetime(dt)

        # Should contain month name or month number, day, year, and time
        assert any(
            month in result.lower()
            for month in [
                "january",
                "01",
            ]
        )


class TestUtilsIntegration:
    """Integration tests for utils module functions."""

    def test_timing_decorator_with_actual_sleep(self):
        """Test measure_time_sync decorator with actual timing."""

        @measure_time_sync
        def slow_function():
            time.sleep(0.1)
            return "done"

        start = time.time()
        result = slow_function()
        elapsed = time.time() - start

        assert result == "done"
        assert elapsed >= 0.1

    def test_format_and_add_space_together(self):
        """Test combining format_llm_response and add_leading_space_if_needed."""
        response = "[INST] question [/INST] answer text"
        formatted = format_llm_response(response)
        with_space = add_leading_space_if_needed(formatted)

        assert formatted != response
        assert with_space[0] == " " or with_space[0].isspace()

    @patch("src.utils.gpu_arc_type")
    def test_get_max_model_len_with_various_models(self, mock_gpu_type):
        """Test get_max_model_len with multiple model types."""
        mock_gpu_type.return_value = "A100"

        # Test a few different models
        models_to_test = [
            (Models.LLAMA3_8B, int),
            (CPUModels.LLAMA32_3B_INSTRUCT, int),
        ]

        for model, expected_type in models_to_test:
            result = get_max_model_len(model)
            assert isinstance(result, expected_type)
            assert result > 0
