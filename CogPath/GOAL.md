# CogPath 后续工作目标与计划

## 总目标

先让现有 CogPath 在可控的单案例上稳定跑通，再整理和重构实验代码；随后把 CogPath 的方法能力接入 agent 工作流，并在统一模型（当前优先使用 DeepSeek V4.1 Flash）下比较不同方法与 agent 的测试生成效果。研究期间补回测试生成领域的文献阅读，并根据 ASE 2026 评审意见完善技术说明和实验设计。

## 阶段计划

### 1. 跑通并固定当前实验基线

- 用一个 Defects4J 类完成端到端运行：模型请求、测试生成、Maven 执行、JaCoCo 覆盖率解析、报告落盘。
- 确认结果目录能追溯配置、模型、token 用量和生成测试；保留一条可复现的单案例命令。
- 统一通过 LiteLLM 调用模型。模型 ID、兼容 API 地址、密钥环境变量和 provider 参数放在 `src/cogpath/model_profiles.ini`；密钥只由环境变量提供。
- 单案例验证稳定后，再评估是否扩大到小批量；完整数据集实验必须使用 manifest runner 并明确实验预算。

### 2. 整理项目并逐步重构

- 盘点核心算法、模型调用、数据集适配、实验运行、指标解析和报告生成之间的依赖。
- 明确稳定的配置 schema、运行入口和结果格式，减少共享状态、隐式默认值和重复实现。
- 将重构拆成小步，每步保持当前单案例可运行，并记录行为变化及旧结果的兼容性。
- 优先整理模型调用层和实验 runner；暂不以大规模重写核心方法作为起点。

### 3. 设计 CogPath 与 agent 的比较实验

- 选择可复现的 agent 基线（先评估 OpenHands，再视安装与维护成本加入其他 agent）。
- 每个案例在隔离的项目副本中运行，避免 agent 修改原始 Defects4J subject。
- 统一模型为 DeepSeek V4.1 Flash，尽量统一任务描述、案例、构建环境与时间/调用预算；记录无法统一的 agent 特有设置。
- 先做 1 个类的 smoke run，确认 agent 能读代码、产出测试、执行 Maven 并保存日志；之后再决定小规模和完整实验范围。
- 报告 line/branch coverage、测试编译与通过情况、耗时、token/费用（可获得时）以及失败案例。
- 明确这属于端到端 agent 工作流比较；将其与只比较提示策略或算法组件的受控实验区分开。

### 4. 根据评审意见扩展证据

- **方法说明**：补充 CogPath 如何从 CFG 选取未覆盖路径、提取并合并路径条件、生成 backward slice，以及相关类依赖上下文如何选择；用完整例子对比 CogPath 与 SymPrompt 的约束信息。
- **消融与随机性**：对 CogPath、基线和消融进行配对重复运行，报告每类/每项目结果分布、均值与离散程度，并调查 noCS-noBS 反常领先的案例。
- **强模型与简单提示**：在相同模型下重跑相关基线；加入 vanilla prompt（直接要求提升分支覆盖）作为对照。
- **测试质量**：评估 mutation score，并说明覆盖率与故障检测能力的关系。
- **训练后数据**：筛选并验证训练时间之后发布的项目/版本，评估方法在 Defects4J 之外的表现。
- **贡献定位**：明确论文主要贡献是方法组合、实证发现还是认知错位假设，并据新增结果调整主张。

### 5. 恢复文献阅读

- 建立测试生成、LLM + 搜索/符号执行、LLM 反馈式测试生成、agentic coding/test generation、mutation testing 五个主题的阅读清单。
- 对每篇文献记录：问题、技术机制、基线、数据集、模型、预算、指标、与 CogPath 的差异及可复现实验材料。
- 优先阅读评审明确提到的 Codamosa、SymPrompt、HITS 及近期 agent 测试生成工作，再扩展系统综述和训练后 benchmark 研究。

## 当前约束与决策

- 当前模型：DeepSeek V4.1 Flash；模型 profile 的别名映射到 LiteLLM 模型 ID，API key 不写入仓库。
- 当前优先级：先完成小案例端到端验证，再做结构整理和 agent 集成。
- 不直接启动 130 类 × 多次重复的完整实验；先完成单案例/小样本验证，并为后续实验明确运行次数和预算。
- 每次实验保存独立配置快照和原始日志，避免只保留汇总指标。

## 进度记录

- [x] 已配置 DeepSeek V4.1 Flash 的 LiteLLM profile，并完成一次短请求验证。
- [ ] 核对模型 profile 覆盖普通调用与工具调用路径，并完善新增模型的配置说明。
- [x] 固化并运行单案例端到端验证：OpenHands 与 CogPath 均使用隔离副本，Maven 和 JaCoCo 结果已落盘。
- [ ] 完成项目模块/依赖地图和重构切分方案。
- [x] 新增并编译检查 OpenHands 单案例 adapter：从数据集索引定位类、复制隔离 subject、调用 SDK、保存事件和最终 Maven/Surefire/JaCoCo 结果；原始 subject 未被修改。
- [x] OpenHands 的 `JacksonXml-5f::ToXmlGenerator` smoke run 最终通过 Maven 与 JaCoCo：经 6 次 repair 后 83 个测试全部通过，line coverage 76.92%，branch coverage 85.65%。首轮生成 94 个测试但有 4 failures/26 errors；全程约 2.74M prompt tokens，费用估算不可用。此为修复后结果，须与初始有效率及 repair 成本一起报告。
- [x] 同一类上运行 CogPath 4 轮先导对照（独立副本、DeepSeek V4.1 Flash、Constraint-Hints + Backward Slicing、每轮 1 次修复）：line/branch coverage 为 14.74%/10.19%，60 次测试验证中 12 通过、45 失败、3 编译失败，约 217,557 tokens。对比记录在 `evaluation/agent_baselines/README.md`。
- [x] 加入 Aider 0.86.2 作为第二个 agent，并在同一案例/模型运行：两次 repair 后 21 个测试全部通过，line/branch coverage 为 48.93%/43.98%，累计 873,975 tokens（初始运行 5 errors，repair 后先降至 1 error 再通过）。当前初始 Aider 会话未限制 chat-history，故其 token 用量只作先导记录；adapter 已新增 32k history cap。
- [ ] 当前先导对照预算不匹配，且未重复运行；需设计公平的 agent/CogPath 预算、修复策略和重复实验，再用于研究结论。
- [x] 增加至少一个其他 agent 基线：Aider 通过 OpenAI 兼容 endpoint 接入 DeepSeek profile，runner 复用相同 subject 索引与 JaCoCo/Surefire 指标解析；当前仍只完成一个案例。
- [ ] 选定 agent 比较基线和实验预算。
- [ ] 按评审意见实施重复实验、mutation score 和训练后数据评估。
- [x] 整理 2024—2026 年单元测试生成研究亮点及 CogPath 的后续研究方向，见 [`LITERATURE_REVIEW_2026.md`](LITERATURE_REVIEW_2026.md)；后续精读论文时继续补充原文链接、技术细节与比较记录。
- [x] 扩展到第二个案例 `Csv-16f::CSVParser`：OpenHands 经过 1 次修复后 53 个测试全部通过，line/branch coverage 为 96.04%/85.71%，累计 749,203 tokens；Aider 0.86.2 生成 20 个通过测试，line/branch coverage 为 88.12%/71.43%，累计 983,193 tokens；CogPath 4 轮后报告 35 个通过、8 个测试失败、2 个编译失败，line/branch coverage 为 97.03%/85.71%，累计 133,017 tokens。该案例同样是单次先导运行，预算与成功标准不匹配，不能据此判定方法优劣；日志和指标分别保存在 `evaluation/result-files/` 与 `result-files/`。
