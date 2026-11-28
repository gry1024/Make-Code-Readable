---
name: make-code-readable
description: 把本地或 GitHub 仓库做成可离线阅读的双语代码教程。适用于想读懂项目架构、跟踪调用和数据流、从图解跳到源码、逐段对照代码学习的请求。
---

# Make Code Readable

为读者设计一条从“这个系统解决什么问题”走到“我能追踪一次真实执行”的学习路径。交付一个自包含的 `reader.html`。你负责阅读源码和撰写中英两套解释，构建工具负责验证、连线和渲染。

## 先读通一条执行路径

1. 读 README、入口、一个实际调用方和相关实现。选择一个具体输入，记下跨文件传递的对象、形状或状态变化，直至可观察的输出。核对训练与推理、初始化与请求处理、失败与重试等不同路径。
2. 从这条路径抽取读者必须先理解的概念。以读者的问题为章节标题。先讲最小可运行例子，再加入分支、策略与细节。学习顺序可以与运行顺序不同。
3. 在 `.mcr/structure.json` 写教程。每章用一个例子解释输入、机制和结果，给出一个或多个可验证的源码位置。边说明具体传递物或触发条件。独立工具可以单独成章。逐一从调用方核对边的方向。大仓库按子系统选取主线，把其他文件放在文件索引中。
4. 用 `python -m mcr.scan <repo>` 建分批清单，`--next` 查看待办。按用户指定的文件范围逐批覆盖；查看清单中的跳过项。每批处理并验证后在 manifest 标记 done。源文件改动后更新受影响的行号和讲解，再重新构建。

以下模块命令从本 skill 的根目录运行；其他工作目录可将 skill 根目录加入 `PYTHONPATH`。项目路径作为参数传入。

## 教程和架构图

`structure.json` 的最小示例；完整的分支和回路见 [示例教程](examples/demo-project/.mcr/structure.json)。

```json
{
  "repo_zh": "一次提交如何交给后台线程，并在失败后重试？",
  "repo_en": "How does a submission reach a worker and get retried on failure?",
  "dirs": {},
  "files": {"task_queue.py": {"zh": "调度和执行后台任务", "en": "Schedules and runs background jobs"}},
  "chapters": [{
    "id": "submit",
    "title": {"zh": "两个任务同时到期，先执行谁？", "en": "How are tied deadlines ordered?"},
    "body": {"zh": "优先队列先比较到期时间。到期时间相同时，锁内分配的序号决定顺序，队列无需比较函数对象。", "en": "Entries sort by deadline. A sequence number assigned under a lock breaks ties before the queue ever compares callables."},
    "refs": [{"file":"task_queue.py","start":40,"end":44,"zh":"检查锁和入队顺序","en":"Inspect locking and enqueue order"}]
  }],
  "edges": []
}
```

`chapters` 数组给出教学顺序。`edges` 中每项含 `from` 和 `to` 两个章节 ID，以及 `zh` 和 `en` 两种关系说明。每个链接使用仓库相对路径与 1-based 闭区间。锚点尽量落在实现决策的几行；需要串起接口时，把调用方和被调用方列为两条证据。

## 点进文件后，先回答它在系统里负责什么

每个源文件对应 `.mcr/annotations/<path>.json`，路径中的斜线换成 `__`。用 `note_zh` 和 `note_en` 交代谁调用它、处理的对象及主要输出。用 `symbols` 列出类、函数和关键方法，写明分工，必要时点出一个容易混淆的边界。Python 文件构建时也会提取定义位置；新写教程时，为读者撰写职责说明。其他语言按实际声明填写。配置文件用文件导读讲清主要配置组及读取方。

文件实例见 [Python 任务队列](examples/demo-project/.mcr/annotations/task_queue.py.json) 和 [JavaScript 客户端](examples/demo-project/.mcr/annotations/frontend.js.json)。符号条目形如：

```json
{"name":"TaskQueue.submit","start":38,"end":44,"zh":"把函数和参数包装成带到期时间的队列条目。","en":"Wraps the invocation in a queue entry with a due time."}
```

## 右栏按含义对齐

保留原始源码、顺序和行号。每个 block 讲一个小问题，`summary_zh/en` 概括这个阶段的职责。`lines` 中用 `n` 指定起始行，连续几行共同完成一个动作时给出 `end`。有独立意义的一行单独解释。覆盖每个非空行，括号、多行参数和注释随所属操作归组，空行可以留白。

写作时以刚才跟踪的具体输入为参照。告诉读者这一步利用了什么事实、数据从哪来、变成什么、下一步为何需要它。对于形状变换，指明每个关键维度在任务里的含义。区分代码明确保证的行为和你的推测。只有语法会影响理解时才解释语法。

例如 `self._seq += 1` 所在的三行可以共同解释为“锁内给这次提交领一个唯一序号。两个任务同时到期时用它打破平局。”再用下一条讲入队时为什么把序号放在任务前面。避免逐条复述 import、赋值、循环和闭括号，也不要用 AST 模板批量生成职责文字。中英文都要能独立读通。

```json
{"start":40,"end":42,"summary_zh":"同一到期时间如何排序","summary_en":"Breaking ties between deadlines","lines":[{"n":40,"end":42,"zh":"在锁内领取序号，同时提交的任务也会得到不同的排序键。","en":"Claim a sequence number under the lock so concurrent submitters receive distinct tie-breakers."}]}
```

文件顶层需含 `file`、`language`、`blocks`。blocks 按行号递增，无重叠或缺口，覆盖整个文件。每个范围只解释一次。刷新旧阅读页时，要重新阅读原注释，将机械直译改写为按意图分组的解释，优先更新教程引用的实现；交代实际改写范围。

## 构建与验收

```sh
python -m mcr.schema <repo>/.mcr/annotations <repo>
python -m mcr.build <repo> --annotations <repo>/.mcr/annotations --out <repo>/reader.html
```

构建时验证章节、符号、目标文件和源码范围。打开离线 HTML，从首页选一章，点源码链接，确认高亮覆盖实际操作；返回同一章，再从文件导读点一个方法。切换中英文，检查两种语言的例子和跳转目标一致。对照扫描清单检查交付范围；说明仍未讲解的部分。选区追问可另外使用 `python -m mcr.serve <repo> --annotations <dir>` 和 `MCR_API_KEY`。
