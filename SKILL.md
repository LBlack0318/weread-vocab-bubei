---
name: weread-vocab-bubei
description: 把微信读书里划线的英文单词/短语整理成不背单词（bbdc.cn）能直接导入的「自制词书」。运行时会弹窗询问微信读书 API Key、弹窗让你选要导哪本书；词表外的词自动联网查词典校验；配置 bbdc cookie 后可以一条命令提交识别并建好词书。当用户说"把微信读书的划线导成单词本/生词本""整理不背单词词书""微信读书生词导入不背单词""导出我的划线单词"时使用。只收单词级与短语级划线，整句自动跳过。
---

# 微信读书划线 → 不背单词自制词书

一条链路：**弹窗要 Key → 取划线 → 弹窗选书 → 抽词 → 词表外的词联网校验 → 出 txt（≥20 词）→ 提交 bbdc.cn 建词书**。

上传默认人工点两下；配好 bbdc cookie 后 `--upload --create` 可以无人值守一路建完（接口细节见 [references/bbdc-import.md](references/bbdc-import.md)）。

零第三方依赖，Python 3.10+ 即可。

## 交互点（三处）

| 时机 | 交互 | 关闭方式 |
|---|---|---|
| 每次运行 | 弹窗询问 API Key（不静默复用） | `WEREAD_API_KEY` 环境变量 / `--use-saved-key` / `--no-prompt` |
| 取到书单后 | 弹窗多选要导哪本书 | `--all`、`--book 关键词`、`--book-id`、`--no-gui` |
| 抽词后 | 词表外的词自动联网查词典（无需人操作） | `--no-verify` |

Key 只存在用户目录，**绝不写进 skill 安装目录**；日志里只出现 `wrk-…abcd` 这种掩码。

## 快速开始

```bash
# 任意目录下执行，把 <skill> 换成本仓库路径
python <skill>/scripts/run.py                 # 交互式：弹 Key → 弹选书 → 出词书
python <skill>/scripts/run.py --verify        # 只验 Key
python <skill>/scripts/run.py --book 书名      # 指定书，不弹选书
python <skill>/scripts/run.py --all --merge    # 所有书合并成一本
```

Windows PowerShell 写法一样，把 `python` 换成你的解释器即可。

一次典型输出：

```
· 有划线的书 5 本，等你选择…          ← 弹窗在这里
· 选中 1 本：《某本书》
《某本书》
  划线 145 条 → 收下 144 条（单词级 143、短语级 1），跳过 1
· 词表外的词 23 个，联网校验中…
  ✗ 词典查不到，丢弃 2 个：de, hmmm
  ✓ 词典确认 21 个
  抽词 144 → 去重 142 → 已导出 0 → 候选 142
  ✓ ~/.weread-vocab/out/wordbook_某本书_2026-11-19.txt（142 词）
  ✓ ~/.weread-vocab/out/review_某本书_2026-11-19.md
```

产物默认落在 `~/.weread-vocab/`：

```
~/.weread-vocab/
├── api_key              # 微信读书 Key（--remember-key 才会存）
├── bbdc_cookies.txt     # 可选，不背单词 cookie，用于自动建词书
├── word_cache.json      # 联网校验缓存
├── data/state.json      # 已导出词、待攒池
└── out/                 # 词书 txt + review.md
```

想换位置用 `--out` / `--data`，或设 `WEREAD_VOCAB_HOME`。都不写进 skill 目录，升级不丢数据。

## 工作流

1. **取数**：微信读书 Agent Gateway `/user/notebooks` 拿有划线的书 → 弹窗选书 → `/book/bookmarklist` 拿 `markText`。见 [references/weread-gateway.md](references/weread-gateway.md)。
2. **清洗**：剥掉多划进来的引号/括号/句读/全角标点/多余空格/零宽字符，拼回跨行断字（`inter-\nesting`），去掉行首编号。
3. **筛粒度**：只收单词级（1 个词）和短语级（2–4 个词、≤50 字符、无句末标点）；整句、含中文、非英文跳过并计数；单词级只剩 1 个字母、或 2 个字母的非词（`de`）当噪声。
4. **抽词**：短语拆成实词（不背单词不支持词组），滤掉停用词与短语内专名。
5. **词形还原**：自带 75,688 词词表 `assets/lexicon.tsv` 校验，`running→run`、`studied→study`、`children→child`；验证不了就保留原形，不造 `snif`/`assembl` 这类残词。细则见 [references/word-rules.md](references/word-rules.md)。
6. **联网校验**：不在词表里的词查 `dictionaryapi.dev`——真词保留（释义进 review）、查不到丢弃、网络失败保留并标记；结果缓存，同词不重复查。
7. **门槛**：不足 `--min-words`（默认 20）不出文件，词进待攒池，下次累加。
8. **增量**：已导出词记在 `state.json`，不重复导出。
9. **产出**：每本书一份 `wordbook_<书名>_YYYY-MM-DD.txt`（一行一词，UTF-8 无 BOM）+ 同名 `review_*.md`。

## 常用参数

| 参数 | 说明 |
|---|---|
| 不给来源参数 | 弹窗选书（默认） |
| `--all` / `--book 关键词` / `--book-id ID` | 指定范围，跳过选书弹窗 |
| `--merge` | 多本合并成一本词书 |
| `--text 文件` 或 `--text -` | 不走 API，读本地文本（每行一条划线） |
| `--since 2026-06-01` | 只要这之后的划线 |
| `--min-words 20` | 词数门槛；低于它只攒不导出 |
| `--max-tokens 4` / `--max-chars 50` | 短语粒度阈值 |
| `--no-verify` | 跳过联网校验 |
| `--upload` | 生成后提交到不背单词，打印平台识别结果 |
| `--create` | 配合 `--upload`：识别通过后直接创建词书 |
| `--book-name` / `--desc` / `--exam` | 词书名（默认用书名）/ 简介 / 分类代码（`KY`=考研，空也行） |
| `--prune-unknown` | 平台识别不了的词剔除后重建 |
| `--no-gui` | 选书改用命令行输入 |
| `--remember-key` / `--use-saved-key` / `--set-key` / `--forget-key` | Key 记忆相关 |
| `--no-lemma` / `--allow-mixed` / `--sort alpha` | 抽词细节 |
| `--dry-run` / `--stats` / `--verify` | 只看不动 |

## 需要知道的坑

- **划线里常是整句**：默认阈值下整句跳过，这是设计。想从整句捞词就调大 `--max-tokens`，但产出的多是常见词。
- **短语不会进词书**：平台不支持词组，只有拆出来的单词会进去，短语原文留在 `review.md`。
- **联网校验磨时间**：词表外的词多时会有几秒等待；查过的词进缓存，第二次很快。断网时自动降级为"未验证，保留"。
- **生僻专名**：平台词库匹配不到的人名/术语（`appreciatively`、`gawker` 这类），`--prune-unknown` 会自动剔除。
- **少于 20 词**：平台直接不生成词书，脚本会攒着。
- **重复跑安全**：已导出词被记住；想重来就删 `~/.weread-vocab/data/state.json`。

## 自检

```bash
python scripts/selftest.py     # 20 个用例，本地 mock gateway + mock 词典，不联网
```

沙箱/只读环境若报写权限错误：`WEREAD_SELFTEST_TMP=<可写目录>`。
