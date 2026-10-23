"""Coverage-guided fuzz targets (Atheris) for code that parses mail and files from strangers.

Run one locally on Linux x86_64 with Python 3.11 to 3.13 (Atheris 3.0.0's wheels; elsewhere
uv builds it from source, which needs clang and libFuzzer):
`uv run --group fuzz --python 3.13 python -m fuzz.fuzz_attachment_text -max_total_time=60`.
`.github/workflows/fuzz.yml` runs every target on pull requests and weekly.
"""
