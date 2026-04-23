"""Convert Experiment/presentation_points.md to .html + .pdf via
Python-Markdown + WeasyPrint CLI (same tool chain as _build_review_pdf.py).
"""
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
MD = HERE / "presentation_points.md"
HTML = HERE / "presentation_points.html"
PDF = HERE / "presentation_points.pdf"

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: "DejaVu Sans", "Segoe UI", Arial, sans-serif; font-size: 10pt; line-height: 1.4; color: #111; }
h1 { font-size: 18pt; color: #1f4e79; margin-top: 0; border-bottom: 2px solid #1f4e79; padding-bottom: 4pt; }
h2 { font-size: 13pt; color: #1f4e79; margin-top: 14pt; border-bottom: 1px solid #ccd; padding-bottom: 2pt; }
h3 { font-size: 11pt; color: #2a577a; margin-top: 10pt; }
p  { margin: 4pt 0; text-align: justify; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 6pt 0; }
th, td { border: 1px solid #bbb; padding: 3pt 5pt; text-align: left; }
th { background: #e8eef5; }
code { font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 9pt; background: #f4f4f4; padding: 1pt 3pt; border-radius: 2pt; }
pre { font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 8.5pt; background: #f4f4f4; padding: 6pt 8pt; border-left: 3px solid #1f4e79; white-space: pre-wrap; word-wrap: break-word; }
blockquote { border-left: 3px solid #aaa; margin: 6pt 0; padding-left: 8pt; color: #444; }
hr { border: none; border-top: 1px solid #bbb; margin: 10pt 0; }
strong { color: #1f4e79; }
ul, ol { margin: 4pt 0; padding-left: 18pt; }
li { margin: 1pt 0; }
"""

md_text = MD.read_text(encoding="utf-8")
body = markdown.markdown(
    md_text,
    extensions=["tables", "fenced_code", "extra", "sane_lists"],
    output_format="html5",
)

html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Presentation Points — ASGARD-XV Exp 14 Data Analysis</title>
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""
HTML.write_text(html_doc, encoding="utf-8")
print(f"Wrote {HTML}")

weasyprint = shutil.which("weasyprint") or str(Path.home() / ".local/bin/weasyprint")
result = subprocess.run(
    [weasyprint, str(HTML), str(PDF)],
    capture_output=True, text=True,
)
if result.returncode != 0:
    print("weasyprint stderr:", result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
print(f"Wrote {PDF}")
