# 抽词规则

目标：把"划线"变成"词书里的词"，只保留值得单独背的英文词。

## 0. 先清洗（`extract.clean`）

手指划过界、跨行断字、输入法标点，都会跟着 `markText` 进来。判定粒度和抽词**之前**先清掉：

| 噪声 | 处理 | 例 |
|---|---|---|
| 两端引号、括号、句读、破折号、省略号 | 循环剥掉 | `"resilience"` / `(resilience)` / `resilience.` → `resilience` |
| 中文标点（全角） | 替换成空格，**不当"含中文"信号** | `resilience，` → `resilience` |
| 多余空格、不间断空格、零宽字符 | 折叠/删除 | `  resili\u00a0ence  ` → `resilience` |
| 跨行断字 | 把 `-` + 换行 拼回去 | `inter-\nesting` → `interesting` |
| 行首编号/项目符号 | 正则剥掉 | `1. resilience` / `• resilience` → `resilience` |
| 多划进来的孤立字母 | 单词级只剩 1 个字母 → `skip:noise` | `a`、`e。` 被丢掉 |

注意：清掉句末标点之后，短句（如 `Go home.`）可能落进短语级——这是有意的，它本来就是短语形态。

## 1. 粒度判定（`extract.classify`）

一条划线按顺序过下面几关，第一关命中就定类：

| 顺序 | 条件 | 结论 |
|---|---|---|
| 1 | 清洗后为空 | `skip:empty` |
| 2 | 含中日韩文字或全角标点 | `skip:cjk`（`--allow-mixed` 时改为抠出英文部分） |
| 3 | 提不出英文 token，或字母占比 < 0.75 | `skip:non_english` |
| 4 | 字符数 > `--max-chars`(50) 或 token 数 > `--max-tokens`(4) | `skip:sentence` |
| 5 | 含 `. ! ? ; :` | `skip:sentence` |
| 6 | 含 `,` 且 ≥3 个 token | `skip:sentence` |
| 7 | 1 个 token | `word` |
| 8 | 其余 | `phrase` |

阈值放宽就更容易收长短语：`--max-tokens 6 --max-chars 80`。

## 2. 收词

- **单词级**：用户明确划出来的，即使是 `however` 这种词也保留（这是他的选择）。
  - 例外：只剩 1 个字母，或 2 个字母但不在 `TWO_LETTER_OK` 白名单（`go`/`up`/`me` 等）里 → 判为划歪的碎片，`skip:noise`。这条专门挡 `de`、`a` 这类噪声。
- **短语级**：拆成实词——
  - 去掉 `assets/stopwords.txt` 里的功能词（冠词、介词、代词、助动词、连词、程度副词等约 190 个）；
  - 去掉短语内部首字母大写且非全大写的 token（判为专名）；
  - 去掉长度 < 2 的 token；
  - 拆完一个实词都不剩 → 整条跳过，计入"短语里没有实词"。

  例：`in the long run` → `long, run`；`take off` → `take`；`the bigger picture` → `bigger, picture`。

## 3. 词形还原（`extract.lemmatize`）

原则：**有词表验证才还原，验证不了就保留原形**。错还原会造出词库里根本不存在的词（`sniffing→snif`、`assembling→assembl`），比不还原更糟。

词表：`assets/lexicon.tsv`，75,688 个英文词，由工作区语料 `tools/corpus/out/freq/freq.tsv`（9.2 万词频表）过滤而来。表格语料缺文学词，所以词表外的词会保留原形——这是有意的。

**高置信规则（不查词表也执行）**：

| 情形 | 例 |
|---|---|
| 不规则表（约 200 条） | `ran→run`、`children→child`、`better→good`、`lives→life`、`lit→light` |
| `-ies` / `-ied` → `y` | `studies→study`、`curtsied→curtsy` |
| `-ches` / `-shes` / `-sses` / `-xes` / `-zes` → 去 `es` | `watches→watch`、`classes→class` |
| `-oes` → 去 `es` | `heroes→hero` |
| `-eed` 保 e | `agreed→agree` |

**需要词表校验**：`-ing`、`-ed`、复数 `-s/-es`。做法是列出候选（原词干 / 双写还原 / 补 e / 去 s / 去 es），挑词表里存在的那个；`-ing`/`-ed` 同形歧义时按词频取舍（`hoping→hope` 而不是 `hop`），复数按优先级取（`spines→spine` 而不是 `spin`）。

**一个都验证不了 → 返回原形**。所以 `tousled`、`excruciating`、`lopsided`、`ill-advised` 会原样保留，不会被切成 `tousl` / `excruciat`。

**不做**的（故意的）：

- `-ly` 不剥：`reluctantly` 保持原样（否则 `early→ear` 这类事故）。
- `-er` / `-est` 不剥：`teacher` 不是 `teach` 的比较级。
- 不做词性标注；`interesting` 这类独立形容词有保护名单，不还原成 `interest`。

## 4. 去重与顺序

- 跨书去重：同一个词只保留首次出现那条记录（书、章节、日期）。
- 默认按阅读出现顺序输出；`--sort alpha` 改字母序。
- 大小写归一为小写；`'s` 所有格去掉（`company's → company`）。

## 6. 词表外的词：联网校验（`verify.py`）

本地词表只有 75,688 词，文学词汇常缺席（`curtsy`、`skitter` 都不在）。这些词不再盲猜，流程改为：

1. 筛出不在 `assets/lexicon.tsv` 里的词；
2. 并发查 `https://api.dictionaryapi.dev/api/v2/entries/en/<word>`（免费、免 Key）；
3. 按结果三分：

| 结果 | 含义 | 处理 |
|---|---|---|
| `valid`（HTTP 200） | 词典里有这个词 | 保留；首个释义写进 `review.md` |
| `invalid`（HTTP 404） | 词典明确查不到 | 判为拼写碎片/噪声，丢弃 |
| `unknown`（超时/断网） | 无法判定 | 保留，`review.md` 标"未验证" |

4. 结果缓存在 `~/.weread-vocab/word_cache.json`，同一个词不会重复联网；只有 `valid/invalid` 会进缓存，`unknown` 下次还会重试。词典站偶发 SSL 握手超时，所以每个词带 2 次退避重试（并发 4、超时 15s）。

关掉：`--no-verify`。断网时整批降级为 `unknown`，词不会被误删。

## 7. 什么时候该调规则

| 症状 | 调法 |
|---|---|
| 整句被当短语收进来 | 调小 `--max-tokens` / `--max-chars` |
| 长短语被整条跳过 | 调大这两个值 |
| 词表里混进 the/is/of | 不该发生（停用词已滤）；检查是否走了 `--no-lemma` 之外的路径、或单词级划线本身划的就是功能词 |
| 出现 `movy`、`buse` 这类怪词 | 规则边界问题，报给维护者；临时用 `--no-lemma` 出原形 |
