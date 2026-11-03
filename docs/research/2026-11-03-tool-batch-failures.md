# 同批工具调用：前项失败后是否继续

核验日期：2026-11-03。本文回应 T1/T3 的未决问题：一次模型响应提出多个 Tool Call，某项普通失败后，尚未执行的调用是否继续。**这里只记录源码事实和待确认建议，没有改变 Nika 的执行策略。** 已确认的“普通 Tool 错误不自动结束 Turn”见 [AgentLoop §5.1](../design/agent-loop.md#ordinary-tool-errors)。

范围：静态读取固定版本的源码和测试，未运行外部代码或测试。Hermes 为 `NousResearch/hermes-agent@d7572ceda754b888216c212691e1b2301ebe0359`；Yomi 比较 fork `12bitsD/yomi@7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97` 与 upstream `Crescent617/yomi@2193746a4a2db2c17a62c5e66ba66a2c4e25056a`。Turn/steer 背景分别见 [Hermes](2026-11-03-hermes-turn-control.md) 和 [Yomi](2026-11-03-yomi-turn-control.md)。

## 1. Hermes：串行路径通常继续

串行执行器将工具返回值分类为成功或错误，提交对应 Tool Result；提交成功后仍返回 True。外层循环没有因为 `is_error` 而停止，因此一个普通错误通常不阻止下一项。参数解析失败也在提交错误结果后继续。[结果提交][h-result]、[串行循环][h-loop]

这不等于所有异常都继续：Registry/context/memory 等路径配置了异常到错误结果的转换；未配置转换的执行异常可外溢，离开当前批次。持久化失败阻止后续派发；取消会为未启动调用补出 skipped/cancelled 结果。[异常转换][h-dispatch]、[异常上抛][h-exception]、[串行循环][h-loop]

有一个直接相关的测试：第一个终端命令返回 exit code 1，第二个命令重新经过审批后仍被执行并返回 0。前项失败会使后续预先取得的批次审批失效，后项仍须满足运行时准入条件。这里仅核对测试断言，未运行测试。[失败后继续测试][h-test]

并行路径中，单个 worker 的 Exception 被转为该项错误结果，其余可执行调用已被提交，不因这一普通错误自动取消整批。[并行路径][h-parallel]

边界：另一个测试明确允许串行超时后继续下一项，同时将前项 `effect_disposition` 标为 unknown；预准备终端批次又有不同处理。因此不能将 Hermes 的超时策略直接引入 Nika，也不能把未知副作用当成普通、已知的失败。[超时测试][h-timeout]

## 2. Yomi：先并发派发，再分别收集结果

fork 与 upstream 都在权限检查后，为所有获准调用创建并发任务，再进入结果收集循环。因此一个调用报错时，其他调用可能已经开始或完成；这里没有可靠的“前一个先失败，后一个尚未执行”的顺序。[fork 派发/收集][y-batch]、[upstream 派发/收集][y-up-batch]

`tool.exec()` 的普通 Err 被转成 `ToolOutput::error`；收集循环逐项记录结果，没有根据 `is_error` 停止其他调用。结果保留原 `tool_call_id`，同批完成后回到下一次模型请求。[错误转换][y-executor]、[fork 派发/收集][y-batch]

Run 的取消信号另行处理：abort 所有任务，收集已完成结果，只为尚无结果的调用补 cancelled，并返回取消状态。不能把“某个工具返回包含 cancelled 的错误”与“Run 已被取消”混为一谈。[fork 取消路径][y-cancel]

错误表示也需单独设计：同步 Shell 的超时返回错误结果，但非零退出码写在输出正文中，工具结果本身可仍为 `is_error=false`。因此仅靠通用错误标志不能完整判断“测试未通过”之类的操作结果。[Shell 返回值][y-shell]

检查到的测试覆盖 missing-tool 的调用 ID，以及成功结果与取消结果在同一批中的配对；未找到直接断言“A 普通失败、B 仍执行”的专门用例。本节普通失败继续的结论来自源码控制流。upstream 的重复调用检测发生在整批结束后，不是单项失败即停。[配对测试][y-id-test]、[取消测试][y-cancel-test]、[重复检测][y-repeat]

## 3. Nika 的取舍：执行顺序不等于成功依赖

Nika 已选择首版串行；这只保证 A 先执行、B 后执行，**不自动表达“只有 A 成功才能执行 B”**。需要分别看两种场景：

- 同时读取两个独立文件：A 不存在，B 仍然有用。继续执行 B，可以将两个结果一起交给模型。
- 先修改文件，再验证这次修改：B 的意义依赖 A 确实成功。模型应先收到 A 的结果，再决定 B；测试通过才能发布也属于这种成功依赖。

因此，所谓“同批无依赖”必须包含两件事：**B 的参数不依赖 A 的结果，B 是否应执行也不依赖 A 的成功。** 仅仅提前知道 B 的参数还不够。分成两次模型调用仍在同一个 Turn/Run 内，不要求用户再发消息，也不建立新 Session。

两种策略都可实现，区别如下：

| 候选 | 行为 | 代价与限制 |
|---|---|---|
| 普通错误后继续 | 保存 A 的真实错误，逐项执行后续获准调用，汇总结果交模型 | 独立调用不额外等待模型；若模型把依赖动作误放同批，运行时不会自动识别和阻止 |
| 普通错误后暂停整批 | 保存 A 的错误，给尚未执行项记录未执行结果，将情况交模型重新决定 | 可阻止失败之后尚未开始的动作；独立调用也可能多一次模型往返，且仍不能防住工具错误标志未反映的业务失败 |

**当前建议，待用户确认：普通错误默认继续；有结果或成功依赖的动作分两次模型调用。** 这比此前“普通错误就暂停整批”的建议更适合独立检索等常见批次，并与现有 [System Prompt](../design/system-prompt.md) 的“不提前假设上一步结果”一致。它是模型调用约定，不是已被 Runtime 证明的独立性；不能据此放松工具本身的授权和必要前置检查。暂不增加自动依赖推断、依赖图或批次事务。

两种候选均须保留这些边界：结果提交后才能开始下一项；后续调用仍各自接受授权和资源检查；继续 B 不代表重试 A；取消、执行权失效、必需持久化失败与未知副作用单独处理。本次不决定坏调用、超时和未知结果的全部分支，也不改变既有恢复规则。

若采纳建议，后续验证至少覆盖：A 读取失败而 B 独立读取成功；A 修改失败后模型改方案，再提出验证动作；普通错误与取消/提交失败分别发生时的派发差异；所有已提出调用的结果身份完整。还须用模型场景验证是否遵守依赖动作跨请求的约定，不能仅用执行器单元测试证明模型会正确分批。

[h-result]: https://github.com/NousResearch/hermes-agent/blob/d7572ceda754b888216c212691e1b2301ebe0359/agent/tool_executor.py#L1810-L1854
[h-loop]: https://github.com/NousResearch/hermes-agent/blob/d7572ceda754b888216c212691e1b2301ebe0359/agent/tool_executor.py#L1876-L1924
[h-dispatch]: https://github.com/NousResearch/hermes-agent/blob/d7572ceda754b888216c212691e1b2301ebe0359/agent/tool_executor.py#L1658-L1739
[h-exception]: https://github.com/NousResearch/hermes-agent/blob/d7572ceda754b888216c212691e1b2301ebe0359/agent/tool_executor.py#L1756-L1807
[h-test]: https://github.com/NousResearch/hermes-agent/blob/d7572ceda754b888216c212691e1b2301ebe0359/tests/agent/test_terminal_approval_batch.py#L234-L315
[h-parallel]: https://github.com/NousResearch/hermes-agent/blob/d7572ceda754b888216c212691e1b2301ebe0359/agent/tool_executor.py#L1337-L1433
[h-timeout]: https://github.com/NousResearch/hermes-agent/blob/d7572ceda754b888216c212691e1b2301ebe0359/tests/agent/test_sequential_tool_timeout.py#L120-L166
[y-batch]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent/tool_exec.rs#L282-L429
[y-up-batch]: https://github.com/Crescent617/yomi/blob/2193746a4a2db2c17a62c5e66ba66a2c4e25056a/crates/kernel/src/agent/agent/tool_exec.rs#L324-L469
[y-executor]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/tools/executor.rs#L180-L188
[y-cancel]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent/tool_exec.rs#L301-L347
[y-shell]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/tools/shell.rs#L295-L353
[y-id-test]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent/tool_exec_test.rs#L7-L48
[y-cancel-test]: https://github.com/12bitsD/yomi/blob/7ec60e80b6b3b2f8020ba712f0b723d1d66f8a97/crates/kernel/src/agent/agent/tool_exec_test.rs#L145-L244
[y-repeat]: https://github.com/Crescent617/yomi/blob/2193746a4a2db2c17a62c5e66ba66a2c4e25056a/crates/kernel/src/agent/agent/tool_exec.rs#L71-L112
