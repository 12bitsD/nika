# Nika 新架构开发接手上下文

核验日期：2026-11-01（Asia/Shanghai）。基线：[`main@57713e41124e2b085fc781c993cfebeb7156fc6a`](https://github.com/12bitsD/nika/commit/57713e41124e2b085fc781c993cfebeb7156fc6a)。本文是本轮接手分析的日期快照；持续维护的讨论顺序仍以 [roadmap](discussion-roadmap.md) 为准，行为契约仍在各 design 文档。下文“建议”不是新增架构决定。

**2026-11-02 补充：**用户提供 Agent Loop / DSH / Super-agent 综述后，新增[能力分类与收敛分析](agent-loop-capability-review.md)，登记 ReAct 执行协议 G0 和 G0–G13 缺口索引，并补充一手研究证据。下文保留原基线核验范围；M4 原状态机/生命周期基线与 ReAct 新关闭项分别记录，§5 的旧句漂移已按既有决定同步。这些均为设计文档工作，没有 runtime 实现或部署结果。

随后按用户要求，将未定问题统一归入 roadmap 的 [T1–T8 讨论 topic](discussion-roadmap.md#discussion-topics)。后续从这个入口逐个讨论模块职责、接口与关闭场景；本文保持接手快照，不另维护 topic 状态。

## 1. 当前接手的是什么

这是围绕**单一原生 AgentLoop** 重新设计的个人 Bot。聊天和 coding 由同一套循环、模型接口和工具执行；coding 的工作方法由 Skill 提供。把执行放在自身运行时中，可以统一生命周期、取消、上下文和 Trajectory，代价是需要自行实现并验证这些能力。

该基线明确移除了外部 Coding Harness、双 Engine、coding mode 和任务卡系统。旧 Yomi/Nika 路线只按需用于飞书行为等研究参照；不能继承其 Provider Session 绑定、任务 FIFO、停止后恢复卡片队列等产品契约。[ADR-0002](../adr/0002-single-agent-loop.md) 已取代 ADR-0001；这不构成旧部署已迁移或下线的证据。

本轮已核实 GitHub 的文件树、提交、分支、Issues、PR、commit comments 和 Actions：

- 基线有 13 个提交，1 个分支；12 个受跟踪文件为 11 篇 Markdown 和 `.gitignore`。
- 没有运行时代码、依赖清单、测试、Dockerfile 或 CI workflow；Issues/PR/commit comments/Actions runs 均为 0，Discussions 未启用。
- 最新提交为 2026-10-31 22:45 的软预算设计。当前可交接资产是契约、Prompt 和分析材料，尚无运行时实现或端到端测试证据。
- System Prompt 的 4.6/5 和 Compaction Prompt 的三轮优化都是文字/场景评审，不是 live model A/B 或成功率。见 [选型说明](../design/system-prompt.md#selection-notes--not-part-of-the-injected-prompt) 与 [压缩 Prompt](../design/compaction-prompt.md)。

## 2. 用一条用户链路理解架构

```text
飞书私聊 / Thread / 文档评论
  → 路由到 Session
  → SessionManager 持单 writer lease，记录输入并创建 Turn/Run
  → ContextBuilder 从已提交事件与运行配置组装请求、检查容量
  → AgentLoop：模型 → 串行 Tool → 已提交结果 → 模型……
  → 必要时 WaitingRequest / Compactor；/stop 进入取消收尾
  → 保存最终事实 → 释放执行资源 → 投递同一 final_message_id
  → 投递闭合或持久投递方接管 → 释放 Session writer

留下：Session 的 append-only Trajectory 与大结果的 assets。
Wiki：独立、经授权维护的长期知识；不从 Trajectory 自动提升。
```

一次输入怎样处理、执行结果怎样留下、如何继续对话，都由这一条链路解释。AgentLoop 是按需执行过程；Session 才有持久身份。`Stopped` 不是用户已收到结果的证明。

## 3. 必须携带的最小契约

| 主题 | 已确认口径 | 权威入口 |
|---|---|---|
| 产品与运行环境 | 一套 Loop 同时处理 chat/coding；Bot、浏览器、虚拟桌面同容器；Feishu 为主入口 | [ADR §1–3](../adr/0002-single-agent-loop.md) |
| Session / Turn / Run | 一个入口映射一个 Session；Turn 是输入到收尾，Run 是具体执行尝试。model retry 不创建新 Run；旧 Run 迟到事件不能污染新 Run | [M4 §1–2](../design/agent-loop.md#2-identities)、[术语](../../CONTEXT.md) |
| 普通输入 | Idle 时开新 Turn；活跃时全部为 steer，按序在安全模型边界注入。final 已提交后留给下一 Turn；没有独立任务 FIFO 或 `/queue` | [M4 §6](../design/agent-loop.md#6-steer-and-input-buffer) |
| 正常结束前的新输入 | 2026-11-03 确认：完整无 Tool 响应先作最终回复候选；已有 pending steer 则继续同 Turn/Run。输入接纳与 final commit 保持一致先后顺序；提交后输入归下一 Turn | [M4 §6.1](../design/agent-loop.md#normal-turn-completion) |
| 工具与副作用 | 首版按模型给出的顺序串行执行；先持久化 intent，再执行，再提交 Result。大输出先持久化 asset 再引用；取消和重启不自动重放历史 Tool | [M4 §5](../design/agent-loop.md#5-tool-calls) |
| 等待与停止 | WaitingRequest 由 runtime 显式创建，最多一个；回答恢复原 request，须校验身份/有效性。普通文字提问不创建等待，回复按 final commit 前后的 steer 规则处理。`/stop` 取消当轮及子进程，保留事实与未注入 steer | [M4 §8–10](../design/agent-loop.md#8-waitingrequest) |
| 最终交付 | `try/finally` 负责必要收尾；执行资源与 Session writer 分开释放。投递失败只重投相同 final_message_id，不重跑模型 | [M4 §4](../design/agent-loop.md#4-durable-event-and-delivery-order) |
| 事实与恢复 | session_events 是唯一执行历史权威；Conversation 是投影，无另一套持久 Snapshot。SQLite WAL + synchronous=FULL；大资产独立存储 | [ADR §5/8](../adr/0002-single-agent-loop.md) |
| 模型上下文 | tools[] + system + messages[]；同 compaction boundary、固定 revisions 下，旧 provider-visible 内容不变，只追加。不同模型/Provider 的映射与缓存策略独立处理 | [ContextBuilder](../design/context-builder.md) |
| 规则与知识 | runtime System Prompt、AgentWiki AGENTS.md、Skill、Wiki 分开。人格初次快照只经用户明确要求刷新；Skill/Wiki 使用时读当前版本，结果追加 | [M5 规则](../design/context-builder.md#system-prompt-agentsmd-and-tools)、[AgentWiki](../design/agentwiki.md) |
| WorkingContext | 每 Session 一个 active slot；run/session 是寿命，不是两个槽。set/clear/expire 只追加，幂等不追加；Tool Result/state → reminder → steer。user-level 提醒不授予权限 | [WorkingContext](../design/context-builder.md#workingcontext-is-append-versioned) |
| 压缩与容量 | 每次模型调用前完整计数；缺 usage 不当零。输入 ≥75% 或 I+O 超 Provider 容量时进入 Compactor；也支持 /compact。专用 Prompt、无 Tool 执行，成功才追加 summary；新上下文保留最新 active WorkingContext | [Preflight](../design/context-builder.md#usage-and-preflight)、[Compaction Prompt](../design/compaction-prompt.md) |
| 预算 | lite/pro/promax，默认 pro；调用数/时间是软指导，over_budget 不强停。run 级变更影响当前 Run 后续操作，session 级变更影响未来默认；在途操作不改 | [Budget](../design/context-builder.md#budget-profiles-and-change-boundaries) |
| Wiki 写入 | grep → read；INDEX 由维护生成，不是必读入口。默认 draft_only；普通 active 知识用 curate，AGENTS/Skill 用独立 behavior 授权。来源证据不等于写授权 | [AgentWiki](../design/agentwiki.md) |

不带入首版：通用 EventBus、远端事件重放、外部 harness、远程设备桥、任务卡系统、agent-defined Hooks、/btw、conversation rewind、自动 RSI、自动 Wiki promotion。状态/交互卡仍在飞书功能范围内，不等于恢复旧任务卡系统。

## 4. 讨论已走到哪

| 阶段 | 仓库状态 | 接手含义 |
|---|---|---|
| M1/M2 研究 | Done | 复用结论；外部研究出处仍需按实际实现依赖补定位 |
| M3 AgentWiki | Done | 不再重开消费模式；Git 同步、并发 writer 归 M6/M7 |
| M4 AgentLoop | 原状态机/生命周期基线已记录；ReAct follow-up Open | 已有执行/取消/收尾顺序与故障矩阵；2026-11-02 补充模型响应→行动→观察→继续/结束的 [G0 协议关闭项](agent-loop-capability-review.md#react-execution-protocol-gap) |
| M5 Context/cache/compaction | In progress | 当前明确剩余项是各 Tool schema/description；已有机制的可执行边界也须在相应阶段补齐 |
| Proactive 专题 | M5 后讨论 | 价值已接受，触发、任务阶段识别、面向用户的蒸馏、授权与打断策略未设计；WorkingContext 不能替代它 |
| M6 资源与信任 | Pending | actor/进程凭证、workspace、Wiki writer、GUI 锁、故障清理 |
| M7 数据与渠道 | Pending | event/projection/asset/export schema，Feishu 去重/投递，备份恢复/GC |
| M8 工程 | Pending | Rust/Python 尚未选择；依赖、目录、进程监督、容器与 CI |
| M9 收口 | Pending | 跨文档一致，端到端场景可推演，实施分期有验证与停止条件 |

10-30/31 的提交主要闭合了 Wiki 授权/检索、System Prompt、WorkingContext、cache、内容访问、usage preflight、compaction prompt 与 soft budget。应从这些已经收敛的决定继续，而非重新讨论所有基础机制。

Roadmap 的现行流程是 M9 收口并获得明确实现确认后开始 runtime。本文完成接手梳理，不把未来开发目标当作这些设计缺口已经解决。

## 5. 已发现的文档漂移

以下坐标均相对 57713e4，保留当时发现的旧句与修正依据；2026-11-02 已在对应文档同步。该表是历史问题记录，当前契约以链接的 design 文档为准。

| 问题 | 证据 | 建议处理 |
|---|---|---|
| 硬预算与软预算冲突 | agent-loop.md:106 写 budget_exceeded 停止；context-builder.md:114–128、ADR-0002:309–313 明确软预算继续 | 以最新明确软预算决定同步 M4；区分 Provider 容量、单次超时等真实硬限制 |
| 压缩触发不一致 | context-builder.md:94 / CONTEXT.md:35 有 I+O 容量分支；agent-loop.md:142、context-builder.md:102、compaction-prompt.md:51 却写 only /compact 或75% | 全部统一触发谓词，覆盖 I<75% 但输出 reserve 导致超限 |
| 已定串行仍列 Open | agent-loop.md:99/110 已定首版串行；feature-worklist.md:28 仍问 serial vs parallel | 串行关闭，资源归属仍交 M6；不据旧 worklist 重新设计并发 |
| steer 边界泛列待定 | agent-loop.md:119–126 已给 streaming/Tool/retry/compaction/final 各边界；feature-worklist.md:12 仍问 exact merge point | 同步已经确定的部分；只留下等待回答、持久恢复等具体缺口 |
| M3/M5 旧待办未收敛 | ADR-0002:17/359 仍称 Wiki 消费待深挖，:356/361 泛列 Prompt/压缩；roadmap、feature-worklist 和专题文档已有闭合结论 | 维护开放问题列表，保留原始决定历史，避免重复研究 |

初次接手时仅登记差异；2026-11-02 已按既有明确决定同步 AgentLoop、ContextBuilder、Compaction Prompt 的过程契约、ADR 与 worklist/roadmap。Compaction Prompt 的注入正文未改。此次一致性修正没有采用新的硬预算、工具并行或任务队列。

## 6. 真正需要补齐的实现前问题

| 归属 | 必须明确什么 | 为什么会影响第一版 |
|---|---|---|
| M4 follow-up / ReAct | 响应分类、完整可执行调用、Observation 配对、继续/退出、Provider 必需回传字段；见 [G0](agent-loop-capability-review.md#react-execution-protocol-gap) | 状态机不能独自说明截断调用、空响应、混合输出和业务验收；需与 Tool Catalog 联合收敛 |
| M5 Tool 契约 | 每个 Tool 的入参、输出、错误、取消/重试语义；runtime 注入哪些 Session/workspace/授权字段 | 目前是工具名称和用途，尚不是可实现的完整 Catalog。先做契约表，不把 runtime 状态重新交模型填写 |
| M4→M7 输入恢复 | WaitingRequest 存在时如何区分回答与 steer；stop 后 pending 输入的持久范围与下一 Turn 起跑条件 | 防止重定向被当授权，或停止后保留输入立即自动执行 |
| M5→M7 压缩恢复 | summary 请求自身的容量；“meaningfully smaller”的判定；Tool Call/Result 配对；运行状态独立 fold 的起点 | Conversation 可从 compaction 开始，但预算、workspace、delivery 等不能只靠自然语言 summary 恢复 |
| M6 权限与资源 | actor 权限与进程凭证分开；Shell/文件写入不能绕过 Wiki 验证；每个 workspace/profile/GUI/Wiki writer 的所有者、锁、取消和崩溃清理 | 当前 capability 丰富，所有权协议缺失会让 Session 互相干扰或破坏已定写入边界 |
| M7 事件与投递 | event 字段、seq、幂等键、事务边界、lease/fence、资产引用；模型重试/新 steer 的 logical call 身份；final delivery 接管/重复与未知回执 | “事件唯一权威”须在杀进程与重复外部事件时成立，不能只实现顺畅路径 |
| M7 Feishu/运维 | 文档评论路由、重复/延迟消息、限流与长文；备份资产一致性、恢复与 GC 顺序 | 原入口交付和历史可恢复需要独立验收 |
| M8 工程 | 根据 Feishu、SQLite、浏览器/桌面与子进程生态选 Rust/Python；确定容器与 CI | 暂无足够已确认条件直接选语言或脚手架 |

初次接手时研究证据缺少最小来源表：roadmap 将 M1/M2 标为 Done，但未附对应 primary-source notes 或外部代码版本坐标。2026-11-02 新增的 [DSH / Super-agent 核验](../research/2026-11-02-dsh-primary-sources.md)与 [Loop Specification / 社区证据](../research/2026-11-02-loop-evidence-notes.md)只覆盖本次综述，未补齐原 M1/M2 的全部依据。ADR 要求复用的 yomi 文档回读/评论竞态处理仍需具体定位；按实际实现行为补 `结论 → 官方文档/源码版本 → 适用边界 → 验证方式` 即可。

## 7. 接手后的推进顺序与第一个开发闭环（建议）

**2026-11-02 用户补充的交付与设计要求：**所有已确认能力都需要实现；整体架构保持简单，每项能力的行为细节打磨完整。分阶段只安排实现和验收顺序，不缩减最终交付范围。AgentLoop 内部也需要合理抽象与拆分，具体职责和状态/提交归属的工作方案已补到 [AgentLoop 内部结构](../design/agent-loop.md#12-internal-structure-and-module-interfaces)；该拆分尚未实现，模块名称和语言相关布局仍待工程设计。

已确认决定造成的文档漂移已在对应文档同步。下一步联合收敛 G0 ReAct 协议与 M5 Tool 契约，随后按 roadmap 收敛 Proactive 与 M6，进入 M7 事件/渠道协议，再确定 M8 工程方案；M9 用端到端场景检查各层是否无需临时发明行为。综述带来的新增能力候选单列在[收敛分析](agent-loop-capability-review.md)，不自动进入已确认交付范围。

**建议首个实现切片：一个 Session、一个真实模型、一个本地文件/命令工具、一个飞书入口，跑通执行与恢复闭环。** 先用内存 Provider/假投递端测试确定性语义，再补真实模型与飞书 smoke；两类证据分开记录。语言和接口细节由前述阶段决定。

验收至少覆盖：

1. 输入 → 持久化 → 模型 → Tool → 结果提交 → 原入口交付；投递重试不重复模型或工具副作用。
2. streaming、Tool、retry backoff、compaction、final commit 后到达的 steer，保持顺序、身份与正确 Turn 归属。
3. WaitingRequest 的有效回答、重复回答、过期回答；每种 AgentState 的 stop；旧 Run 迟到事件不进入新 Run。
4. 在 intent、工具副作用、Result commit、final commit、delivery receipt 各窗口中断进程；恢复事实，不自动重放工具。
5. 两次普通请求旧前缀不变；无输出无新输入的 retry 字节一致；WorkingContext 与预算变更的顺序、幂等、scope 正确。
6. 精确覆盖75%两侧、I+O 超限但 I<75%、缺 usage、固定内容过大、压缩无进展与二次 overflow；另外做压缩前后真实续作对照。

这一切片通过只证明核心执行链。Browser/Computer、AgentWiki 写入、文档评论、批量导出、备份恢复和 GC 仍需各自验收，不能一起标为完成。

## 8. 后续 Agent 最短阅读与续接提示

先读本文、[roadmap](discussion-roadmap.md) 和 [CONTEXT](../../CONTEXT.md)；评审能力与剩余缺口读[收敛分析](agent-loop-capability-review.md)。进入实现域时只展开对应文件：执行读 [agent-loop](../design/agent-loop.md)，上下文读 [context-builder](../design/context-builder.md) 与两个 Prompt，知识读 [agentwiki](../design/agentwiki.md)。跨域查 [ADR-0002](../adr/0002-single-agent-loop.md)；任务清单查 [feature-worklist](feature-worklist.md)。ADR-0001 只为追溯被取代方案而读。

> 工作目标是接手 12bitsD/nika 的单 AgentLoop 新架构。先核对当前 main 与本文基线及本地工作稿的差异；不要把旧 Yomi 任务卡需求带进来。当前没有 runtime，实现前仍需完成 roadmap 的剩余契约与收口。下一步联合收敛 G0 ReAct 协议与 M5 Tool schemas，再推进 Proactive/M6–M9。以 session_events 为事实源，把上下文组装、工具副作用、取消、恢复和最终投递的边界做成可验证契约；新增能力候选先明确取舍，任何实现或实测结果都分别记录，不把设计闭合说成能力已上线。
