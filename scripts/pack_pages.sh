#!/usr/bin/env bash
set -euo pipefail

mkdir -p public

# 拷贝生成的三件套；缺哪件就跳过，但会打 warning
for f in report.pdf index.html table.csv; do
  if [[ -f "$f" ]]; then
    cp "$f" public/
  else
    echo "::warning::missing $f (continue)"
  fi
done

# 若没有 index.html 但有 PDF，写一个最小跳转页
if [[ ! -f public/index.html && -f public/report.pdf ]]; then
  cat > public/index.html <<'HTML'
<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Report</title>
<p>If you are not redirected, <a href="./report.pdf">open the PDF</a>.</p>
<script>location.href="./report.pdf";</script>
HTML
fi

echo "== public content =="
ls -l public
