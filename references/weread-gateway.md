# 微信读书 Agent Gateway（本 skill 依赖的全部接口）

官方 skill：`Tencent/WeChatReading`（Apache-2.0，v1.0.6）。本 skill 只复用它的**接口约定**，不安装它、也不 import 它。

## 统一入口

```
POST https://i.weread.qq.com/api/agent/gateway
Authorization: Bearer $WEREAD_API_KEY        # wrk-xxxxxxxx
Content-Type: application/json
```

Key 来源优先级：环境变量 `WEREAD_API_KEY` →（`--use-saved-key` 时）`~/.weread-vocab/api_key` → 每次运行弹窗询问。
默认**不复用**已保存的 Key；`--remember-key` 才会把它存下来。Key 永远不写进 skill 目录。

```json
{"api_name": "/book/bookmarklist", "bookId": "123456", "skill_version": "1.0.6"}
```

规则：

- **业务参数必须平铺在 body 顶层**，包进 `params` / `data` 会导致参数被丢弃、永远返回第一页。
- 每次请求都要带 `skill_version`。
- API Key 绑定 vid，需要身份的接口自动注入，不要自己传 vid。
- 回包是裁剪过的 JSON；`errcode != 0` 即失败，用中文 `errmsg` 提示。
- 回包里的 `upgrade_info` 只是非阻塞升级提示，用同一份业务数据继续，不要重试。
- `{"api_name": "/_list"}` 可列出全部接口。

## /user/notebooks — 有笔记的书

请求：`{"api_name":"/user/notebooks","count":100,"lastSort":<上一页最后一条的 sort>}`

| 字段 | 含义 |
|---|---|
| `totalBookCount` / `totalNoteCount` / `hasMore` | 概览总数，`hasMore=1` 表示还有下一页 |
| `books[].bookId` | 书籍 ID |
| `books[].book.title` / `.author` | 书名、作者 |
| `books[].noteCount` | **划线数**（不是总笔记数） |
| `books[].reviewCount` | 想法/点评数（已含划线想法，别重复相加） |
| `books[].bookmarkCount` | 书签数，只统计不导出内容 |
| `books[].sort` | 最近笔记时间戳，翻页游标 |
| `books[].markedStatus` | 1=读完，0=在读 |

翻页：首次只传 `count`；`hasMore=1` 时取本页最后一条的 `sort` 作为下一页 `lastSort`。**不支持 offset/limit**。

## /book/bookmarklist — 单本书的划线

请求：`{"api_name":"/book/bookmarklist","bookId":"123456"}`

| 字段 | 含义 |
|---|---|
| `updated[]` | 划线数组，已自动过滤书签（type=0） |
| `updated[].markText` | **划线原文**（本 skill 的输入） |
| `updated[].bookmarkId` | 划线 ID |
| `updated[].chapterUid` | 章节 UID |
| `updated[].createTime` | Unix 时间戳 |
| `updated[].range` / `.colorStyle` | 位置范围、划线颜色 |
| `chapters[]` | `chapterUid` / `chapterIdx` / `title`，用来把划线归到章节 |
| `book` | 书籍信息（`title`、`author` 等） |

## 本 skill 用到的其它接口

- `/store/search`：`{"api_name":"/store/search","keyword":"原则","scope":10,"count":10,"context":"..."}`，用于书名→bookId。

## 排错

| 现象 | 原因 / 处理 |
|---|---|
| HTTP 401/403 | Key 无效或过期，去 https://weread.qq.com/r/weread-skills 重取 |
| `errcode != 0` | 按 `errmsg` 处理；常见是参数缺失或 bookId 不存在 |
| 翻页总是第一页 | 参数被包进 `params` 了，必须平铺 |
| 分页拿不全 | 忘了循环到 `hasMore=0` |
| 想要"查词历史/生词本" | **没有这个接口**。微信读书只暴露划线、想法、书签数量；词源只能用划线 |

## 版本

`skill_version` 默认 `1.0.6`，可用环境变量 `WEREAD_SKILL_VERSION` 覆盖；网关地址默认生产环境，可用 `WEREAD_GATEWAY_URL` 指向 mock（自检就是这么做的）。
