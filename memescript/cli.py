"""Command-line interface for MemeScript."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .models import MemeDensity, PipelineConfig
from .meme_db import MemeDatabase, get_default_database
from .pipeline import run_pipeline, run_analysis_only, run_suggestions_only
from .preview import run_preview


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="memescript",
        description="Automated meme generation from video scripts.",
    )
    parser.add_argument(
        "script",
        help="Path to the script file, or '-' to read from stdin.",
    )
    parser.add_argument(
        "-d", "--density",
        choices=["sparse", "moderate", "fireship"],
        default="moderate",
        help="Meme density (default: moderate).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="output",
        help="Output directory for rendered memes (default: output/).",
    )
    parser.add_argument(
        "-t", "--template-dir",
        default="meme_templates",
        help="Directory containing meme template images (default: meme_templates/).",
    )
    parser.add_argument(
        "--registry",
        default=None,
        help="Path to meme template registry JSON file.",
    )
    parser.add_argument(
        "-m", "--model",
        default="claude-sonnet-4-20250514",
        help="Anthropic model to use.",
    )
    parser.add_argument(
        "--max-suggestions",
        type=int,
        default=3,
        help="Max meme suggestions per moment (default: 3).",
    )
    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=3.0,
        help="Minimum quality score to keep a meme (default: 3.0).",
    )
    parser.add_argument(
        "--no-critic",
        action="store_true",
        help="Skip the quality critique stage.",
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Skip image rendering — output suggestions only.",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Only identify meme-worthy moments, no selection.",
    )
    parser.add_argument(
        "--audience",
        default=None,
        help="Audience description for prompt tuning.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Launch interactive preview mode after rendering. "
             "Use hotkeys (T=toggle terrain, ?=help) instead of CLI flags.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to save the output manifest JSON.",
    )

    args = parser.parse_args(argv)

    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Read script
    if args.script == "-":
        script_text = sys.stdin.read()
    else:
        script_path = Path(args.script)
        if not script_path.exists():
            print(f"Error: Script file not found: {script_path}", file=sys.stderr)
            return 1
        script_text = script_path.read_text()

    if not script_text.strip():
        print("Error: Script is empty.", file=sys.stderr)
        return 1

    # Build config
    config = PipelineConfig(
        density=MemeDensity(args.density),
        max_suggestions_per_moment=args.max_suggestions,
        quality_threshold=args.quality_threshold,
        enable_critic=not args.no_critic,
        enable_compositing=not args.no_render,
        template_dir=args.template_dir,
        output_dir=args.output_dir,
        model=args.model,
    )
    if args.audience:
        config.audience = args.audience

    # Load meme database
    if args.registry:
        meme_db = MemeDatabase.load_from_file(args.registry)
    else:
        meme_db = get_default_database()

    # Run pipeline
    try:
        if args.analyze_only:
            result = run_analysis_only(script_text, config)
        elif args.no_render:
            result = run_suggestions_only(script_text, config, meme_db)
        else:
            result = run_pipeline(script_text, config, meme_db)
    except Exception as e:
        print(f"Error during pipeline execution: {e}", file=sys.stderr)
        logging.exception("Pipeline failed")
        return 1

    # Output results
    manifest = result.to_manifest()
    manifest_json = json.dumps(manifest, indent=2, default=str)

    if args.manifest:
        result.save_manifest(args.manifest)
        print(f"Manifest saved to: {args.manifest}")
    else:
        print(manifest_json)

    # Summary
    print(f"\n--- MemeScript Summary ---", file=sys.stderr)
    print(f"Moments detected: {len(result.moments)}", file=sys.stderr)
    print(f"Suggestions generated: {len(result.suggestions)}", file=sys.stderr)
    print(f"Memes output: {len(result.outputs)}", file=sys.stderr)
    if result.outputs and config.enable_compositing:
        print(f"Output directory: {config.output_dir}", file=sys.stderr)

    # Launch interactive preview if requested
    if args.preview and result.outputs:
        run_preview(result, config, meme_db)

    return 0


if __name__ == "__main__":
    sys.exit(main())
