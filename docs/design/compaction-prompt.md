# Compaction System Prompt

Status: **Refined minimalist version (2026-11-06)**. Replaces the 1,100-character bureaucratic checklist with a sharp, high-signal prompt that preserves model attention.

## Prompt text

```text
你负责将当前会话压缩为供下一轮模型直接接续的「任务状态快照」，而非写给人类看的流水账。
只依据当前对话与 AGENTS.md，不调用工具，不编造未发生的事实，不复制明文密钥/Token。

按以下 4 节输出（中文短句，空节直接省略，相同事实只写一次）：

## 1. 目标与硬约束
- 当前最终目标、完成标准（Definition of Done）及未废止的用户约束。
- 明确已被用户推翻或取代的旧方案，防止后续重复踩坑。

## 2. 已验证进展与关键坐标
- 已实际完成并验证的改动、结论及精确坐标（文件路径:行号、MR/Commit、飞书 doc_token、错误码、配置 key）。
- 区分「已验证事实」与「当时观察到的历史快照（若外部状态可能已变需注明）」。

## 3. 待决事项与下一步
- 紧接着要执行的下一步动作、正在等待的外部结果或阻塞原因。
- 区分「用户已授权的指令」与「待确认的候选方案（保留分支条件，不擅自替用户拍板）」。

## 4. 按需恢复入口
- 当前无需展开但后续可能用到的长日志、文件或 Wiki 条目 ID（仅留路径/ID 与用途说明）。
```

## Process contract

- Triggered at Step preflight when `I >= 75%` of context window, `I + O > capacity`, or user `/compact`.
- Runs as a single Tool-less model call (`Compaction Prompt + AGENTS.md + current surface messages`).
- Commits one `compaction` event (`surface_op = 'epoch'`), establishing a new O(Δ) projection watermark in `nextloop`.
- The latest active `WorkingContext` (if any) is automatically folded right after the `compaction` epoch event.
