# ElephantPaperSOP

v1.0.0（JSON-first, per-paper immutable records）

## 当前版本

- 每篇论文一个独立 JSON：历史结果不会被后续批次覆盖
- 每个模板一个独立 JSON：支持模板增量替换与扩展
- `content.fulltext` 以 `gzip+base64` 写入论文 JSON，兼顾后续分析与文件体积
- `content.sections` 预留 `introduction/related_work/method/experiments/conclusion`
- 页面按需加载单篇论文 JSON，不再依赖批量文件聚合

## 目录结构

- `data/v1/index.json`：全局入口（schema/version/论文清单/路径）
- `data/v1/papers/*.json`：论文级详情（元信息 + 全文 + 各章节分析状态）
- `data/v1/templates/intro/*.json`：Introduction 模板库
- `scripts/migrate_intro_to_v1.py`：从旧结构迁移到 v1

## 本地处理脚本

```bash
python3 scripts/migrate_intro_to_v1.py
```

说明：
- 默认读取 `data/intro/index.json` 的论文列表
- 若 `pdf` 为 `local:///...` 且文件存在，会抽取全文并压缩写入 `data/v1/papers/*.json`
- 若章节切分失败，会回退到 `intro_highlights` 作为 Introduction 文本兜底

## 页面

- `index.html`
  - 左侧：论文列表（搜索 / 模板 / 状态过滤）
  - 中间：论文详情（摘抄句 / 模板映射 / 章节状态 / 全文压缩统计）
  - 右侧：模板全文（完整 Introduction 段落模板 + 句式库）
