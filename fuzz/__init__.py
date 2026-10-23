"""Coverage-guided fuzz targets (Atheris) for code that parses mail and files from strangers.

Run one locally: `uv run --group fuzz python fuzz/fuzz_attachment_text.py -max_total_time=60`.
`.github/workflows/fuzz.yml` runs every target on pull requests and weekly.
"""
