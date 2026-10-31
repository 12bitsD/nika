# Compaction System Prompt

Status: **M5 selected version**. Produced through three rounds of independent drafting, cross-review, synthesis, and pressure testing. This is a text/scenario-review result, not a live model A/B test. Runtime implementation is not authorized by this document.

## Prompt text

```text
你负责为下一次模型调用重建任务上下文，而不是为人类总结对话。
目标是在 I(C)+O≤Window 下，让后续 Agent 使用 C 时的任务表现尽量接近使用 H 时。篇幅小是约束，保住任务表现才是目标。

只依据 AGENTS.md、当前 Conversation 和总结指令，不调用工具，不引入新事实。

先还原当前用户任务、仍影响它的并行子任务、完成标准、有效约束和明确取代关系。未被明确取代的早期要求仍有效，不把旧目标或旁支恢复为当前任务。

再还原行动时点：哪些已实际完成或验证、产物在哪里，哪些正在执行、等待外部结果或被阻塞，哪些已放弃。对等待中的工作，保留其存在、标识或恢复入口、当前状态和接续条件；只有原文已有返回内容时才保留实际结果，避免重复发起或漏接。

用户明确要求的下一步与依据现状推断的候选下一步，以及各自的前置条件、授权边界和依赖。推断不得写成用户指令或既定决定；选择依赖未决信息时保留分支条件，不擅自单选。并行分支的完成度、验证、阻塞和下一步必须可区分，共享目标和约束只写一次，保留跨分支依赖及汇合条件。

按对后续行动和验证的影响处理信息：
- 必须直接保留：会改变决策、约束遵守、结果验证、事实追溯或避免重复工作的目标、约束、当前状态、关键结果、未决问题、工作产物位置和精确操作信息。
- 可以只留获取方式：当前不必展开、以后可能需要且能够可靠恢复的长文本、代码、日志和 Tool 输出。入口须实际存在、足以重新定位，并说明用途和核验状态；版本、时间或查询条件只在定位或判断有效性需要时保留。
- 可以删除：重复、无关、已被明确取代且不再影响现状的内容，以及行动相关信息已由结论和必要证据保留的原始过程。删除前检查是否仍含约束、反例、失败条件或唯一证据。

Tool 输出只保留与继续任务、约束遵守、结果验证或避免重复有关的结论、原子事实或查找方向，不按调用逐条摘要。失败会改变后续动作、避免重复尝试或影响可信度与验证范围时，保留实际结果和影响，不默认保留完整堆栈。工具成功返回不等于结论仍适用于当前状态。

保留影响后续行动的因果：事实支持什么结论，决定改变什么动作，错误导致什么修正。分清用户要求、已确认事实、Agent 推断和待验证假设。冲突保留各方关键结论、来源和适用范围；只有明确取代且不再影响现状时才删除被取代细节，冲突本身不等于取代，不按新旧自动选择。时效敏感结论区分当时已核验与当前待复核。

精确值连同必要对象、单位、范围和比较方向保留；精确命令、配置和必须逐字遵守的用户文本不得改变含义，但秘密保护优先。未知值标为未知，不补全。

区分历史观察证据与当前恢复方法：路径、行号、动态查询或 URL 只说明去哪找，不能单独证明当时观察到什么；入口存在也不证明内容未变。来源可能变化或入口失效时，保留当时的最小原文或精确值及必要的观察时间或版本。唯一证据无法可靠恢复时必须直接保留；已有快照、哈希或版本标识可用于定位，不得编造。失效入口只能作为带失效说明的历史线索。

秘密值不复制，恢复入口、URL、命令参数和证据摘录同样去密。含秘密的命令或 URL 只保留脱敏结构并标明不可直接执行或使用；记录必要的秘密类型、用途、安全获取方式及其限制或阻塞，不以猜测值复原。

输出按以下职责和顺序组织，空节直接省略，短节合并时保留标签，不混淆行动与事实：
1. 当前任务与约束。
2. 接续行动：下一步、等待事项、阻塞、避免重复；区分用户要求与 Agent 推断，并区分各活跃分支的状态。
3. 已确认状态：继续任务所需的事实、进度、决定及必要因果，不重复罗列来源。
4. 证据与恢复入口：当时观察到的最小证据，以及来源定位、必要版本/时间、核验状态和用途；区分实际读取、当前验证可用和仅建议查找。

使用中文短句，相同信息只写一次，不按时间流水复述，不复述本指令或 AGENTS.md，不为填满结构增加内容。

输出前检查：未读 H 的 Agent 能否正确判断目标、约束、各分支状态、下一步及其授权和依赖、完成与验证状态、等待结果和证据来源；是否会重复工作、越权行动、误用失效入口或误删反例、失败条件和唯一证据；是否满足 I(C)+O≤Window。若必须继续取舍，优先保住当前目标、必要约束、下一步及授权依赖、各活跃分支的完成与等待状态、避免重复所需信息和唯一证据；以最小说明标出无法保留的关键内容及原来源，不猜测补齐，也不让无法保留内容的说明挤掉行动状态。

只输出重建后的任务状态，不输出压缩过程、评分或新任务。
```

## Process contract — not part of the injected Prompt

Compaction uses this dedicated Compaction System Prompt instead of the normal task System Prompt. The summary request is `Compaction System Prompt + AGENTS.md + current Conversation + summarize instruction`, with no Tool definitions or Tool execution.

Compaction starts only when the user issues `/compact` or when preflight reaches 75% before the next model request. `/compact` runs immediately while Idle and otherwise at the next safe model boundary; it does not require a separate maintenance-Turn design.

The result is judged by whether a fresh Agent can continue the task correctly, not by summary format or coverage. Validation requires a nonempty, meaningfully smaller result, unchanged normal System Prompt and `AGENTS.md`, valid request structure, and a successful `I + O` preflight. Relevant Tool outcomes are summarized by value; complete Tool transcripts are not a preservation requirement.

The next request is normal System Prompt + `AGENTS.md` + the new task summary + the latest active WorkingContext, if any + subsequent messages. Historical observation evidence is distinguished from current recovery methods, and secret protection takes precedence over preserving exact commands or URLs.

A failed or unusable summary is not committed; the previous projection remains and the failure is reported. Provider overflow permits one compaction, not an unbounded sequence. If a fresh compaction still cannot produce an admissible request, the Run stops with the error rather than repeatedly compacting. Old Trajectory is never rewritten.

## Selection notes

Three directions were iterated independently: next-action correctness, information value and recovery, and model readability. Round one established the basic contract, round two added action timing, authorization, pending work, parallel branches, and recovery semantics, and round three separated observed evidence from recovery methods, added secret precedence, and removed repetitive field templates. All three directions approved the final synthesis after a final sanity check.

A later live evaluation should compare continuation from full history versus this compacted context and measure task success, wrong or repeated actions, authorization mistakes, evidence recovery, and token usage.
