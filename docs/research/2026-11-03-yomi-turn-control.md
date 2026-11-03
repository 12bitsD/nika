# Yomi 原生 Loop：Turn 结束、steer 与收尾证据

核验日期：2026-11-03（Asia/Shanghai）。只读核对本地 fork 和最新 upstream 的原生 `Agent` / `Conductor`；不研究 coding harness 或 task-card 调度。未运行测试、模型、daemon 或远端代码。下文明确区分源码行为、测试断言与静态推断，不声称复现竞态。

## 1. 固定版本与范围

| 来源 | 本轮确认版本 |
|---|---|
| 本地 fork 研究 checkout | `feat/task-card-execution`，HEAD [`7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97`][fork-commit]；工作树干净 |
| origin `12bitsD/yomi` | `git ls-remote --symref origin ...`：默认分支/main 为 [`a8566269311cb10a870f2c706d5488f1a76dbbc1`][origin-commit]；`feat/chat-flow-requirements` 为 `7ec60e80...`；查询未返回远端 `feat/task-card-execution` |
| upstream `Crescent617/yomi` | `git ls-remote --symref upstream ...`：默认分支/main 为 [`2193746a4a2db2c17a62c5e66ba66a2c4e25056a`][up-commit]，GitHub commit API 显示 2026-11-02 05:21:58Z，`chore(release): v0.11.22` |

本地比较 origin/main 与 fork HEAD：本轮涉及的 `agent.rs`、`tool_exec.rs`、`mailbox.rs`、`conductor.rs` 和对应所引测试没有差异；`agent/types.rs` 有 fork 扩展，不能据此推论整个 fork 与 origin 相同。upstream 源文件通过固定 SHA 的 GitHub raw URL 下载到临时目录，未 fetch、checkout 或修改 Yomi 工作树。

## 2. 一手证据

### 2.1 没有 Tool Call 不是唯一结束条件；正常结束也没有检查 pending steer

**源码：** fork 先校验 `finish_reason` 与本次 `has_tool_calls` 是否一致，避免读取 buffer 中更早的 Tool Call。`ToolCalls` 进入工具执行；`MaxTokens` 最多注入一次 `continue`；不支持的 `PauseTurn` 记失败；`Refusal`、`Stop`、`Repeat` 进入收尾。不一致的原因也记失败。`Stop/Repeat → Completed → WindingDown` 路径没有读取 mailbox。[fork 转换][fork-transition]、[一致性表][fork-consistency]

**源码：** steer 仅在 Idle 和下一次 Streaming 调用前批量消费。若 steer 在一个最终文本响应的流式生成期间到达，当前正常结束路径仍先关闭旧 Turn，Idle 再消费它。upstream 最新版保留相同结构。[fork 主循环][fork-loop]、[upstream 主循环][up-loop]、[upstream 转换][up-transition]

**测试边界：** `mid_turn_steer_stays_in_turn_next_turn_anchors_to_it` 验证的是直接调用注入方法时不新增 Turn；它没有模拟“流式生成最终文本时输入到达”。另有空响应与未知 finish reason 进入 Failed 的测试，不能扩大为所有结束竞态已验证。[steer 测试][fork-steer-test]、[空响应断言][fork-empty-test]

**对 Nika：** 已确认的“final 候选前已有未注入 steer，则同 Turn 续调；final committed 后属于下一 Turn”比这份 Yomi 实现更明确。不能把 Yomi 主循环直接当作该语义的实现证据。Provider 正常结束只生成 final 候选，是否提交 final 还要经过输入归属检查；Refusal、截断、错误等分支需各自定义，不能统一解释成普通文本 final。

### 2.2 mailbox 接纳、消费与 Run 生命周期不是同一个操作

**源码：** fork 使用两个内存 `VecDeque`：steer 在 Streaming 前最多取 20 条并合并；normal 在 Idle 每次取一条。入队使用 Mutex，随后 `Notify::notify_one`。Conductor 每条输入各起异步任务，先处理附件、入 mailbox、发变更事件，再调用 `wake_agent`。这支持“等待执行期间继续接纳输入”，但这些代码不是持久化接纳记录，也不是一个统一的原始到达顺序事务。[mailbox][fork-mailbox]、[入队与消费][fork-mailbox-ops]、[输入任务][fork-dispatch]、[接纳与唤醒][fork-ingress]

**对 Nika：** 借用“接纳与注入分开”的职责即可。Nika 已选择单 steer buffer，不需要继承双队列或 20 条上限；其顺序应以已提交的 accepted 记录为准，而不是附件处理或异步任务的完成时间。

### 2.3 最后空队列检查与执行退出之间仍要有交接协议

**源码：** agent 在 Idle 等待两分钟后检查 `mailbox.is_empty()`，为空就退出；`wake_agent` 看到旧 handle 尚未 finished 就返回。spawn 包装在 `start_loop()` 返回后仅记日志，没有再次检查 mailbox；定期清理只移除已结束 handle、保留非空 mailbox，不主动唤醒它。[Idle 退出][fork-loop]、[wake 条件与包装][fork-wake]、[定期清理][fork-cleanup]。upstream 对应逻辑仍存在。[upstream Idle][up-loop]、[upstream wake][up-wake]

**静态推断，未复现：** 在多线程执行下可形成交错：旧 agent 最后观察空 → 新输入入队且 `wake_agent` 看到旧 handle 仍活跃而返回 → 旧 agent 退出。pending 可能留到下一次输入才被唤醒。单独的 Mutex 队列和 Notify 不把“确认空＋交出消费者归属”变成一个原子操作。本轮读取的测试没有覆盖该交错。

**对 Nika：** final 决策与 accepted 输入归属必须有确定的先后关系，不能只写“结束前再检查一次”。只需在现有 SessionManager/Store 契约内规定：一次 final 提交检查确认当前没有应属于本 Turn 的未注入输入；竞争输入要么使 final 暂缓并续调，要么在 final 提交后明确归下一 Turn。释放 writer 时，也须确保已有 pending 输入会被调度，不能靠再来一条消息唤醒。锁/事务/序号校验的具体选择仍属实现设计，无需增加第二调度系统。

### 2.4 集中收尾有价值，但 Completed、持久化与交付需要分清

**源码：** `WindingDown` 调用 `finish_turn_wind_down`：完成 checkpoint、等待 `turn_end` hook，再发 `Stopped`，之后转 Idle。`complete_current_turn` 用 `take()` 避免重复收尾。[fork 收尾][fork-finalize]。慢 hook 测试明确断言完成标记先于 `Stopped`，比只断言最后状态更能验证顺序。[慢 hook 测试][fork-finalize-test]

**源码与测试边界：** assistant message 经事件总线异步落盘；Conductor 收到 `Stopped` 后等待该 Session 持久化队列，再转发孤儿回复。其慢存储测试针对“转发前答案可读”，不是所有渠道的 durable-final/交付证明；源码也记有总线饱和导致丢件的限制。[持久化与转发][fork-persist]、[慢存储测试][fork-persist-test]、[总线限制][fork-interrupt]

**对 Nika：** 借鉴集中收尾及顺序测试。保留 Nika 已有“权威事实同步提交 → 执行资源清理 → final 投递/责任接管 → writer 释放”，不复制这套 EventBus 持久化路径，也不把 `Completed` 当作业务验证通过或消息已送达。

### 2.5 stop、部分输出和未完成工具需要分别处理

**源码：** fork `/stop` 先取消 active token，随后清空两个 mailbox，再等待旧 agent 结束；后到而尚存的输入可触发 respawn。它会删除 stop 时已有 pending 输入，与 Nika 已接受的“未注入 steer 保留，除非显式清空”不同。[stop][fork-stop]

**源码：** 流收集中的 cancel 或 Provider error 直接返回，累积的部分内容没有进入 `push_message`；Chunk 已可能用于显示。重试层按错误重试，没有以“已输出过内容”或“有新 steer”作为重试准入条件，也不会在重试内部消费 steer。[partial 路径][fork-partial]、[完整消息写入][fork-response]、[重试循环][fork-retry]。这是已读路径的行为，不证明外部渠道如何撤销已显示预览。

**源码及测试：** 工具取消先 abort，再 drain 已完成结果，最后仅为没有结果的调用补 cancelled 结果，保持 Call/Result 配对且不覆盖真实成功结果；测试检查结果 ID 和不重新执行已关闭调用。[工具取消][fork-tool-cancel]、[工具取消测试][fork-tool-test]。这提供配对思路；合成 cancelled 文本本身不能证明外部副作用已经停止，Nika 仍应区分 cancelled 与 unknown。

### 2.6 迟到事件与 upstream 变化

**源码：** stop 路径在等待旧 handle 之前从 `active` 移除它，先等待 5 秒，若仍是 WindingDown 再等 30 秒，超时则 detach。注释明确记录“迟到 Stopped 落进新 Turn”的窗口。upstream 新版仍保留该说明。[fork stop][fork-stop]、[upstream stop][up-stop]。这不是具有 Run fence 的旧事件隔离保证。

**upstream 限定：** 新版增加 deleted-session tombstone 阻止删除后的 ghost respawn，以及工具重复结果检测的警告/硬停止；但正常 `Stop/Repeat` 的 pending-steer 检查和 Idle 退出交接并未因此改变。[删除闸][up-delete]、[工具循环检测][up-tool-guard]。后者不构成修改 Nika 软预算的理由。

## 3. 最值得讨论的三点

1. **final 的唯一决策边界。** 正常模型响应是候选；输入接纳与 final commit 的竞争要有可测试的确定顺序。至少覆盖：响应返回前、返回后提交前、提交后各到一条 steer。
2. **结束与交接的责任。** 当前 Turn 的收尾、下一 Turn 的唤醒、旧 Run 的迟到结果必须由现有 owner 明确接管。验证“最后空检查之后来输入”和“旧 Run 超时后回调”，不引入常驻轮询或新队列。
3. **打断后的事实。** 保留已提交结果和 pending 输入；已显示 partial、未提交 partial、已完成工具、结果未知工具分别呈现。所有这些路径最终复用收尾，不通过重跑模型或副作用去补齐表面成功。

以上是实现与验收启发，不自动采纳 Yomi 的双队列、hook 系统、并行工具、硬停止或异步权威写入。

[fork-commit]: https://github.com/12bitsD/yomi/commit/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97
[origin-commit]: https://github.com/12bitsD/yomi/commit/a8566269311cb10a870f2c706d5488f1a76dbbc1
[up-commit]: https://github.com/Crescent617/yomi/commit/2193746a4a2db2c17a62c5e66ba66a2c4e25056a
[fork-transition]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent.rs#L1551-L1627
[fork-consistency]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent.rs#L1739-L1761
[fork-loop]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent.rs#L308-L390
[up-loop]: https://github.com/Crescent617/yomi/blob/2193746a4a2db2c17a62c5e66ba66a2c4e25056a/crates/kernel/src/agent/agent.rs#L312-L394
[up-transition]: https://github.com/Crescent617/yomi/blob/2193746a4a2db2c17a62c5e66ba66a2c4e25056a/crates/kernel/src/agent/agent.rs#L1574-L1648
[fork-steer-test]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent_test.rs#L1997-L2031
[fork-empty-test]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent_test.rs#L1422-L1457
[fork-mailbox]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/comms/mailbox.rs#L9-L17
[fork-mailbox-ops]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/comms/mailbox.rs#L116-L167
[fork-dispatch]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/kernel/conductor.rs#L139-L143
[fork-ingress]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/kernel/conductor.rs#L465-L503
[fork-wake]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/kernel/conductor.rs#L1002-L1142
[fork-cleanup]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/kernel/conductor.rs#L257-L271
[up-wake]: https://github.com/Crescent617/yomi/blob/2193746a4a2db2c17a62c5e66ba66a2c4e25056a/crates/kernel/src/kernel/conductor.rs#L1080-L1228
[fork-finalize]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent.rs#L531-L592
[fork-finalize-test]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent_test.rs#L2047-L2095
[fork-persist]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/kernel/conductor.rs#L175-L252
[fork-persist-test]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/kernel/conductor_test.rs#L420-L483
[fork-interrupt]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent.rs#L474-L504
[fork-stop]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/kernel/conductor.rs#L380-L451
[fork-partial]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent.rs#L1187-L1264
[fork-response]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent.rs#L1138-L1175
[fork-retry]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent.rs#L1633-L1705
[fork-tool-cancel]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent/tool_exec.rs#L282-L347
[fork-tool-test]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent/tool_exec_test.rs#L180-L238
[up-stop]: https://github.com/Crescent617/yomi/blob/2193746a4a2db2c17a62c5e66ba66a2c4e25056a/crates/kernel/src/kernel/conductor.rs#L407-L484
[up-delete]: https://github.com/Crescent617/yomi/blob/2193746a4a2db2c17a62c5e66ba66a2c4e25056a/crates/kernel/src/kernel/conductor.rs#L393-L407
[up-tool-guard]: https://github.com/Crescent617/yomi/blob/2193746a4a2db2c17a62c5e66ba66a2c4e25056a/crates/kernel/src/agent/agent/tool_exec.rs#L71-L108
