"""Tests for the CLI interface."""

import json
from unittest.mock import MagicMock, patch

import pytest

from memescript.cli import main


class TestCLI:
    def test_missing_script_file(self):
        exit_code = main(["nonexistent_file.txt"])
        assert exit_code == 1

    def test_empty_script_file(self, tmp_path):
        script_file = tmp_path / "empty.txt"
        script_file.write_text("")

        exit_code = main([str(script_file)])
        assert exit_code == 1

    @patch("memescript.cli.run_suggestions_only")
    def test_full_run_no_render(self, mock_run, tmp_path):
        from memescript.models import PipelineConfig, PipelineResult

        script_file = tmp_path / "script.txt"
        script_file.write_text("Test line 1\nTest line 2")

        mock_run.return_value = PipelineResult(
            script_lines=[], moments=[], suggestions=[],
            critiques=[], outputs=[], config=PipelineConfig(),
        )

        exit_code = main([str(script_file), "--no-render"])
        assert exit_code == 0

    @patch("memescript.cli.run_pipeline")
    def test_full_run_with_render(self, mock_run, tmp_path):
        from memescript.models import PipelineConfig, PipelineResult

        script_file = tmp_path / "script.txt"
        script_file.write_text("Test line 1\nTest line 2")

        mock_run.return_value = PipelineResult(
            script_lines=[], moments=[], suggestions=[],
            critiques=[], outputs=[], config=PipelineConfig(),
        )

        exit_code = main([str(script_file), "--no-critic"])
        assert exit_code == 0

    @patch("memescript.cli.run_analysis_only")
    def test_analyze_only(self, mock_analyze, tmp_path):
        from memescript.models import PipelineConfig, PipelineResult

        script_file = tmp_path / "script.txt"
        script_file.write_text("Test content")

        mock_analyze.return_value = PipelineResult(
            script_lines=[], moments=[], suggestions=[],
            critiques=[], outputs=[], config=PipelineConfig(),
        )

        exit_code = main([str(script_file), "--analyze-only"])
        assert exit_code == 0

    @patch("memescript.cli.run_suggestions_only")
    def test_manifest_output(self, mock_run, tmp_path):
        from memescript.models import PipelineConfig, PipelineResult

        script_file = tmp_path / "script.txt"
        script_file.write_text("Test line")
        manifest_file = tmp_path / "manifest.json"

        mock_run.return_value = PipelineResult(
            script_lines=[], moments=[], suggestions=[],
            critiques=[], outputs=[], config=PipelineConfig(),
        )

        exit_code = main([
            str(script_file),
            "--no-render",
            "--manifest", str(manifest_file),
        ])
        assert exit_code == 0
        assert manifest_file.exists()

    @patch("memescript.cli.run_pipeline")
    def test_density_option(self, mock_run, tmp_path):
        from memescript.models import PipelineConfig, PipelineResult

        script_file = tmp_path / "script.txt"
        script_file.write_text("Test")

        mock_run.return_value = PipelineResult(
            script_lines=[], moments=[], suggestions=[],
            critiques=[], outputs=[], config=PipelineConfig(),
        )

        # Not using --no-render, so it calls run_pipeline
        exit_code = main([str(script_file), "-d", "fireship", "--no-critic"])
        assert exit_code == 0
        call_args = mock_run.call_args
        # run_pipeline(script, config, meme_db)
        assert call_args[0][1].density.value == "fireship"

    @patch("memescript.cli.run_pipeline")
    def test_pipeline_error_handling(self, mock_run, tmp_path):
        script_file = tmp_path / "script.txt"
        script_file.write_text("Test")

        mock_run.side_effect = RuntimeError("API Error")

        # Without --no-render, it calls run_pipeline
        exit_code = main([str(script_file)])
        assert exit_code == 1
