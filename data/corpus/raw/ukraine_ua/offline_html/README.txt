Ukraine.ua 离线 HTML（绕过 Cloudflare）

官网直连返回 403，需用浏览器打开后另存，或使用本目录：

  slug.zh.html  — 中文页完整 HTML
  slug.uk.html  — 乌克兰语页完整 HTML

然后运行：
  set UKRAINE_UA_FETCH_MODE=offline
  venv\Scripts\python.exe tools\run_corpus_pipeline.py --source ukraine_ua --max-pages 50

文件名 slug = URL 路径，如 explore_ukrainian-cuisine.zh.html
