```mermaid
flowchart TB
    subgraph Init["初始化阶段"]
        A1[接收命令行参数] --> A2[设置日志路径]
        A2 --> A3[验证并映射LLM模型]
        A3 --> A4[提取测试依赖]
        A4 --> A5[验证源文件路径]
        A5 --> A6[创建测试文件框架]
        A6 --> A7[初始化UnitTestGenerator]
    end

    subgraph Analysis["初始分析"]
        B1[初始测试套件AST分析] --> B2{检查终止条件}
    end

    subgraph Loop["迭代生成循环"]
        B2 -->|未达到目标| C1[记录当前覆盖率]
        C1 --> C2{是否为初始迭代<br/>或覆盖率为0?}

        C2 -->|是| C3[使用Baseline提示<br/>生成初始测试]
        C2 -->|否| C4[使用迭代提示<br/>生成新测试]

        C3 --> C5
        C4 --> C5{启用Backward Slice?}

        C5{覆盖率<br/>未增加次数<br/>> β × 阈值?}
        C5 -->|是| C6[通过Backward Slice<br/>生成额外测试]
        C5 -->|否| C7

        C6 --> C7[验证所有生成的测试]
        C7 --> C8[运行覆盖率统计]
        C8 --> C9{启用测试修复?}

        C9 -->|是| C10[修复失败的测试]
        C9 -->|否| C11

        C10 --> C11[检查覆盖率是否增加]
        C11 --> C12{覆盖率增加?}

        C12 -->|是| C13[重置未增加计数]
        C12 -->|否| C14[增加未增加计数]

        C13 --> C15[记录路径历史]
        C14 --> C15
        C15 --> C16[迭代次数+1]
        C16 --> B2
    end

    subgraph Report["报告生成"]
        D1[达到目标覆盖率?] --> E1[生成测试结果报告]
        D2[达到最大迭代次数?] --> E1
        D3[覆盖率无法增加?] --> E1

        E1 --> E2[保存详细路径历史JSON]
        E2 --> E3[清理测试文件]
    end

    B2 -->|终止| D1
    D1 -->|是| E1
    D1 -->|否| D2
    D2 -->|是| E1
    D2 -->|否| D3

    style Init fill:#e1f5fe
    style Analysis fill:#e8f5e8
    style Loop fill:#fff3e0
    style Report fill:#fce4ec
```

### 流程图说明

**1. 初始化阶段 (Initialization)**
- 接收并解析命令行参数
- 配置日志系统
- 验证LLM模型可用性
- 提取项目测试依赖
- 创建测试类框架（JUnit 3/4/5）
- 初始化测试生成器

**2. 初始分析 (Initial Analysis)**
- 对源代码进行AST分析
- 建立初始覆盖率和未覆盖代码映射

**3. 迭代生成循环 (Iterative Generation Loop)**
- **终止条件**: 达到目标覆盖率 OR 达到最大迭代次数 OR 覆盖率无法继续增加
- **测试生成**:
  - 初始迭代: 使用Baseline提示模板
  - 后续迭代: 基于未覆盖代码和执行路径生成针对性测试
  - Backward Slice: 当常规迭代无法提升覆盖率时，使用代码逆向切片技术
- **测试验证**: 编译、运行、收集覆盖率
- **可选修复**: 对失败的测试进行修复

**4. 报告生成 (Report Generation)**
- 生成HTML格式测试结果报告
- 保存详细路径历史用于分析
- 清理临时测试文件
