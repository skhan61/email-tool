"""Coverage-guided fuzz targets (Atheris) for code that parses mail and files from strangers.

Run one locally on Linux x86_64 with Python 3.12 to 3.14 (Atheris 3.1.0 ships wheels only there,
and no source package to build elsewhere):
`uv run --group fuzz --python 3.13 python -m fuzz.fuzz_attachment_text -max_total_time=60`.
`.github/workflows/fuzz.yml` runs every target on pull requests and weekly.
"""
