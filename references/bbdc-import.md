# 不背单词「自制词书」上传

两条路：**全自动**（cookie + 直接打接口）或**手动**（网页点四下）。先看自动那条。

## 自动上传：接口与鉴权

端点来自一次真实抓包（Chrome「Copy as cURL」）：

```
POST https://bbdc.cn/lexis/book/file/submit
Content-Type: multipart/form-data
字段：file（filename 用真实文件名，Content-Type: text/plain）
Header：Origin/Referer = https://bbdc.cn，X-Requested-With: XMLHttpRequest
鉴权：Cookie 里的 JSESSIONID + hanhan（acw_tc、Hm_* 是统计用的，可留可删）
```

回包直接给出平台识别结果：

```json
{"result_code":200,"data_body":{
  "knowList":"snowflake,curtsy,…",      // 平台认识，能进词书
  "unknowList":"appreciatively"          // 平台词库没有
}}
```

实测：141 词 → 识别 140，未识别 1（`appreciatively`）；74 词 → 72，未识别 `gawker`、`incanted`。

**连字符没关系**：`ill-advised` 在 knowList 里，平台是认的，不需要拆词。

### Cookie 怎么来

1. 浏览器登录 https://bbdc.cn
2. F12 → Network → 点任意一个 `api` 请求 → 复制请求头里的 `Cookie:` 整串
3. 存到 `~/.weread-vocab/bbdc_cookies.txt`（不在 skill 目录里）

```powershell
& $py "$s\scripts\bbdc_upload.py" 词书.txt --cookie "JSESSIONID=...; hanhan=..." --save-cookie
```

`JSESSIONID` 是会话级，会过期；过期时报“鉴权失败 HTTP 403”，重新登录抓一次即可。

### 第二步：创建词书

```
POST https://bbdc.cn/lexis/book/save
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
字段：wordList=<逗号分隔的单词>  name=<词书名>  desc=<简介>  exam=<分类代码，可空>
```

回包：`{"result_code":200,"data_kind":"lexis_book","data_body":{}}` 即建成。

- `wordList` 用第一步回包的 `knowList`（平台认识的词）最稳；直接塞未知词会被平台过滤。
- **少于 20 词直接拒绝**：`result_code 20000`，“上传的单词小于20个不能创建词书”。脚本会先拦。
- `exam` 是考试分类；传空串可以（实测通过），`KY` = 考研。
- 名称重复不会报错，会生成同名新词书。

### 查已有词书

```
POST https://bbdc.cn/lexis/book/list      （无参数）
→ data_body.list[]：name / createTime / …
```

可用来自查自动化是否成功。

### 用法

```powershell
& $py "$s\scripts\run.py" --upload                   # 提交 + 打印识别结果
& $py "$s\scripts\run.py" --upload --create          # 再建词书（名字默认用书名）
& $py "$s\scripts\run.py" --create --book-name "书名 第一批" --desc "微信读书划线"
& $py "$s\scripts\run.py" --upload --prune-unknown    # 识别不了的自动剔除再建
& $py "$s\scripts\bbdc_upload.py" 词书.txt --save-book --name "书名"
```

整条链现在无人值守：**取划线 → 抽词 → 联网校验 → 上传识别 → 建词书**。

## 手动上传（兜底）

### 格式要求（硬约束）

| 项目 | 要求 |
|---|---|
| 文件 | `.txt`，UTF-8 **无 BOM**，一行一个单词 |
| 内容 | 只要英文单词；**不要写释义列**，平台按词库自行匹配释义和例句 |
| 词组 | **不支持**。`take off` 会被判无效，所以短语必须拆成单词 |
| 词数 | 识别成功的单词 **≥20** 才生成词书，少了直接失败 |
| 生僻词 | 平台词库没有的人名/术语会识别不到，正常现象 |

本 skill 产出的 `~/.weread-vocab/out/wordbook_*.txt` 已满足以上全部要求（含去掉 BOM、末尾换行）。

## 上传步骤

1. 电脑浏览器打开 https://bbdc.cn 并登录（手机号/微信）。
2. 右上角菜单（三道杠）→「自制词书」。
3. 选择上一步生成的 txt → 点「识别」。
4. 识别完成后填词书名称、标签、简介 → 提交。
5. 等状态变成「词书处理完成」。
6. 手机 App：计划 / 仪表盘 → 换本词书 → **我的自制** → 选刚建的这本。

## 常见失败

| 现象 | 原因 |
|---|---|
| 提示"请选择 txt 格式" | 编码不对，用记事本另存为 UTF-8；或文件其实是 docx 改名 |
| 识别为 0 / 很少 | 每行不止一个词，或混了中文、标点、编号 |
| 无法生成词书 | 识别成功数 < 20 |
| 某词一直"未识别" | 平台词库没有（专名、拼写变体），从 `review.md` 找出对应词删掉后重传 |
| 上传后 App 里找不到 | 在「我的自制」里，不在官方词书列表 |

## 想改词表怎么办

- 删几个词：直接编辑 txt 再传一次（会生成新词书）。
- 想整批重来：删掉 `~/.weread-vocab/data/state.json`，重新跑 `run.py`。
