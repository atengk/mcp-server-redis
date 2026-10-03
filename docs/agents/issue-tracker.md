# 任务跟踪器：GitHub (Issue Tracker)

本项目的所有任务工单、需求规格（Spec）与缺陷跟踪统一记录在 GitHub Issues 中。所有交互操作统一通过 `gh` 命令行工具完成。

---

## 常用操作规范 (Conventions)

- **创建 Issue**：`gh issue create --title "..." --body "..."`。多行正文内容推荐使用分行文本块或标准输入管道传递。
- **查看 Issue**：`gh issue view <编号> --comments`，结合 `jq` 过滤评论并读取关联标签。
- **检索 Issue 列表**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，可按需附加 `--label` 和 `--state` 过滤参数。
- **发表评论**：`gh issue comment <编号> --body "..."`
- **应用 / 移除标签**：`gh issue edit <编号> --add-label "..."` / `--remove-label "..."`
- **关闭 Issue**：`gh issue close <编号> --comment "..."`

仓库地址由本地 `git remote -v` 自动推断——在克隆仓库的工作区内运行 `gh` 会自动识别目标仓库。

---

## Pull Request 作为分类接入点

**PR 是否作为需求接收端：否**。（若本项目后续将外部 PR 视同功能需求纳入流转，可将此项置为 `是`；`/triage` 技能会读取此项配置）。

当配置为 `是` 时，PR 将遵循与 Issue 完全一致的标签流转与状态规范，通过 `gh pr` 系列命令操作：
- **查看 PR**：`gh pr view <编号> --comments` 以及 `gh pr diff <编号>` 获取改动差异。
- **获取待分流外部 PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，仅保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的外部提交（自动过滤仓库所有者与核心协作者）。
- **评论 / 标签 / 关闭**：对应执行 `gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

因 GitHub 的 Issue 与 PR 共享同一数字编号空间（如 `#42`），若无法判定具体类型，优先尝试 `gh pr view 42`，失败后平滑降级执行 `gh issue view 42`。

---

## 当技能提示“发布至任务跟踪器”时

直接调用 GitHub CLI 在当前仓库中创建 GitHub Issue。

---

## 当技能提示“获取对应工单”时

执行命令 `gh issue view <编号> --comments` 获取完整工单上下文与历史交流记录。

---

## 寻路器操作规范 (Wayfinding Operations)

供 `/wayfinder` 技能调度使用。**路线图 (Map)** 为单个汇总 Issue，其**子任务工单**为关联的具体子 Issue。

- **路线图 (Map)**：标注 `wayfinder:map` 标签的独立 Issue，主体记录笔记、既定技术决策及待探索迷雾区。创建命令：`gh issue create --label wayfinder:map`。
- **子任务工单 (Child Ticket)**：通过 GitHub sub-issue 关联至主路线图（调用 `gh api` 子工单端点）。若当前环境未启用 sub-issues，在路线图正文中添加任务列表（Task list），并在子任务工单正文顶部添加 `Part of #<路线图编号>`。标签格式为 `wayfinder:<类型>`（`research`、`prototype`、`grilling`、`task`）。一旦认领，指派给执行开发者。
- **阻塞依赖关系 (Blocking)**：采用 GitHub 原生任务依赖机制。通过 `gh api --method POST repos/<所有者>/<仓库>/issues/<子任务编号>/dependencies/blocked_by -F issue_id=<前置阻塞任务数据库ID>` 添加依赖关系（注意此处为数字 database id，非 `#` 编号）。GitHub 会输出 `issue_dependencies_summary.blocked_by` 字段。若依赖 API 不可用，在子任务正文顶部以 `Blocked by: #<编号1>, #<编号2>` 显式声明。所有阻塞任务关闭后视为解除阻塞。
- **前沿就绪查询 (Frontier Query)**：列出路线图中所有未关闭子任务，过滤掉存在未完成前置阻塞或已有指派人的任务，按照任务列表先后顺序认领。
- **认领任务 (Claim)**：`gh issue edit <编号> --add-assignee @me`。
- **办结任务 (Resolve)**：`gh issue comment <编号> --body "<方案总结>"`，随后执行 `gh issue close <编号>`，最后在路线图 Issue 的“既定决策”段落中追加结论索引。
