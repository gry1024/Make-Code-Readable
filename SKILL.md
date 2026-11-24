---
name: make-code-readable
description: 把一个 GitHub 仓库或本地目录变成可交互的双栏代码阅读页面（左栏源代码、右栏自然语言伪代码式的逐行解释，中英双语），产出自包含 HTML 或本地服务。当用户想"读懂这个仓库"、"给这个仓库生成代码讲解"、"做一个代码阅读页面"时使用。
---

# Make-Code-Readable

你（Agent）就是注释生成器——不需要任何外部 API Key。你的任务是阅读目标仓库，按本文件约定的 JSON schema 为每个源文件生成「段落总结 + 自然语言伪代码式的逐行解释」，然后调用构建脚本生成阅读页面。

## 核心写作风格（最重要，先读这个）

右栏不是"评注"，而是**用自然语言重写的代码（伪代码）**。用户读右栏时，应该像读代码一样、按同样的逻辑顺序理解程序，只是换成了人话。

### 每行解释 = 该行代码的自然语言直译

保留代码的控制结构（条件、循环、赋值、调用、返回），用自然语言表达操作本身。**不要**写"这一行是……"、"这一行用于……"、"这一行定义了……"这类散文式评注。

示例（Python）：

| 代码 | 右栏解释（zh） |
|---|---|
| `for attempt in range(retries + 1):` | 循环 `attempt` 从 0 到 `retries`（含），每次 +1 |
| `if not resp.ok: raise ...` | 若 响应非 2xx → 抛出 HTTP 状态错误 |
| `self._seq += 1` | `seq` 序号 +1 |
| `timer = setTimeout(..., wait)` | 启动 `wait` 毫秒定时器，到点才真正执行 `fn` |
| `return () => { stopped = true }` | 返回停止函数：调用它 → `stopped` 置真，轮询终止 |
| `with self._lock:` | 进入锁保护区 { |
| `}` | } 结束 if 块 |

规则：
- **每个非空代码行都必须有自己的解释条目**，包括单独的 `{`、`}`、`)`——闭合行用「} 结束 xx 块」说明关闭的是什么。空行可跳过（页面自动留空对齐）。`schema.py` 会强制检查，任何非空行缺解释都会报错。
- 控制流用「若 … → …」「循环 …」「… 时 → …」的句式；多分支用「若 A → …；否则 → …」。
- 标识符、函数名、字面量用反引号包成行内代码（页面会高亮渲染）；支持 `**加粗**` 和换行（`\n`）。
- 在直译之后，如有关键的"为什么"（设计意图、坑、副作用），用一句简短补充，以「→ 因为…」或「（…）」收尾；没有就不加，不硬凑。
- 解释长度与代码复杂度匹配：简单行几个字即可，复杂行最多两句。右栏会按代码缩进同步缩进，不要在文本里再加空格缩进。
- `summary_zh` 是宏观注释：一句话（20–40 字）说清整段的职责与思路，允许比逐行更抽象。

## 分批生成策略（大仓库必用）

不要试图一次注释整个仓库。用扫描工具生成批次清单，逐批推进、可随时中断续跑：

1. **扫描分批**：
   ```bash
   python <skill_dir>/mcr/scan.py <repo_path>
   ```
   产物 `<repo>/.mcr/manifest.json`：自动跳过 `.git`/`node_modules`/锁文件/minified/二进制，>2000 行的文件列入 `oversized_skipped`；按「入口文件 > README 提及 > 目录深度浅 > 文件小」排序，切成若干批（默认每批 ≤5 文件且 ≤1200 行）。
2. **逐批处理**：`python <skill_dir>/mcr/scan.py <repo_path> --next` 查看下一批待办文件。每批内逐文件生成注释 JSON。
3. **单文件即时校验**：每写完一个文件的 JSON，立即校验（见下文），通过后在 manifest 中把该文件 `status` 改为 `"done"`，失败改 `"failed"` 并记录原因。中断后重跑时跳过所有 `"done"`。
4. **每批结束构建预览**：注释目录是增量累积的，随时可 build，已完成的文件立即可读。
5. **大文件内部再分块**：单文件超过约 150 行时，按函数/类分多次生成，逐次追加到该文件的 `blocks` 数组（保持行号升序不重叠），全部写完后一次性校验。

## 注释 JSON Schema（严格遵守）

每个源文件一个 JSON，写入 `<repo>/.mcr/annotations/`，文件名把路径中的 `/` 换成 `__`，如 `src__main.py.json`：

```json
{
  "file": "src/main.py",
  "language": "python",
  "note_zh": "可选，文件级备注",
  "note_en": "optional file-level note",
  "blocks": [
    {
      "start": 1,
      "end": 12,
      "summary_zh": "一句话概括这段代码的职责与思路",
      "summary_en": "One-line summary of this block's responsibility and approach",
      "lines": [
        {"n": 1, "zh": "该行代码的自然语言直译（中文）", "en": "natural-language pseudocode of this line (English)"}
      ]
    }
  ]
}
```

- `file` 必须与仓库内相对路径**完全一致**；`language` 用 highlight.js 的语言名（`python`、`javascript`、`typescript`、`go`、`rust`、`java`、`c`、`cpp`、`bash`、`json`、`yaml`、`markdown` 等）。
- `blocks` 按行号升序、不重叠地覆盖整个文件（1-based 闭区间），空行也必须落在某个 block 范围内。
- 分块粒度：按函数 / 类 / 逻辑段落切分，每块 3–40 行为宜。
- 中英文语义对等（不是逐字翻译），都遵循上面的伪代码风格。

## 仓库宏观结构解析（structure.json）

除了逐文件注释，还要生成一份 `<repo>/.mcr/structure.json`，驱动阅读页的「仓库总览」视图（左侧 IDE 目录树自动包含全仓库文件，无需配置）：

```json
{
  "repo_zh": "一段话：这个仓库是什么、由哪几大部分组成、核心数据流是什么",
  "repo_en": "one paragraph: what this repo is, its main parts, the core data flow",
  "dirs": {
    "src": {"zh": "一句话说明该目录职责", "en": "one-line purpose of this directory"},
    "src/core": {"zh": "...", "en": "..."}
  },
  "files": {
    "src/main.py": {"zh": "一句话说明该文件职责", "en": "one-line purpose of this file"}
  }
}
```

- 先读 README + 浏览目录树再写 `repo_zh/repo_en`；`dirs` 覆盖所有一级目录与核心二级目录；`files` 至少覆盖已注释文件与入口文件。
- 写宏观解析要「有观点」：说清模块之间怎么协作，而不是罗列目录名。

## 校验与构建

```bash
# 校验：行号越界、block 重叠/缺口、非空行缺解释都会报错
python <skill_dir>/mcr/schema.py <repo>/.mcr/annotations <repo>

# 构建自包含 HTML
python <skill_dir>/mcr/build.py <repo> --annotations <repo>/.mcr/annotations --out <repo>/reader.html
```

## 交付

- 默认交付：告诉用户双击 `reader.html` 即可离线阅读。
- 划词提问（选中即自动解释，无需点击）需要本地服务：
  ```bash
  export MCR_API_KEY=...   # OpenAI 兼容接口
  python <skill_dir>/mcr/serve.py <repo> --annotations <repo>/.mcr/annotations
  ```
