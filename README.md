# 微信读书划线 → 不背单词自制词书

把微信读书里划线的英文单词/短语，一键整理成[不背单词](https://bbdc.cn)能直接导入的**自制词书**。

只收**单词级 / 短语级**划线（整句自动跳过），自动清洗、还原词形、联网校验生僻词，再输出「一行一词」的 UTF-8 txt；配置 cookie 后还能直接调接口把词书建好。

> 非官方工具，接口来自抓包，随时可能变。

## 它解决什么

在微信读书读英文书时划词很方便，但划线没法直接拿去背。手动抄出来又有几个坑：

- 划线里常混着整句、引号、句号、多余空格，甚至有跨行断字 `inter-\nesting`
- `curtsied`、`sniffing` 这类词要还原成 `curtsy`、`sniff` 才和词库对得上
- 不背单词不支持词组、要求 ≥20 词、只要英文单词
- 导出过哪些词没有记录，每次都要重新删一遍

这个工具把这些都做掉了，并且记住已导出的词，**下次只出新增的**。

## 效果

```
· 有划线的书 5 本，等你选择…          ← 弹窗多选
《某本书》
  划线 145 条 → 收下 144 条（单词级 143、短语级 1），跳过 1
· 词表外的词 5 个，联网校验中…
  ✗ 词典查不到，丢弃 1 个：hand-knotted
  ✓ 词典确认 3 个
  抽词 144 → 去重 141 → 已导出 0 → 候选 141
  ✓ ~/.weread-vocab/out/wordbook_某本书_2026-11-19.txt（141 词）
  · 提交到不背单词…
  ✓ 平台识别 140/141 词
  ✓ 已创建词书《某本书》（140 词）
```

## 依赖

- Python 3.9+，**零第三方库**
- 微信读书 [Agent API Key](https://weread.qq.com/r/weread-skills)，格式 `wrk-xxxx`（免费，登录即取）
- 可选：不背单词 cookie（想全自动建词书才需要）

## 安装

### 方式一：作为 Agent Skill（Claude Code / 同类工具）

```bash
git clone https://github.com/<you>/weread-vocab-bubei.git ~/.claude/skills/weread-vocab-bubei
# 或任意 skills 目录：~/.agents/skills/、项目内 .claude/skills/
```

Agent 会自动读 `SKILL.md` 里的触发条件（"把微信读书划线导成单词本"等）。

### 方式二：直接当命令行工具

```bash
git clone https://github.com/<you>/weread-vocab-bubei.git
cd weread-vocab-bubei
python scripts/run.py            # 需要的话换成 python3
```

## 使用

```bash
python scripts/run.py                    # 弹窗要 Key → 弹窗选书 → 出词书
python scripts/run.py --all              # 所有有划线的书，各出一本
python scripts/run.py --book 原则         # 指定书
python scripts/run.py --all --merge      # 多本合成一本
python scripts/run.py --text notes.txt   # 不用 API，读本地文本（每行一条划线）
```

首次运行会**弹窗询问 API Key**，粘一次即可；默认每次都会问，想省事：

```bash
python scripts/run.py --remember-key     # 记住这次的 Key
python scripts/run.py --use-saved-key    # 以后复用
```

> 弹窗依赖 tkinter。Linux 上需要 `sudo apt install python3-tk`；装不了也没关系，脚本会自动退回命令行输入（`--no-gui` 可强制）。

### 全自动建词书（可选）

想让它直接把词书建好，需要不背单词的登录 cookie：

1. 浏览器登录 https://bbdc.cn
2. F12 → Network → 点任意 `api` 请求 → 复制请求头里的 `Cookie:` 整串
3. 存到 `~/.weread-vocab/bbdc_cookies.txt`

然后：

```bash
python scripts/run.py --upload --create                       # 提交识别 + 建词书
python scripts/run.py --upload --create --book-name "书名 第一批"
python scripts/run.py --upload --prune-unknown --create        # 先剔除平台不认的词
```

`JSESSIONID` 是会话级，过期会报「鉴权失败 HTTP 403」，重新登录抓一次即可。

## 它是怎么做的

| 阶段 | 做法 | 细节 |
|---|---|---|
| 取数 | 微信读书 Agent Gateway（`i.weread.qq.com/api/agent/gateway`），Bearer Key | [references/weread-gateway.md](references/weread-gateway.md) |
| 清洗 | 剥引号/括号/句读/全角标点/零宽字符，拼跨行断字，去行首编号 | [references/word-rules.md](references/word-rules.md) |
| 筛粒度 | 单词级 / 短语级（2–4 词、≤50 字符、无句末标点），整句和中文跳过 | 同上 |
| 抽词 | 短语拆实词，滤停用词与专名 | `assets/stopwords.txt` |
| 词形还原 | 75,688 词自带词表校验；验证不了就保留原形，绝不造词 | `assets/lexicon.tsv` |
| 联网校验 | 词表外的词查 [dictionaryapi.dev](https://dictionaryapi.dev/)，三级结果 | [references/word-rules.md](references/word-rules.md) |
| 提交 | `/lexis/book/file/submit` 上传识别，`/lexis/book/save` 建词书 | [references/bbdc-import.md](references/bbdc-import.md) |

## 隐私

- Key 和 cookie 只存在 `~/.weread-vocab/`，**不写进仓库、不进 skill 目录**
- 日志里只出现掩码（`wrk-…abcd`）
- 联网只访问三个地方：微信读书网关、dictionaryapi.dev、bbdc.cn
- `.gitignore` 已排除 `out/`、`data/`、`api_key`、`bbdc_cookies.txt`

## 开发

```bash
python scripts/selftest.py     # 20 个用例，本地 mock gateway + mock 词典，不联网
```

目录：

```
SKILL.md           Agent 的操作说明（触发条件 + 工作流 + 参数）
scripts/           run.py 主入口；extract 抽词；verify 联网校验；bbdc_upload 提交
assets/            lexicon.tsv（词表）、stopwords.txt
references/        接口文档、上传接口、抽词规则
```

欢迎 PR：新增考试词表、支持更多平台（墨墨/欧路）、改进词形还原规则。

## License

MIT
