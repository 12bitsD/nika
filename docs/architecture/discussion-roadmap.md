# Architecture discussion roadmap

Purpose: finish the architecture without losing decisions or the main thread. This file is the controlling plan for discussion. The [feature worklist](feature-worklist.md) tracks individual features; this roadmap controls their order and closure.

Current stage: **M5 — Context, cache, and compaction**. No runtime implementation is authorized by this roadmap.

Current discussion entry: [T1 — 执行控制与 ReAct](#topic-execution), jointly checking its Tool interface with [T3](#topic-tools). The topic map below groups the remaining questions by responsibility; M1–M9 still track stage dependencies and closure.

**2026-11-02 review:** the M4 state-machine/lifecycle baseline remains recorded, with an explicit **ReAct execution-protocol follow-up** now open. See the [capability review and G0–G13 index](agent-loop-capability-review.md#closure-gap-index). The external survey supplies comparison criteria and proposed capabilities; it does not authorize Router/Worker, hard resource budgets, background jobs, or autonomous task restart.

## Fixed guardrails

These decisions should not be reopened without an explicit change of product direction:

- One AgentLoop for ordinary chat and coding; no external coding harness or coding mode.
- One container for Bot, BrowserUse, and ComputerUse; no remote device bridge.
- Feishu is the primary channel, including documents and document comments.
- One `AgentWiki` root, with Wiki and Skill consumed through different mechanisms.
- Every Session produces Trajectory; export is on demand, with no automatic RSI or automatic Wiki promotion.
- Keep the system small. Do not add a generic EventBus, remote event replay, task-card system, agent-defined Hooks, or unrelated platform features.

## Route

| Stage | Mission | Main question | Required output and close condition | Status |
|---|---|---|---|---|
| Research | M1, M2 | What do yomi, Hermes, OpenAI, and Anthropic already prove? | Primary-source notes for runtime, Trajectory, compaction, Skill, and extension mechanisms | Done |
| Core | **M4** | What exactly happens inside AgentLoop? | State transitions, event order, Tool concurrency, cancellation, finalization, and failure paths are unambiguous in all listed scenarios | State-machine/lifecycle baseline recorded — [agent-loop.md](../design/agent-loop.md); **ReAct protocol follow-up open** — [G0](agent-loop-capability-review.md#react-execution-protocol-gap) |
| Context | M5 | What exactly does the model see, and how is it compacted? | Deterministic ContextBuilder, revision/cache rules, 75% compaction, WorkingContext, and budget behavior are consistent with M4 | **In progress** — [context-builder.md](../design/context-builder.md) |
| Resources | M6 | What can each actor and process access, and who owns each resource? | Trust/credential rules, resource ownership, locks, concurrency, and crash cleanup cover every Tool and shared resource | Pending; depends on M4 |
| Data and channels | M7 | What is authoritative, and how do external systems observe it? | Session/event/projection schema, Trajectory/export contracts, Feishu acceptance, backup, and GC are consistent | Pending; depends on M5 and M6 |
| Engineering | M8 | How is the design implemented and verified? | Language, package layout, dependencies, container processes, storage mounts, health checks, and CI levels are chosen | Pending; depends on M7 |
| Special topic | **M3** | How should Wiki actually be consumed? | A dedicated comparison and decision for bootstrap, retrieval, automatic recall, writeback, cache, and compaction | **Done** — [agentwiki.md](../design/agentwiki.md); Git synchronization and writer coordination belong to M6/M7 |
| Special topic | Proactive | How should the Bot reduce the user's context-management burden? | A separate mechanism for task-phase detection, internal updates, user-facing distillation, authorization boundaries, and interruption policy | Planned after M5; value accepted, behavior not yet designed |
| Closure | M9 | Is the architecture complete and implementable? | End-to-end review, no unowned big questions, synchronized docs, and a staged implementation plan | Pending; depends on M3, Proactive, and M8 |

M5 and M6 may be discussed in parallel after M4 if their inputs stop changing. M7 must not be used to resolve new questions by silently changing M5 or M6; any change goes back to the owning stage and is recorded there first.

<a id="discussion-topics"></a>

## Discussion topics by responsibility

2026-11-02 按用户要求，将 [G0–G13](agent-loop-capability-review.md#closure-gap-index) 与综述中的补充建议归入以下大 topic。T 编号表示讨论归属，不规定代码包、类、服务或新增运行时模块。每个 gap 有一个主 topic；跨模块行为在接口处联合关闭。讨论顺序与状态仍由本 roadmap 维护，具体决定回到所属 design 文档，feature worklist 继续维护能力覆盖。

**状态口径：**已有决定继续沿用；契约缺口需要补到可实现、可验证；P1–P5 与 Router/Worker 等新增机制仍为候选。完成本次归组不等于关闭任何行为问题，也不减少已确认的完整交付范围。

| Topic / 负责模块 | 要回答的核心问题 | 主归属 gap | 原阶段 |
|---|---|---|---|
| [T1 执行控制与 ReAct](#topic-execution) — AgentLoop / SessionManager | 当前输入怎样推进、等待、停止并形成可信结果？ | G0、G2 | M4 follow-up；M6–M8 接口 |
| [T2 模型请求与上下文](#topic-context) — ContextBuilder / ModelProvider / Compactor | 模型每次看到什么，响应怎样被解释，如何合法续调？ | G3 | M5 / M8 |
| [T3 能力执行、权限与资源](#topic-tools) — Tool Catalog / ToolRuntime | 一个动作什么时候能执行，影响什么，怎样取消与释放？ | G1、G4、G5 | M5 / M6 / M8 |
| [T4 持久状态与数据生命周期](#topic-state) — Session Store / Trajectory / Assets | 什么已经成为事实，故障后怎样恢复、查询和保留？ | G6、G10 | M7 / M8 |
| [T5 渠道与交互交付](#topic-channels) — Feishu ingress / rendering / delivery | 外部输入归谁，用户怎样看到结果和参与执行？ | G8、G9 | M7 |
| [T6 知识与行为资产](#topic-knowledge) — AgentWiki / SkillLoader | 经授权的知识或 Skill 修改怎样验证、发布并生效？ | G7 | M3 后续集成；M6 / M7 |
| [T7 主动性与注意力](#topic-proactive) — Proactive 专题 | 何时值得主动整理、行动、唤醒或打扰用户？ | G11 | M5 后专题 |
| [T8 工程运行与全功能验收](#topic-engineering) — 部署、诊断、CI 与整体验收 | 怎样稳定运行，并证明全部已确认能力可交付？ | G12、G13 | M8 / M9 |

<a id="topic-execution"></a>

### T1 — 执行控制与 ReAct

沿用 [AgentLoop](../design/agent-loop.md) 的单执行路径、单 steer buffer、串行 Tool、软预算与未知副作用不重放。AgentLoop 内部的 driver / input / model invocation / Tool batch / finalization 按已记录职责继续细化；SessionManager 负责 entry→Session、Run 生命周期与唯一执行 writer。

**2026-11-03 已确认：**一个 Turn 可包含多条运行中的 steer。模型准备正常结束时，已接纳但尚未交给模型的 steer 先在当前 Turn/Run 处理；final commit 后接纳的输入归下一 Turn。模型响应保存与最终回复提交分开，输入接纳和最终提交必须有一致先后顺序，详见 [AgentLoop §6.1](../design/agent-loop.md#normal-turn-completion)。本次只关闭这一行为选择；异常响应、验证机制与具体持久化实现仍待讨论和验证。

同日源码参考：[Hermes](../research/2026-11-03-hermes-turn-control.md) 与 [Yomi](../research/2026-11-03-yomi-turn-control.md)。两者都存在将剩余 steer 留给后续 Turn 的路径，不能作为 Nika 已确认同 Turn 规则的实现证明。可借鉴的验证场景包括最后输入检查与执行权移交、清理期间的新输入、取消后的真实工具结果；其他行为仍按各 topic 决定。

**2026-11-03 普通工具错误已确认：**文件不存在、测试失败等结果先保存并交回模型，由模型决定修正、换方法或说明受阻后结束；错误本身不结束 Turn。详见 [AgentLoop §5.1](../design/agent-loop.md#ordinary-tool-errors)。取消、未知副作用和结果保存失败分别处理；同批其他调用遇到前序失败时是否继续，仍待讨论。该问题的 [Hermes/Yomi 源码比较与两种候选](../research/2026-11-03-tool-batch-failures.md) 已记录；“普通错误继续，有依赖动作分两次模型调用”仍是待确认建议。

待讨论：

- ReAct 决策表：完整/混合/空/截断/拒绝/中断响应怎样转为调用、Observation、续调或收尾；模型终止、业务完成和投递完成分别怎样表达。
- 输入控制表：WaitingRequest 回答与 steer 怎样判别；retry、stop 或重启下的输入归属，以及保留的 pending 输入何时允许起跑。final commit 前后的归属已确认，接纳/提交事务与并发验证交 T4。补齐 `/new`、workspace 切换、model/Provider 配置与显式 AGENTS 刷新在活跃 Run/等待/积压输入下的接纳与生效时点，沿用已有 Session 和 revision 规则。
- 内部 Interface：哪个 flow 提交哪个事实、返回什么 outcome；Provider attempt 与 logical call 身份、重建请求、取消与 finalization 接管怎样衔接。重试分类和可恢复响应由 T2 提供，Run/lease fencing 由 T4 保证。
- P1/P2 候选：如何把目标、验证证据、未完成项接入交付；是否增加无进展诊断和软成本提醒。验证方法依任务/Skill 决定，正常轮询与无效重复要区分，不新增通用 Planner/Verifier，不改变软预算。

关闭产物：响应→动作决策表、输入→Turn/continuation 归属表、内部 flow 输入/输出与 commit owner 表，以及成功/异常/取消的完整场景。具体完成状态表达仍待本 topic 决定，不在归组时预选新的持久 Task 对象。

<a id="topic-context"></a>

### T2 — 模型请求与上下文

沿用 [ContextBuilder](../design/context-builder.md) 的固定 revision 内前缀不变、WorkingContext 单 active slot、usage fallback、75% 或容量超限压缩与专用 Prompt。

待讨论：Provider 原生字段与统一逻辑响应怎样映射；完整/部分 streaming、调用 ID、公开 reasoning summary 与必须回传的 opaque 字段怎样保留；规范化序列化、缓存标记和 model switch 怎样验证；summary 请求本身超限时怎样处理；“有效且显著缩小”的压缩检查、Tool Call/Result 配对与多模态重建怎样落地。Provider 错误→重试/修正/终止分类表须覆盖 `Retry-After`、退避/jitter、次数与单次超时，并与 T1 的 stop/steer 和 partial-output 规则联合验证，避免 SDK 与 invocation 重复重试。大结果预览和检索提示归此处，完整资产的存储/保留规则交 T4。

关闭产物：完整候选请求→admitted request 的 Interface、各 Provider 请求/响应样例、续调/缓存/压缩验证矩阵。T2 输出模型协议事实，T1 决定下一步运行行为；Tool schema 的语义由 T3 定义，T2 只负责正确呈现。

<a id="topic-tools"></a>

### T3 — 能力执行、权限与资源

沿用静态 Tool Catalog、模型参数与 runtime 注入字段分开、首版串行执行、同容器 Browser/Computer 及 GUI 锁。工具运行期间接收输入是既有执行契约；跨 Turn 后台 job 仍是额外候选。

待讨论：

- Catalog：每个 Tool 的 schema/description、返回值与错误、调用 ID、取消/超时、部分成功/未知、大结果示例；区分调用格式校验、运行前授权与资源准入，明确被拒调用如何反馈和计数。
- Trust：发起人/事件来源与当前有效授权如何绑定；进程凭据、shell/file/network、Browser 登录态怎样约束；Wiki 的 curate/behavior 权限怎样避免被通用文件或 shell 操作绕过。此授权契约也供入口、Session 查询/导出和 Wiki 发布使用，不能只存在于 ToolRuntime 内部。Mandate 的授权留痕作为 P3 候选，目标仍可通过可信 steer 更新。
- Resources：workspace、进程树、browser context/profile、共享桌面与 Wiki writer 的 owner、互斥、期限、停止与失联处理；跨 Session 并行可能竞争同一资源，不能只依赖 Session 内串行。
- Long operation：等待、进度、取消反馈和未知结果怎样回到 T1；如采用后台 job，另补 handle、完成事件、跨 Turn/重启归属及清理，不能只添加一个超时阈值。

关闭产物：逐 Tool 契约表、身份/授权→可用资源表、资源生命周期与失败矩阵。T1 负责 intent/Result 的执行顺序与 commit owner；T3 封装真实执行和资源回收；T4 提供持久提交能力。

<a id="topic-state"></a>

### T4 — 持久状态与数据生命周期

沿用唯一 append-only `session_events`、SQLite WAL/FULL、asset-before-reference、无持久 Snapshot、按需导出与手动 GC。

待讨论：event schema/seq/幂等键/事务和版本迁移；执行 writer 与 ingress 接纳如何协调；Run/lease fencing、迟到事件和损坏尾部如何处理；Conversation 从 compaction 重建时，预算、workspace、授权关联和 delivery 等运行事实怎样从必要事件确定性 fold；assets 的地址、访问、共享引用与 GC，尤其导出/备份期间的保留、压缩后的引用关系及缺失/损坏报告；SessionCatalog 查询、`trace/v1` 与 `aift/v1` 的截止 seq、manifest/JSONL/资产包含和 Tool 配对、多 Session 部分导出失败；一致备份/恢复与磁盘满处理。

关闭产物：字段级 schema、状态投影与重建规则、提交/崩溃窗口矩阵、查询/导出/备份格式及引用完整性验证。T4 持久化与重建事实，不自行决定恢复后启动任务；起跑条件归 T1，外部投递接管归 T5。进程存活检查提供运行证据，不把数据库的旧 running 字段当成进程仍在执行。

<a id="topic-channels"></a>

### T5 — 渠道与交互交付

沿用 Feishu 私聊/群/Thread/文档评论入口、当前严格 @ 默认、原入口回复和 stable `final_message_id`。最终状态与结果依据已提交事实；未提交的流式增量仅作临时预览。投递重试不重跑模型或工具。

待讨论：各入口身份、去重、延迟/乱序与路由；自由文本回答/steer/控制指令的明确交互；重复/过期回答和 timeout UX；文档 block 编辑、回读、评论竞态与部分成功；状态卡/工具轨迹/长文/限流；流式预览与持久 final_message_id 的渠道 ID 映射、取消/部分输出后的展示；投递回执丢失、幂等查询、持久接管与 writer 释放的先后关系，接管后的消息排序和永久失败如何关闭投递责任。

关闭产物：真实渠道的输入/输出交互表、文档操作契约、delivery 状态/重试表和验收场景。工具形式的飞书操作沿 T3 统一执行；渠道不增加第二套 AgentLoop。何时应通知由 T7 决定，怎样可靠投递由 T5 决定。

<a id="topic-knowledge"></a>

### T6 — 知识与行为资产

沿用 [AgentWiki](../design/agentwiki.md) 的 grep→read、维护生成 INDEX、draft_only/curate/behavior、Skill 按需读取、AGENTS 显式刷新与不自动提升。M3 消费方式不重新选型。

待讨论：经授权的修改如何经过结构/语义验证、并发 writer、Git 同步/冲突、发布和失败恢复；覆盖已有 dirty tree、离线与部分成功，明确文件写入后可检索、事件提交、Git commit 和远端发布各自的事实及失败返回，避免一边成功却宣称全部发布；动态 Skill/index 的更新、删除、损坏或不兼容如何处理；Coding Skill 怎样给出任务相关的验证与交付流程。

关闭产物：授权→修改→验证→提交/发布→生效的流程与失败表，以及 Skill 加载/更新兼容契约。T3 管实际授权执行与资源锁，T4 管事实记录，T2 管版本进入请求的时点；T6 负责知识与行为资产的发布语义，不另建 Memory 服务。

<a id="topic-proactive"></a>

### T7 — 主动性与注意力

既有目标是减少用户的上下文整理与跟进负担。需要具体设计内部整理、事实更新、任务阶段识别、用户蒸馏、触发与打扰规则；这些已接受的目标不能因外部候选暂缓而被删掉。

待讨论：哪些事件/变化值得关注；授权内可做哪些整理和验证；何时仅观察、何时执行；通知去重/合并、静默、决策请求与停止条件；用户取消后是否以及何时可再唤醒。用 trigger/goal/verification/stopping/memory 五要素检查每个场景，不预选新 DSL、任务库或 scheduler。

同一 topic 内单独评估新增候选：持久订阅与自动唤醒、独立任务并行与 Router/Worker、语义 Watchdog。若采用，必须解释任务归属、授权继承、成本/注意力收益，以及与 T1/T3/T4/T5 的接口；它们不由“有事件”“能恢复”或“有健康检查”自动推出。observe-first 与注意力策略对应 P4；结构化验证通过后是否启动执行仍取决于授权。

关闭产物：真实场景表、允许行为与触发规则、通知/求助策略，以及候选逐项采用或暂缓的理由。部署存活/失联检测归 T8，不由监督 Agent 自述代替。

<a id="topic-engineering"></a>

### T8 — 工程运行与全功能验收

沿用单容器部署、完整能力交付和设计/实现/测试/部署证据分开。实施切片只调整顺序。

待讨论：Rust/Python 与依赖/接口/目录；配置和 secret 使用路径；Bot/browser/desktop/子进程监督；健康、故障诊断和资源指标；升级/迁移/回滚；CI、真实 Provider 与飞书 smoke；新实现同既有部署的并行或替代关系，是否迁移历史需明确范围。进程健康检测属于 P5 的工程部分，业务偏航判断仍归 T7 候选。

关闭产物：可运行工程方案、部署/升级/恢复流程，以及覆盖全部已确认能力的验收矩阵。每个验收项包含正常、失败、并发或恢复场景、可检查的证据与通过条件。这里的系统验收区别于 T1 中 Agent 为用户任务选择的具体检查；不能用单元测试或一个 smoke 把全部能力标为完成。

### Cross-topic contracts and proposal ownership

| 容易重复讨论的问题 | 主负责与接口约定 |
|---|---|
| 模型错误、重试和 ReAct 出口 | T2 规范化 Provider 事实与错误；T1 拥有 attempt/continuation、重试执行与终止决策；T4 保证事实提交 |
| 输入接纳、回答与停止 | T5 解析入口身份与交互；T1 决定输入归属/注入/控制；T4 保证接纳持久性，T3 接收实际资源取消 |
| 结果完成与最终投递 | T1 形成证据支持的结果及 finalization；T4 存事实；T5 负责接管/投递/回执。投递闭合，或持久 delivery owner 确认接管并保证消息顺序后，由 SessionManager 释放 writer |
| 授权、Wiki 发布与动态加载 | T3 定义并执行有效权限；T6 定义发布/验证；T4 保存关联事实；T2 按已有 revision 规则加载 |
| 大输出、截图与历史恢复 | T3 产出完整结果；T4 持久化、保留并提供访问；T2 组装预览和恢复入口；T5 按渠道呈现 |
| 恢复、健康与再次启动 | T8 发现进程失联；T4 重建事实；T1 执行恢复/起跑规则；T7 仅在明确采用主动触发后提供新的合法触发 |

P1（验证驱动交付）主归 T1，任务方法由 T6 承载；P2（无进展与软成本）主归 T1，usage 来自 T2、记录在 T4；P3（授权来源）主归 T3；P4（主动性/注意力）主归 T7；P5 主归 T3 的长操作响应，其中进程健康诊断部分交 T8。每项仍保持 proposed，不能因为分配了负责人就视为采纳。

### Discussion sequence and closure packet

下一轮先展开 **T1**，用 T3 的代表性工具和 T2 的响应样例联合检查；随后关闭 T2/T3 的剩余 M5 项。M5 后先用 T7 明确主动性场景与候选范围，再收敛 T3 的 M6 权限/资源和 T6 的写入需求；T4/T5/T6 共同关闭 M7 持久化、发布与投递接口；最后以 T8 完成 M8/M9。T8 的生态约束可提前提供输入，最终语言/部署决定仍需前述契约支持。

每次只展开一个主 topic，交付同一份简短关闭材料：**已定输入 → 待定问题与建议 → Interface/唯一 owner → 正常与失败场景 → 验证证据与关闭条件**。已确认决定写回对应 design 文档；本页只维护问题归属、顺序和关闭要求，不复制完整协议。

## Stage close criteria

### M4 — AgentLoop

Close only when these walks are all deterministic:

1. ordinary text response;
2. one and multiple Tool calls;
3. steer during model streaming and during Tool execution;
4. compaction before and during a Tool-driven task;
5. WaitingRequest and its answer;
6. `/stop` at every state and a later new Turn;
7. model, Tool, persistence, and process failures.

The output must define where Trajectory events and Session writes occur in each path.

The ReAct follow-up also needs a model-response-to-runtime-decision table: mixed text/calls, partial or malformed calls, empty output, truncation, errors, Provider termination, correlated Observations, and evidence-bounded final delivery. Existing state transitions alone do not close these cases.

### M5 — Context and compaction

Close only when every model request can be explained by a deterministic assembly rule:

- stable prefix, Skill/Wiki revisions, Session history, WorkingContext, and current input have a defined order;
- within a compaction boundary and fixed revisions, provider-visible content is immutable and append-only, including WorkingContext versions and invalidation markers;
- model, Skill, Wiki, and `AGENTS.md` updates have explicit effective boundaries;
- compaction has a defined trigger, Agent-generated task summary, validation, failure path, recovery, and new cache boundary;
- budget changes take effect at a defined point.

### M6 — Trust and resources

Close only when every execution resource has an owner and lifecycle:

- actor permissions are distinguished from process credentials;
- shell, browser, desktop, Git workspace, and Wiki writes have explicit access rules;
- every shared resource is Session-private, globally shared with a lock, or explicitly exclusive;
- cancellation and process failure release or mark every resource without pretending side effects were undone.

### M7 — Data and channels

Close only when:

- `session_events` is the sole authority for execution history; Session projections and Conversation views are derived from the latest compaction event and subsequent events, with no persistent Snapshot to keep synchronized;
- trace and AIFT exports have stable schemas and preserve Tool Call/Result correlation;
- Feishu IM, documents, comments, and cards have concrete acceptance scenarios, including duplicate and delayed events;
- backup, restore, and GC preserve referential consistency between events and assets.

### M8 — Engineering

Close only when a fresh checkout can be built, tested, and run by a documented path. Language choice must account for AgentLoop, Feishu, SQLite, BrowserUse, ComputerUse, external Tool processes, and maintenance cost—not just benchmark performance.

### M9 — Final review

Close only when:

- all feature rows have a value, an approach, and either a closed contract or an explicitly deferred reason;
- the seven M4 scenarios plus Feishu document and Browser/Computer scenarios can be walked through without inventing behavior;
- ADR, CONTEXT, README, feature worklist, and this roadmap agree;
- remaining open topics are genuinely outside the implementation baseline;
- the implementation phases have verification and stop conditions.

All accepted capabilities remain covered by the implementation phases. Only unaccepted additions may be parked without a delivery commitment; staging must not silently drop agreed scope. Topic organization is complete only when all G0–G13 entries have a primary owner and their cross-topic contracts have explicit participants.

## Discussion protocol for every feature

Use the same short loop:

1. **Value** — what user outcome requires this feature? Remove it if there is no concrete outcome.
2. **Scenarios** — name the success path and the important failure/concurrent path.
3. **Approach** — choose the smallest mechanism that handles those scenarios.
4. **Verification** — state exactly how the feature would be demonstrated or tested.
5. **Record** — update the feature worklist and any affected ADR/CONTEXT entry, then commit.

A feature is not closed because its name or happy path is agreed. It closes when its behavior, failure handling, ownership, and verification are all explicit.

## How to handle divergence

When a useful but out-of-stage idea appears:

1. Record it in the parking lot below with the reason and the condition that would make it worth reopening.
2. Do not spend the current stage designing it.
3. Return to the current stage's unresolved question in the same reply.
4. If it changes an accepted decision, explicitly say so and create a superseding ADR instead of silently editing history.

## Parking lot

| Idea | Why it is parked | Reopen when |
|---|---|---|
| Agent-defined Hooks | Trajectory already covers recording and audit; no current scenario requires automatically changing subsequent behavior | A concrete deterministic action is required that cannot be left to the next model decision; then design activation, recursion, timeout, and failure semantics afresh |
| Read-only `/btw` side questions | An IM bot can answer progress through the main Session; a separate read-only completion adds concurrency and prompt complexity without a concrete use case | A recurring scenario needs side questions that must not affect the main task |
| Automatic RSI or automatic Skill promotion | Trajectory and Skills are useful without an automatic self-modification loop | There is a reviewed offline evaluation and approval policy |
| Cross-entry Session resume | One entry per Session is simpler and covers the current workflow | A real user repeatedly needs to continue the same work in another entry |
| Vector/semantic Wiki index | M3 selected bounded grep/read without a semantic index | Concrete retrieval failures demonstrate that aliases and keyword retrieval are insufficient |
| Generic EventBus and event replay | There is only the active Feishu renderer and direct authoritative writes | A second real subscriber or remote UI requires it |
| Multiple virtual desktops or remote devices | One container and one shared desktop are enough for the baseline | Parallel GUI work becomes a measured requirement |
| External Kimi Code route or coding mode | One native AgentLoop gives complete Trajectory and less lifecycle duplication | A requirement for native external Session compatibility is explicitly reinstated |
| Automatic Wiki promotion from Trajectory | Raw execution history is not curated long-term knowledge | A user-selected curation workflow exists |

## Status maintenance

At every stage close or meaningful decision:

1. Update the affected feature row and ADR/CONTEXT entries.
2. Update this roadmap's stage status and parking lot.
3. Check links and `git diff --check`.
4. Commit and push so the next discussion starts from the repository rather than chat memory.

The roadmap does not authorize implementation. Implementation starts only after M9 and explicit user confirmation.
