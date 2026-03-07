# ElephantPaperSOP

v0.3.0（Introduction-first）

## 这次改动

- 启动本地缓存机制：`cache/pdf` + `cache/text` + `cache/meta/manifest.json`
- 所有内容改为独立 JSON 文件组织，不再把数据塞进 HTML
- 模板库升级为“完整可套用的 Introduction 行文模板”（含段落级全文）
- 每篇论文都有独立详情文件：摘抄句 + 模板映射 + 架构对应

## 数据结构

- `data/intro/index.json`：批次索引
- `data/intro/templates/*.json`：模板家族（完整行文）
- `data/intro/papers/*.json`：论文级详情

## 缓存脚本

1. 下载 PDF 到本地缓存

```bash
python3 scripts/cache_pdfs.py
```

2. 从本地 PDF 抽取 Introduction 文本

```bash
python3 scripts/extract_intro_texts.py
```

## 页面

- `index.html`
  - 左侧：论文列表
  - 中间：论文详情（摘抄句 + why + 映射）
  - 右侧：完整模板全文（可直接套用）
