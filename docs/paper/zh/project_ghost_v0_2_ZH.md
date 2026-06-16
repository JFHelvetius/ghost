# 自主系统的认识论契约：不确定性下安全声明的可验证模式

**作者：** Javier Menéndez Mateos (`jfhelvetius@gmail.com`)
**单位：** 独立研究者
**版本：** v0.2.3（2026-06-12）
**代码仓库：** <https://github.com/JFHelvetius/ghost>
**PyPI：** <https://pypi.org/project/project-ghost/>
**文档：** <https://JFHelvetius.github.io/ghost/>
**许可证：** Apache-2.0

> **内部说明：** 本文档是英文论文
> [`project_ghost_v0_2.md`](../project_ghost_v0_2.md) 的中文翻译，
> 供作者和中文母语合作者使用。提交给 arXiv 和 FMAS 2026 的标准版本
> 为英文版本；如两版本出现差异，应以英文版本为准。技术名称
> （BAUD-v1、ERUR-v1 等）、代码仓库文件引用、表格、代码片段以及
> 形式化属性名称均保留英文。

---

> *自主代理应当对其如何与自身的不确定性相关有可验证的义务。*
>
> *安全声明应当与第三方拒绝它所需的一切一起发布。*
>
> —— 本论文存在所要捍卫的两句话。

---

## 摘要

**论点：自主代理应当对其自身的认识论姿态有可验证的契约 ——
它们如何降级信心、恢复、保持有界，以及在不确定性下将信念转
化为行动。** 大多数现有的运行时验证器询问关于世界的谓词（速
度、距离、温度）；我们提出询问关于代理对自身不确定性姿态的
谓词。我们将这些称为**认识论安全契约**。我们介绍 **Project
Ghost**，一个开源平台，它 (i) 为参考自主性监督器定义了五个
认识论契约（BAUD/ERUR/MD/RLB/FPB），(ii) 通过对内容寻址的
MCAP 日志的纯函数验证每一个，(iii) 通过 TLA+/TLC 机械检查底
层不变式，并 (iv) 将每个契约与录制的运行和验证器一起打包为
单个**可执行的安全引用**：`pip install project-ghost==0.2.3`
然后 `ghost verify-properties --mcap <log>` 使第三方能够重现
裁定 —— 或反驳它。

参考契约涵盖了不确定性下行为的最小理论：如果你怀疑自己错了，
要保守地行动（BAUD）；当证据恢复时，回到行动（ERUR）；永不
声称比证据支持的更多信心（MD）；不确定性不能无限持续（RLB）；
不信任必须可测量、可审计（FPB）。三个 TLA+ 规范共同检查 CI
中的 11 个不变式，包括分区定理 `BAUD ⊕ ERUR` 和恢复延迟界限
`L ≤ peak + W − 1`。

在六个注入 bug 类别的违规矩阵、三个结构性不同的校准策略、三
个 shape-realistic 漂移剖面、对 RTAMT 的头对头基准测试，以
及真实 PX4 v1.10 飞行遥测上的判别实验 —— 两个独立有缺陷的
组件，替换到同一物理飞行中，都将 BAUD-v1 从 HOLDS 翻转为
VIOLATED，而其他四个属性保持 HOLD —— 上的实证评估表明，验
证器是策略无关的，在 Linux 和 Windows CI runner 之间具有确
定性，并在真实遥测上具有信息量。完整工件可从
`pip install project-ghost==0.2.3` 重新运行。

**关键词：** 认识论安全契约、运行时验证、自主性中的不确定
性、可执行的安全引用、内容寻址遥测、TLA+/TLC、MCAP。

---

## 1. 引言

大多数现有的运行时验证器询问关于世界的谓词：速度低于界限、
距离高于边距、温度在包络内。我们询问关于代理对自身不确定性
姿态的谓词：代理必须满足的契约，关于*如何*降级信心、*如何*
恢复、*如何*使其不确定性保持有界、以及*如何*将信念转化为
行动。我们将这些称为**认识论安全契约**。

认识论契约不是关于代理*相信什么*的契约；而是关于*基于*它对
自己的相信，代理*必须做什么*的契约。"如果你检测到你的校准
历史包含漂移的证据，则不可发出非保守动作"（BAUD）是与"速度
必须保持在 5 m/s 以下"（一个 STL 风格的关于信号的谓词）不
同形状的属性：前置条件指向代理的自我评估，而非世界。

随之而来第二个空缺：即使存在正确形状的属性，想要对录制的运
行进行安全声明验证的第三方通常无法做到 —— 没有 shell 命令，
没有内容寻址的日志，没有他们可以在自己机器上重新运行的纯函
数验证器。我们在一个平台中弥补两个空缺。Project Ghost 是
sim-first，用 Python 编写，作为可 `pip` 安装的包发布，带有
一个 CLI 子命令（`ghost verify-properties`），接收捕获的
MCAP 日志并返回对参考自主性监督器的五个认识论契约的
byte-exact 判定。每个契约都在有约束力的 ADR 中声明，由纯函
数对日志验证，由 Hypothesis property tests 测试，并由 CI
在每次推送时自我强制。其中两个契约（BAUD-v1 和 ERUR-v1）还
通过 TLA+/TLC 进行**机械验证**，连同分区定理。

将一个认识论契约与其录制的运行和验证器一起打包成一个可引用
的、第三方可证伪的单元，正是我们所称的**可执行的安全引用**。
被引用的工件*就是*证伪机制。

### 1.1 贡献

**认识论安全契约是自主代理必须满足的、关于其自身不确定性的
可验证义务。** 一个契约是三元组（关于代理认识论状态的前置
条件、关于代理行为的后置条件、对录制运行的纯函数验证器）—— 与
今天主导运行时验证的世界谓词不同的属性类。我们将每个契约与
运行和验证器一起打包为**可执行的安全引用**。

我们做出**三项贡献**：

- **C1 —— 作为验证目标的认识论安全契约（概念性）。** 一类
  安全属性，其前置条件指向代理对自身不确定性的信念
  （calibrated-self-assessment 等级、漂移检测、fire-rate
  测量），而非外部世界的信号。与 STL 风格关于信号的谓词以
  及 POMDP 风格的 belief monitoring 不同；形式化定义在 §1.2。

- **C2 —— 参考实现：Ghost（工件）。** 一个闭环自主性监督器，
  实例化五个认识论契约（BAUD-v1、ERUR-v1、MD-v1、RLB-v1、
  FPB-v1）并打包为可执行的安全引用 —— 有约束力的 ADR、内容
  寻址的 MCAP 遥测、`ghost verify-properties --mcap`、OIDC
  签名的 PyPI wheels，以及跨三个校准策略的策略无关验证器
  （§8.4）。

- **C3 —— 机械验证 + 实证评估（验证）。** 三个 TLA+ 规范
  （CI 中 11 个不变式，包括分区定理 `BAUD ⊕ ERUR`）、一个
  六类违规矩阵（§8.2）、shape-realistic 漂移剖面（§8.5）、
  对 RTAMT 的能力基准测试（§8.6），以及真实 PX4 飞行遥测上
  的判别：两个有缺陷组件，替换到同一物理飞行中，都将 BAUD-v1
  从 HOLDS 翻转为 VIOLATED（§8.8）。

恢复延迟界限 `L ≤ peak + W − 1` 作为**支持结果**呈现，而非
贡献。

### 1.2 认识论安全契约：形式化定义

**认识论安全契约**是三元组 `(P, Q, V)`，其中：

- `P` 是关于代理**在周期 `t` 的认识论状态**的谓词 —— 即代理
  在 `t` 时可用的自我评估记录、校准历史和结果流的函数。`P`
  不直接指向世界；它指向代理对自身相对世界姿态的信念。
- `Q` 是关于代理**在周期 `t` 的行为**的谓词 —— 即在 `t` 时
  发出的 calibrated assessment、决策和执行器命令的函数。
- `V` 是纯函数验证器，使得给定录制运行 `r`（per-cycle 遥测
  记录的内容寻址序列），`V(r)` 返回 HOLDS 当且仅当 `r` 中
  每个满足 `P_t` 的周期 `t` 也满足 `Q_t`，否则返回 VIOLATED
  及证人周期。

三点观察：

1. **认识论契约不是 STL 谓词。** STL 监视器评估 `信号 < 阈值`
   形式的谓词，作用于实值时序信号上。认识论契约的原子谓词
   是关于代理*自身校准与决策的内部记录*，这是结构化数据，
   不是连续信号。STL 算子（always、eventually、until）可
   提升到作用于认识论契约的周期索引；RLB-v1（有界 eventually）
   就是这样表达的。

2. **认识论契约不是 belief monitoring。** Belief monitoring
   跟踪代理对隐藏世界状态的信念（如 POMDP 信念更新、粒子
   滤波后验）。认识论契约验证关于代理*与其自身信念的关系*
   的义务 —— 它必须在正确条件下降级信心、在有界延迟内恢复，
   并永不声称比证据支持的更多信心。契约位于信念之上一层：
   它是代理*认识论策略*的属性，而非其信念本身的属性。

3. **认识论契约在与内容寻址的录制运行和 OIDC 签名的验证器
   wheel 一起打包时，成为可由第三方证伪的安全声明。** 我们
   将此打包称为**可执行的安全引用**（图 1）。

我们交付的五个契约（§3）在代表性的自主性监督器上实例化此定义。

### 1.3 本论文是什么和不是什么

这是一篇引入属性类别的工程和基础设施论文，而非证明新逻辑的
理论论文。Ghost 依赖的滤波、校准和 FDI 要素已被广泛建立
（§2.1）。恢复延迟界限是辅助结果，而非贡献。§5.3 的分区定
理*在我们机械化的形式上*是新颖的 —— 参考闭环上的 TLA+
`INV_PARTITION`。我们捍卫的贡献是**认识论契约 framing**
（C1）、**参考实现**（C2）和**验证**（C3）。

#### 图 1：安全引用模式

```mermaid
flowchart LR
    subgraph P["生产者（Ghost 作者 / 操作员）"]
        ADR["📜 有约束力的 ADR<br/>属性谓词"]
        Code["🔧 纯函数验证器<br/>+ 闭环管道"]
        Spec["🧪 Property tests + TLA+<br/>（11 个不变式）"]
    end
    subgraph R["CI + 签名发布"]
        CIv["⚙ ghost verify-properties<br/>+ TLC + 跨机器"]
        Tag["🏷 标记发布 v0.2.3<br/>OIDC 签名 PyPI wheel"]
    end
    subgraph A["可引用工件"]
        MCAP["📦 MCAP 日志<br/>SHA-256，byte-exact"]
        Cite["🔗 引用<br/>pip install + SHA-256 + ADR ID"]
    end
    subgraph V["第三方（任何人）"]
        Cmd["💻 ghost verify-properties<br/>--mcap log.mcap"]
        Out["📋 Exit 0/1 + 确定性 JSON<br/>（每个属性的判定）"]
    end
    ADR --> Code
    Code --> Spec
    Spec --> CIv
    CIv --> Tag
    Code -. 产生 .-> MCAP
    Tag --> Cite
    MCAP --> Cite
    Cite ==> Cmd
    Cmd ==> Out
```

该图从左到右阅读，作为该模式下安全声明的操作管道。在生产者一
侧，有约束力的 ADR 陈述属性谓词，纯函数验证器实现其语义，
Hypothesis property tests + TLA+ 规范演练不变式。CI 在每次推送
时门控，标记切割 OIDC 签名的发布。可引用工件承载两半：运行
（带 SHA-256 的 MCAP）和验证工具（按版本固定的 PyPI wheel）。
第三方用一个 shell 命令将它们连接起来，获得每个属性的确定性
JSON 判定。**本论文的贡献是将七个框组装为一个可发布的单元，因此 —— 据我们
所知，在我们所调查的文献范围内，这是首次 —— 安全声明可以与第
三方拒绝它所需的一切一起发布。** 其他一切（属性集、封闭式界
限、TLA+ 规范）在代表性监督器上实例化该模式。

---

## 2. 背景与相关工作

### 2.1 基础要素

Project Ghost 建立在属于机器人和控制标准实践的要素之上：贝叶斯
滤波和粒子滤波、概率预测的校准、认知与偶然不确定性、FDI、运行
时验证、TLA+ 和 TLC 用于显式状态模型检查、MCAP 用于可移植的内容
寻址机器人遥测数据序列化。

### 2.2 最接近的工具相关工作

- **RTAMT** [Niković 等人，ATVA 2020]：基于 STL 的 CPS 日志监视
  器，具有 online/offline 算法和 Python API。属性语言是 STL，
  不是手工预测；没有机械验证的证明层，也没有内容寻址的可重现性
  链。
- **MoonLight** [Bartocci 等人，RV 2020]：Java 中的 STREL（时空
  逻辑）监视器，具有 CLI，用于汽车基准。空间关注；没有形式化验
  证监视器语义。
- **ROSMonitoring** [Ferrando 等人，2020] 和 **ROSRV** [Huang
  等人，RV 2014]：对 ROS-middleware 的实时监视器。两者都是
  online；都没有使用单行 CLI 的事后日志验证。
- **Safe RL via shielding** [Jansen 等人，CONCUR 2020]：通过
  动作过滤器进行安全的运行时强制。在线、动作阻断；Ghost 是离线、
  日志验证的。
- **Control Barrier Functions** [MIT Lincoln Lab CBF Toolbox]：
  用于连续安全约束的控制器合成。补充性，不竞争。
- **Conformal prediction for robot safety** [Chakraborty 等人，
  TAC 2024]：用于门控动作的前向无分布不确定性界限。预测性；
  Ghost 是回溯性。
- **Supervisory control of timed automata** [Flordal 等人，
  2022]：合成 timed 监督器。构建新监督器；Ghost 验证现有跟踪。
  之前的 timed automata 工作没有给出 恢复延迟界限 的封闭式界限。
- **Surveys of formal verification for autonomy** [Rizaldi 等人，
  ACM CSUR 2020]：编目 Coq/Lean/Isabelle/Alloy 工作。注意到针对
  自主性监督器的机械验证 TLA+ 规范缺失。

### 2.3 比较矩阵

| 维度 | **Ghost** | RTAMT | MoonLight | Shielding | CBF | Conformal | Timed Aut. SC |
|---|---|---|---|---|---|---|---|
| 验证模式 | 事后日志 | On/offline | On/offline | 在线强制 | 在线控制 | 在线门控 | 离线合成 |
| 分发方式 | PyPI + OIDC | 源代码 | 源代码 | 框架 | 工具箱 | 代码+论文 | 合成工具 |
| 内容寻址输入 | **是** (SHA-256) | 否 | 否 | N/A | N/A | N/A | 否 |
| 单行 CLI 验证器 | **是** | 否 | 否 | 否 | 否 | 否 | 否 |
| 属性性质 | 行为+延迟 | STL | STREL | 不变式 | CBF | 预测性 | 离散/timed |
| 机械证明 | **TLA+/TLC** | 无 | 无 | 非正式 | 非正式 | 无 | Timed-aut. |
| 多属性输出 | **5 reports/run** | 1/spec | 1/spec | 模块化 | 1/CBF | 1/model | 1/synth. |
| 分区定理 | **BAUD ⊕ ERUR** | N/A | N/A | N/A | N/A | N/A | N/A |
| 封闭式恢复界限 | **L ≤ peak + W − 1** | N/A | N/A | N/A | N/A | 间接 | 无 |
| Bug 检测演示 | **是 (§8.2)** | N/A | N/A | N/A | N/A | N/A | N/A |

据我们所知，**没有先前工具通过 `pip install` + OIDC 签名 wheel
分发内容寻址、纯函数的安全属性验证器，并具有机械验证的底层不变
式**。我们将此作为 Ghost 的主要操作声明；上面的比较是其证据。

Ghost 真正与上述运行时验证工具不同的轴是它监控*何种*谓词。
RTAMT、MoonLight、ROSMonitoring 和 shielding 监控关于外部世界
的谓词（速度边界、距离阈值、信号包络）。Ghost 的五个属性（§3）
是关于代理**认识论姿态**的契约 —— 其自身的信心如何在不确定性
下被降级、恢复、约束并转化为行动。机制有重叠（我们都重放
trace）；提出的问题不同。

### 2.4 本工作的新颖之处

两个贡献是操作性的模式声明（可重现性原语和端到端引用模式）。两
个是形式化声明，据我们经过深思熟虑的 prior art 审查所知，没有
出现在 peer-reviewed 文献的我们陈述的形式中：

- **封闭式恢复延迟界限 `L ≤ peak + W − 1`** 对于 count-of-K-in-W
  滑动窗口监视器。Sequential probability ratio tests 给出假设检
  验的最优样本大小界限，但没有这种用于滑动窗口恢复的封闭式形式，
  而 timed automata 工作偏好定性的非阻塞保证而非具体的延迟界限。
  我们将其形式化为 恢复延迟界限（§6.4），并通过构造证明其紧致。
- **分区定理 `BAUD ⊕ ERUR`** 关于闭环自主性监督器的每周期条件
  行为空间，由 TLC 在抽象模型上证明。我们没有找到专门针对滑动
  窗口安全监督器的条件行为分区的先前形式化。

### 2.5 Ghost 在工业实践中的位置

自主性安全领域由 Ghost 无法企及的规模的工业努力主导：Waymo 的
safety case 框架，PX4 的 `commander` 状态机，NASA 的 NFM 传统，
Autoware 的安全架构，Cruise 的 safety case 方法论。它们都共享
Ghost 没有的组织属性：**安全工程师团队和对遥测、测试基础设施和
监管机构的专有访问**。它们产生证明运营部署正当性的保证 artifact。

Ghost 做出一个小得多的声明 —— *第三方可以通过发出一个 shell 命
令对捕获的运行验证陈述的属性* —— 但它以**操作方式**做出这个声
明，而不是诉诸内部 review。我们认为 Ghost 填补的互补利基是
"这个软件是安全的"（由组织签署的封闭声明）与"这里是验证器和日
志；自己检查"（第三方可引用的开放声明）之间的差距。Citation
pattern 不是工业 safety case 的替代品；它是这些 case 可以引用
的原语。我们不声称与上述工作等同、范围或成熟度。

---

## 3. 属性集

**与传统的运行时验证（主要监控关于外部世界的谓词：速度、距
离、温度）不同，Ghost 验证关于代理认识论姿态的契约：信心如何
在不确定性下被降级、恢复、约束并转化为行动。** 五个属性构成
了一个自主代理在不确定性下行为的最小理论：

| ID | 形式谓词 | 认识论解读 |
|---|---|---|
| **BAUD-v1** | 检测到漂移 → 不 PROCEED + 保守动作 | *如果你怀疑自己错了，要保守地行动。* |
| **ERUR-v1** | 漂移缺失 ∧ belief KNOWN → PROCEED | *当证据恢复时，回到行动。* |
| **MD-v1** | `adjusted ≼ raw`（无膨胀） | *永不声称比证据支持的更多信心。* |
| **RLB-v1** | `L ≤ peak + W − 1`（恢复有界） | *不确定性不能无限持续。* |
| **FPB-v1** | 经验触发率被暴露和固定 | *不信任必须可测量、可审计。* |

每个属性都在有约束力的 ADR 中声明（一旦接受即不可变），并由
`src/project_ghost/properties/` 中的纯函数验证。

### 3.1 BAUD-v1 — Bounded Action Under Drift

> *如果代理怀疑自己的信念是错误的，必须保守地行动。*

当检测到漂移时（窗口中 ≥M 个结果且 ≥K 个 dirty），调整等级在 lattice
中降低，决策不是 PROCEED，且 actuator 命令（如果有）属于封闭的
safe-reason 集合 `S_BAUD = {attitude_hold_hold, kill_zero_throttle}`。
ADR-0031。

### 3.2 ERUR — Eventual Reactivation Under Recovery (ADR-0032)

> *当证据恢复时，代理必须回到行动。*

契约分两层陈述：具体的参考谓词（v1）与策略参数化的提升（v2）。

**ERUR-v1（参考谓词）。** 前置条件：在*参考*的 count-of-K-in-W
规则下漂移缺失（`outcomes < M` 或 `dirty_count < K`，使用
`M=4, K=2`）且原始 belief 为 KNOWN。后置条件：调整等级为 KNOWN 且
决策为 PROCEED。v1 将前置条件的参数固定为参考 Mahalanobis 校准
器；这是 v0.2.3 验证器交付的内容。

**ERUR-v2（策略参数化）。** 设 `policy.drift_precondition` 为
校准策略 Protocol 上的方法，对于当前校准历史返回该策略*自身*
对漂移是否存在的判断（每周期一个 Boolean）。ERUR-v2 的前置条
件是：`not policy.drift_precondition(history)` 且原始 belief
为 KNOWN。ERUR-v2 是 §2.3 中**策略无关**主张实际支持的内容：
ERUR 由任何自身漂移准则缺失且 belief 为 KNOWN 的策略所满足，
而不仅是共享 Mahalanobis 的 `(M,K)` 的校准器。v2 验证器将前置
条件委托给每个待测策略；v1 验证器是 v2 验证器以参考策略的谓
词实例化得到的。§8.4 评估两者，v1 与 v2 判定在替代校准器上的
差异是 lifting 有意义的运行时证据。

与 BAUD 共同构成**分区定理**：每个原始 belief 为 KNOWN 的周
期或满足 BAUD 的前置条件或满足 ERUR 的，两者从不重叠。TLA+
规范将此提升为在抽象模型上**在 v1 下证明的定理**（第 5 节）；
分区论证按构造提升至 v2，因为 v2 严格地将前置条件委托给校准
策略。

### 3.3 MD-v1 — Monotonic Degradation

> *代理永不声称比证据支持的更多信心。*

对所有周期，confidence lattice 中 `adjusted ≼ raw`。校准器从不
*发明*信心。ADR-0033。

### 3.4 RLB-v1 — Recovery Latency Bound

> *代理的不确定性不能无限持续；恢复由校准窗口结构所约束。*

对 sliding-window count-of-K-in-W filters 的 `L ≤ peak + W − 1`。
这是 恢复延迟界限（§6.3）。ADR-0034。

### 3.5 FPB-v1 — False Positive Bound observer

> *代理的不信任必须可测量、可审计，而非隐式的。*

运行期间的经验 BAUD fire rate，作为结构化指标暴露用于回归门控。
默认情况下是观察性的（`max_fire_fraction = 1.0`）。ADR-0035。

---

## 4. 验证器架构

### 4.1 内容寻址 MCAP

每个捕获的运行都被实例化为一个 MCAP，每个通道都有已知的消息
schema。感兴趣的通道包括 `/fusion/results`、`/uncertainty/*`、
`/decisions/decision`、`/actuation/command`、`/prediction/*`。每条
消息在给定上游输入的情况下是确定性的（重放验证，ADR-0030，确
保 byte-exact）。MCAP 的 SHA-256 是内容地址，并记录在每个验证
器的输出 report 中。

### 4.2 纯函数验证器

每个属性在 `src/project_ghost/properties/verify_<id>.py` 中有一
个验证器。验证器 (a) 以只读方式打开 MCAP，(b) 按周期顺序遍历感
兴趣的通道，(c) 仅从存储的消息中计算每周期的前置和后置条件（无
重放、无模拟），并 (d) 返回 typed report。

### 4.3 CLI 表面

```bash
$ pip install project-ghost==0.2.3
$ python -m project_ghost.examples.closed_loop_smoke
$ ghost verify-properties --mcap closed_loop_smoke.mcap
BAUD-v1: HOLDS  (M=4, K=2, 6/10 cycles evaluated)
ERUR-v1: HOLDS  (M=4, K=2, 4/10 cycles evaluated)
MD-v1:   HOLDS  (10/10 cycles evaluated)
RLB-v1:  HOLDS  (W=32, 0/10 cycles evaluated)
FPB-v1:  HOLDS  (fire_fraction=0.60, 6/10 cycles evaluated)
$ echo $?
0
```

Exit code 约定：`0` 当且仅当所有属性成立，`1` 如果任何属性违反
或验证器崩溃，`2` 用于参数错误。`--json` 发出适合 CI 消费的确
定性 JSON 对象。

### 4.4 内嵌自证 + CI 作为持续保证

`run_closed_loop_smoke()` 返回一个 `SmokeSummary`，它携带针对
刚写入的 MCAP 计算的五个 property reports。`ci.yml` 在每次推送
时运行 smoke + 验证器，在三个 TLA+ 规范上执行 TLC，并验证 MCAP
在 Linux 和 Windows runner 之间的 byte-equality。任何违反都会
阻塞构建。

---

## 5. 机械验证

### 5.1 为什么选 TLA+

使用 Hypothesis 进行基于属性的测试（每个属性 200+ 个例子）在生产
规模上提供了强有力的证据，但它证明属性*在生成器采样的输入上*成
立，而非在所有输入上。下一级证据是**在有限抽象模型上的机械验
证**。我们出于成本/效益论证选择 TLA+ 与 TLC 而非定理证明
（Lean、Coq）：TLC 在有界状态空间上几秒内即可穷尽，而 Lean 证
明需要几周。

### 5.2 三个规范

三个 TLA+ 规范共同涵盖五个属性；每个都为其作用域内的策略逐行
镜像 Python 源代码。

- **`BaudErur.tla`** 将闭环建模为每周期一个转换的状态机。状态变
  量包括校准历史（最多 `W` 条目的有界序列）、原始评估等级，以及
  派生的调整等级、决策类型和执行器安全标志。参考校准器
  （`MahalanobisDowngradePolicy`）、决策策略
  （`UncertaintyAwareReferencePolicy`）和执行器安全分类器作为
  TLA+ 定义被镜像。
- **`Rlb.tla`** 通过两个阶段（`ACCUMULATING`、`RECOVERING`）将模
  型限制为 恢复延迟界限（§6.3）的连续漂移假设。它镜像
  `src/project_ghost/properties/rlb.py` 的验证器算法，并跟踪
  dirty-run 计数器和运行期间观察到的 peak。
- **`Fpb.tla`** 在整数算术中建模 FPB-v1 计数器自动机（两个计数
  器：`cycles_total`、`cycles_fires`）。它验证计数器的结构良好
  性，而不是 fire rate 的概率界限（后者是 FPB-v2 的范围，§10）。

### 5.3 检查的不变式

三个规范共同在持续 CI 中验证 11 个不变式（BaudErur 中 5 个、
Rlb 中 3 个、Fpb 中 3 个），覆盖 BAUD/ERUR/MD/RLB/FPB，每个至
少有一个结构性不变式。这将机械覆盖率从 v0.2.1 的 3/5 提升至
v0.2.3 的 **5/5**。

### 5.4 界限及其证明的内容

为了易处理性，每个规范都使用故意小的有界常数运行：

| 规范 | 界限 | 为什么足够 |
|---|---|---|
| `BaudErur.tla` | `M=2, K=1, W=3` | 前置条件的*边界情况*在任何正 `M` 下穷尽；`W ≥ M` 演练滑动窗口机制。 |
| `Rlb.tla` | `W=4, MAX_DRIFT=4` | 演练 恢复延迟界限 证明的所有四个阶段（积累、饱和、flush、recovery）。 |
| `Fpb.tla` | `MAX_CYCLES=8` | 八个周期枚举计数器自动机的每个 fire/non-fire 交替。 |

生产规模常数（`M=4, K=2, W=32`）下的行为由 property tests 覆
盖。TLA+ 填充*小但穷尽*的角落。将 恢复延迟界限 提升到*任何有限 W*
（unbounded proof）是文档化在
[`docs/proofs/TLAPS_roadmap.md`](../../proofs/TLAPS_roadmap.md)
中的候选 ADR-0038。

### 5.5 声明什么和不声明什么

**声明：** ADR 0031–0033 中的属性陈述与参考策略语义在抽象模型
上逻辑一致；BAUD + ERUR 分区在抽象模型上结构完整；有界状态空
间中没有 (history, raw_level) 组合违反不变式。

**不声明：** Python 实现忠实地镜像 TLA+ 模型（bridge 是通过人工
检查；自动化是 future work）；有界常数证明 unbounded case；
非参考策略满足不变式（每个都需要自己的规范）。

---

## 6. 封闭式恢复延迟界限

### 6.1 设定

设 `(o_t)_{t ≥ 1}` 是每周期预测结果的流，按二元分区
`dirty ∈ {0, 1}` 分类，其中 `dirty = 1` 当 Mahalanobis verdict
等于或高于 BAUD 前置条件考虑的阈值。设 `H_t` 表示周期 `t` 时可
用的最后 `W` 个结果的滑动窗口：

```
H_t = (o_{max(1, t − W + 1)}, ..., o_t),    |H_t| ≤ W.
```

参考校准器（`MahalanobisDowngradePolicy(M, K)`）在满足以下条件
的任何周期中将调整的自评估等级在置信度格上降一级：

```
|H_t| ≥ M    且    Σ_{o ∈ H_t} dirty(o) ≥ K.    (1)
```

### 6.2 定义

- **peak** = 在 dirty run 期间窗口中观察到的最大 dirty count。
- **drift interval** = 以 (1) 持续成立的最后一个周期结束的最大
  子跟踪。
- **L** = 恢复延迟：窗口包含至少一个 dirty 结果的连续周期数。

### 6.3 恢复延迟界限

**恢复延迟界限（RLB-v1，瞬态情况）。** *设 `(o_t)_{t ≥ 1}` 是包含
`N ≤ W` 个连续 dirty 结果的瞬态 drift interval 后跟 clean 结果的
流，窗口大小为 `W`。定义：*

- *`peak = min(N, W) = N`，在 dirty run 期间在窗口中观察到的最
  大 dirty count；*
- *`L`，dirty-run length：窗口包含至少一个 dirty 结果的连续周
  期数。*

*那么 `L = peak + W − 1`。等价地，界限 `L ≤ peak + W − 1` 达到
等式。因此界限是紧致的。*

**证明。** 逐周期跟踪窗口状态，注意滑动窗口不变式：在周期 `t`，
窗口包含最后 `min(t, W)` 个结果。

- **积累阶段**（周期 1..N）。每个周期添加一个 dirty 结果；窗口
  尚未填满（因为 `N ≤ W`），因此没有驱逐。dirty count 从 1 上
  升到 `N = peak`。所有 `N` 个周期 count `≥ 1`，因此是 dirty。
- **饱和阶段**（周期 N+1..W）。每个周期添加一个 clean 结果；窗
  口尚未填满，没有驱逐。dirty count 保持在 `peak`。所有 `W − N`
  个周期都是 dirty。
- **Flush 阶段**（周期 W+1..W+peak−1）。窗口现在已满；每个新
  clean 结果驱逐最旧的条目。根据构造，最旧的条目是最先到达的
  dirty 结果。dirty count 每周期减 1，从 `peak` 到 `1`。所有
  `peak − 1` 个周期都是 dirty（count `≥ 1`）。
- **恢复**（周期 W+peak）。最后一个 dirty 结果被驱逐。dirty
  count 降到 `0`。这个周期是 clean。

求和 dirty 周期：`N + (W − N) + (peak − 1) = W + peak − 1`。由
于在瞬态情况下 `peak = N`，`L = peak + W − 1`。∎

**推论 1（操作情况）。** 当 `N > W` 时，drift 超过窗口；
`peak = W` 和 `L = N + W − 1`。当 `N > W` 时，界限
`peak + W − 1 = 2W − 1` 被超过。因此界限 `L ≤ peak + W − 1` 在
操作上表征*瞬态*情况；在持续漂移情况下，*在漂移期间*不发生
recovery transition，且属性在捕获的跟踪上空虚地成立。

**推论 2（结构合理性）。** 在正确实现的大小为 `W` 的滑动窗口
下，在 recovery transition 上 `L > peak + W − 1` 的跟踪是不可
能的。验证器的 `RLBViolation` 因此也作为窗口实现的结构完整性
检查。

### 6.4 操作紧致性检查

drift-then-recovery smoke（`closed_loop_smoke_with_recovery.py`）
被设计为在生产常数（`N = peak = 7`，`W = 32`）下展示 恢复延迟界限：

```
L_observed = 38 = 7 + 32 − 1 = peak + W − 1.
```

集成测试
`tests/integration/test_closed_loop_smoke_with_recovery.py`
断言 recovery transition 在周期 39 准确触发，而不是更早或更
晚。因此 smoke 是界限*可达*的见证 —— 即 恢复延迟界限 在瞬态情况下
是紧致的。

### 6.5 范围和限制

恢复延迟界限 适用于参考校准器 `MahalanobisDowngradePolicy(M, K)`
及其带有结果的二元 dirty/clean 分区的滑动窗口机制。具有 hysteresis、
recency-weighted history 或多带分区的校准器超出范围；它们的恢复
界限需要自己的推导。界限 `peak + W − 1` 仅在瞬态情况下有意义
（`N ≤ W`）；在持续情况下，drift 期间不发生 recovery transition，
属性在捕获的跟踪上空虚地成立直到 drift 结束。

`Rlb.tla` 通过 TLC 在有界抽象模型（`W=4`）上证明定理；unbounded
case 的 TLAPS 证明大纲在
[`docs/proofs/Rlb_unbounded.tla`](../../proofs/Rlb_unbounded.tla)
中，discharge 计划文档化在
[`docs/proofs/TLAPS_roadmap.md`](../../proofs/TLAPS_roadmap.md)
中。将该大纲提升为已验证证明是候选 ADR-0038。

---

## 7. 可重现性表面

总体声明是第三方可以**在不信任生产者的情况下**对捕获的运行验证
属性集。可重现性表面有五层：

1. **内容寻址 MCAP。** SHA-256 计算一次，并加载到每个 property
   report 中。
2. **确定性管道。** ADR-0030（Replay Verification v1）断言下游
   通道 byte-exact 可重现。
3. **纯函数验证器。** 除了读取 MCAP 外没有 I/O；无全局状态；无
   random 源。
4. **Hypothesis property tests。** ~50 个测试，每个属性 200+ 个
   生成的例子。
5. **TLA+ 持续自检。** TLC 在每次推送时运行，并在任何不变式违
   反时阻塞构建。

希望引用 Project Ghost 安全声明的读者可以写：

> Project Ghost v0.2.3 在捆绑的参考 smoke MCAP
> `SHA-256:<hash>` 上满足 BAUD-v1，由
> `ghost verify-properties --mcap closed_loop_smoke.mcap` 从
> `pip install project-ghost==0.2.3` 验证，并另外在抽象模型
> `BaudErur.tla` 的界限 `M=2, K=1, W=3` 处满足 `INV_BAUD`、
> `INV_ERUR`、`INV_PARTITION`，以及在 `Rlb.tla` 的 `W=4` 处满
> 足 `INV_RLB`（恢复延迟界限）。

这就是贡献 C4 的实际应用。

---

## 8. 评估

内部摘要。详细的定量数据（表格、可重现 JSON）请参阅英文版本。

### 8.1 测试、CI 和机械验证

1687 个测试通过，ruff + mypy strict + deptry clean，CI matrix 4
个组合（ubuntu/windows × py 3.11/3.12），3 个 TLA+ 规范在持续 CI
中。

### 8.2 Bug 检测能力（Violation Matrix）

6 个 bug 类别，所有都被未修改的验证器检测到：
`calibrator_no_downgrade` → BAUD-v1；
`calibrator_invents_confidence` → MD-v1；
`decision_proceeds_anyway` → BAUD-v1；
`decision_never_proceeds` → ERUR-v1；
`actuation_non_safe_reason` → BAUD-v1；
`fpb_threshold_exceeded` → FPB-v1。

### 8.3 参数化策略评估

9 次运行（3 个策略 × 3 个跟踪长度），所有 5 个属性在所有运行中
成立。验证器在跟踪长度上线性：n=10 时 21 ms，n=200 时 406 ms。

### 8.4 策略无关的验证器、策略参数化的前置条件

在 `MahalanobisDowngradePolicy`、`EWMADowngradePolicy` 和
`PerAxisHysteresisDowngradePolicy` 下运行 smoke，验证器无变化
地处理所有三个 MCAP —— 在**两者**之下：ERUR-v1（参考谓词，
§3.2）和 ERUR-v2（策略参数化，§3.2）：

| 策略 | BAUD | ERUR-v1 | ERUR-v2 | MD | RLB | FPB |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `Mahalanobis(M=4,K=2)` 参考 | OK | OK | OK | OK | OK | OK |
| `EWMA(α=0.5,min=3,thr=0.3)` | OK | **VIOL** | **OK** | OK | OK | OK |
| `PerAxisHysteresis(up=3.0)` | OK | **VIOL** | **OK** | OK | OK | OK |

**矩阵的解读：** ERUR-v1 固定为参考谓词，因此在 EWMA 和
PerAxis 上报告 VIOL —— 但该信号表示"替代策略的行为与参考不
同"，而非"替代策略不安全"。这正是 §3.2 中 v2 lifting 的动机。
**ERUR-v2 在三个策略上都成立**：每个替代策略满足其自身契约：
当其*自身*的漂移准则缺失且 belief 为 KNOWN 时，发出 PROCEED。
ERUR-v2 因此捕获 §2.3 "multi-property output" 列承诺的策略无
关保证。

**实现状态（v0.2.4）。** 两个验证器都作为通用、策略无关的函
数交付。`verify_erur`（v1）使用调用者提供的 `(M, K)` 评估参考
谓词；v0.2.4 中没有变化 —— 绝对向后兼容。`verify_erur_v2`
（v0.2.4 中新增，ADR-0040 已接受）接受
`Mapping[policy_id, Callable[[CalibrationHistory], bool]]` 并
通过上述三个校准器都实现的 `DriftPreconditionProvider`
Protocol 将前置条件委托给每个策略自身的
`drift_precondition` 方法。验证器仍然是 MCAP 上的纯函数。
**上述矩阵在每次 CI 推送中由验证器生成**，而非手工派生；
`docs/paper/scripts/compare_policies.py` 与
`docs/paper/outputs/policy_comparison.json` 一起生成。

### 8.5 Shape-realistic 场景

3 个由 VIO/SLAM 文献启发的剖面（gps_denial、slow_biased_drift、
cascading_failure）。所有 5 个属性在 3 个上都成立。

### 8.6 vs RTAMT 比较：能力矩阵，而非比赛

在尝试 head-to-head 基准测试（脚本保留在
[`benchmark_vs_rtamt.py`](../scripts/benchmark_vs_rtamt.py)）后，我
们决定**不将其视为竞争性比较**：Ghost 和 RTAMT 在同一 trace 上
编码不同的属性，因此判定差异不能确立任一工具的缺陷。我们改为报
告两个工具在同一 MCAP 上发布的**能力**矩阵（RTAMT 0.3.5；Ghost
v0.2.3）：

| 能力 | Ghost v0.2.3 | RTAMT 0.3.5 |
|---|:---:|:---:|
| 原生属性语言 | 针对 MCAP schema 的 Python 谓词 | STL |
| 直接读取 MCAP | 是 | 否（用户提取信号） |
| K-在-W 单一公式 | 是（内在） | 否（需辅助计数器） |
| Robustness 语义 | 否（仅判定） | 是（实值） |
| 任意 STL | 超出范围 | 是（工具目的） |
| Ghost 管道上的 bug 检测 | 系统性（§8.2） | 需要按属性重新编码 |
| 分发 | PyPI + OIDC 签名 wheel | PyPI 源码 |

工具是互补的。**RTAMT 适合用户希望对任意信号声明性 STL 与定量
robustness 时**。**Ghost 适合用户希望对特定监督器使用内容寻址、
schema 感知的 CLI 验证器与 hand-stated 谓词时**。Performance 测
量仅作为数量级报告（Ghost ~23 ms，RTAMT ~0.15 ms + ~20 ms 信号
提取）；这些数字测量不同的事物。

### 8.7 验证器在真实飞行遥测上

> **验证器未经修改地在真实飞行遥测上执行。**
>
> 这是本论文先前版本不得不致歉缺席的那一句话。v0.2.3 让我们能
> 写出它。

**v0.2.3 实际交付：**

- 真实的 PX4 ULog，来自 PX4/pyulog 测试 fixtures
  (`test/sample_log_small.ulg`，~921 KB，PX4 v1.10 时代 SITL 飞行
  日志，BSD-3 by PX4)。bundle 在
  [`docs/paper/data/sample.ulg`](../data/sample.ulg)，SHA-256
  `68d1020f...`。
- 端到端 orchestrator
  ([`project_ghost.adapters.real_ulog_smoke.run_real_ulog_smoke`](../../../src/project_ghost/adapters/real_ulog_smoke.py))，
  通过 `parse_ulog_pose_samples` 读取 ULog，子采样到 10 Hz，驱动
  **未修改**的 Ghost 闭环管道，实化 MCAP，运行 5 个属性验证器。
- CLI driver
  [`docs/paper/scripts/verify_real_ulog.py`](../scripts/verify_real_ulog.py)。
- 3 个集成测试
  [`tests/adapters/test_real_ulog_smoke.py`](../../../tests/adapters/test_real_ulog_smoke.py)
  pin 端到端：pipeline 运行、MCAP byte 确定性、判定精确如表。

**真实 PX4 ULog 上的判定 bundle：**

| 字段 | 值 |
|---|---|
| 提取的姿态样本 | 636 |
| Ghost 周期数 | 71 |
| MCAP SHA-256 | `49fd0a48...720a4591` |
| BAUD-v1 | HOLDS |
| ERUR-v1 | HOLDS |
| MD-v1 | HOLDS |
| RLB-v1 | HOLDS |
| FPB-v1 | HOLDS (fire_fraction = 0.9437) |

**判定的告示。** Orchestrator 使用 ULog 自身的 EKF2 估计同时作
为 belief 和（空虚的）oracle ground truth，因此 all-HOLDS 行作
为 safety claim 是空虚的。非空虚 ground truth（动作捕捉、RTK
GPS、post-flight 优化解）是 ADR-0037 候选；§9 "Sim, not
hardware" 子句对强读保持不变。

**本节确立的内容**，在上述告示明确记录的前提下，是本论文先前
版本无法陈述的结构性事实：

> **验证器未经修改地在真实 PX4 v1.10 飞行遥测上、在 CI 中执
> 行，输出从单个 shell 命令可重现的确定性 MCAP。**

这是本节的 load-bearing 句子 —— 不是判定行。

### 8.8 真实飞行遥测上的判别

§8.7 确立了验证器在真实遥测上*运行*。它本身没有确立验证器在真实
遥测上*捕获*任何东西 —— all-HOLDS 行可以由空验证器产生，正如可以
由正确的验证器产生。本小节弥补这一空缺。

**实验。** 在与 §8.7 **相同的**真实 PX4 ULog 上，我们再运行
闭环管道两次，每次替换**一个**从 §8.2 违规矩阵中逐字导入的
有缺陷组件。融合预言机、MCAP schema、验证器和 ULog 输入与
nominal 运行保持相同；每个有缺陷情况只有一个命名组件不同。

**捆绑真实 PX4 ULog 上的判定差异。** v0.2.4 将实验从两个有缺陷
类别扩展为违规矩阵（§8.2）的全部六个类别。每行替换一个从合成
矩阵逐字导入的命名组件；融合预言机、MCAP schema、验证器和
ULog 输入在各行间保持相同：

| 运行 | 预期违反者 | BAUD | ERUR | MD | RLB | FPB |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| nominal（参考策略） | — | HOLDS | HOLDS | HOLDS | HOLDS | HOLDS |
| `calibrator_no_downgrade` | BAUD-v1 | **VIOLATED** | HOLDS | HOLDS | HOLDS | HOLDS |
| `calibrator_invents_confidence` | MD-v1 | **VIOLATED** | HOLDS | **VIOLATED** | HOLDS | HOLDS |
| `decision_proceeds_anyway` | BAUD-v1 | **VIOLATED** | HOLDS | HOLDS | HOLDS | HOLDS |
| `decision_never_proceeds` | ERUR-v1 | HOLDS | **VIOLATED** | HOLDS | HOLDS | HOLDS |
| `actuation_non_safe_reason` | BAUD-v1 | **VIOLATED** | HOLDS | HOLDS | HOLDS | HOLDS |
| `fpb_threshold_exceeded` | FPB-v1 | HOLDS | HOLDS | HOLDS | HOLDS | **VIOLATED** |

**6/6 类别翻转其预期属性；5/6 隔离。** 唯一非隔离行是
`calibrator_invents_confidence`：膨胀置信度的校准器*同时*违反
MD-v1 和 BAUD-v1，因为对置信度撒谎的校准器同时破坏 Mahalanobis
降级契约（它最直接攻击的属性）和漂移下弃权契约（静止信念仍在
漂移，但校准器不再标记它）。这是真实的共违规，不是验证器
伪影：校准器可能通过多个不变量同时损坏下游行为，验证器报告
两者。

**可重现性。** 从 `pip install 'project-ghost[adapters]==0.2.4'`
端到端可运行：

```
python docs/paper/scripts/verify_real_ulog_discriminate.py \
    --ulog docs/paper/data/sample.ulg \
    --out-dir docs/paper/outputs/real_ulog_discrim
```

退出代码为 0 当且仅当每个有缺陷类别翻转其预期属性。六个集成
测试在 CI 中固定该实验
（`tests/adapters/test_real_ulog_discrimination.py`）。

#### 8.8.1 推广到 3-ULog 语料库

§8.8 的结果建立在*一个* PX4 SITL ULog 上。这是审稿人对此类
结果最常见的攻击，v0.2.4 通过将实验扩展为**三个结构上不同的
PX4 ULog 语料库**直接解决，取自 PX4 公开测试 fixture（BSD-3，
license-clean，无需我们居中即可重现）：

| ULog | Pose 样本 | 持续时间 | FPB `fire_fraction` |
|---|---:|---:|---:|
| `sample.ulg`（§8.8 锚点） | 636 | 6.5 s | 0.9437 |
| `corpus/sample_appended.ulg`（多段） | 1110 | 112.6 s | 0.9800 |
| `corpus/sample_logging_tagged.ulg`（logging-tagged） | 1268 | 10.1 s | 0.0000 |

语料库故意跨越 16× 持续时间范围，并包含一个日志
（`sample_logging_tagged.ulg`）其记录段**大部分静止** ——
`fire_fraction = 0.00` 意味着静止信念从未观察到与记录 GT 的
漂移。我们没有过滤该日志：语料库是 PX4 公开测试集 as-shipped，
而手工挑选每个属性都触发的日志的论文按定义就是 cherry-picked。

**语料库检测矩阵**由 CI 在每次推送时重新生成，并作为
[`docs/paper/outputs/multi_ulog_discrimination/matrix.json`](../outputs/multi_ulog_discrimination/matrix.json)
发出（自描述 —— `schema_version`、每 ULog 诊断、两个矩阵）。
YES = 验证器在该 ULog 上翻转预期属性；NO = 该属性在 nominal 和
buggy 之间均保持 HOLDS：

| Bug 类别 | `sample.ulg` | `sample_appended.ulg` | `sample_logging_tagged.ulg` |
|---|:---:|:---:|:---:|
| `calibrator_no_downgrade` | YES | YES | **NO** |
| `calibrator_invents_confidence` | YES | YES | YES |
| `decision_proceeds_anyway` | YES | YES | **NO** |
| `decision_never_proceeds` | YES | YES | YES |
| `actuation_non_safe_reason` | YES | YES | **NO** |
| `fpb_threshold_exceeded` | YES | YES | **NO** |

**诚实解读：18 个单元中 12 个判别。** 在两个**活跃** ULog 上
（`fire_fraction > 0.9`），矩阵全绿 —— 每个 ULog 上六个类别中
有六个翻转预期属性，并具有与 §8.8 相同的单一共违规行。在
**静止** ULog 上（`fire_fraction = 0.00`），六个类别中有四个
在 nominal 和 buggy 之间报告 HOLDS。

这是**有信息的非判别**，不是验证器失败。四个全 HOLDS 类别
（`calibrator_no_downgrade`, `decision_proceeds_anyway`,
`actuation_non_safe_reason`, `fpb_threshold_exceeded`）共享
一个前置条件：BAUD-v1 漂移信号必须至少触发一次。在代理大部分
静止且静止信念从未偏离 GT 的日志上，该前置条件对 nominal 和
buggy 均空真满足，属性正确地对两者报告 HOLDS。其余两个
（`calibrator_invents_confidence`, `decision_never_proceeds`）
不要求漂移信号触发 —— 无论是否观察到漂移，校准器都膨胀置信度，
never-PROCEED 策略也违反 ERUR-v1 的 "K 个失效周期后释放" 分支。
这些在所有三个 ULog 上都正确翻转。

因此验证器**确实做了它声称要做的事**：它精确地标记 ULog 实际
触发其前置条件的生产者 bug。更精致的结果将过滤语料库或从
独立参考获取漂移；我们在此报告诚实矩阵，并将"独立 GT 源"
缓解推迟到 ADR-0037（v0.2.4 部分覆盖 SITL 语料库，v0.2.5
完全关闭）。

**可重现性。** 运行
`python docs/paper/scripts/run_multi_ulog_corpus.py` —— 发出
`docs/paper/outputs/multi_ulog_discrimination/matrix.json`，
若活跃 ULog 不变式回归则以非零退出码退出。六个集成测试
（`tests/adapters/test_real_ulog_corpus.py`）固定矩阵形状、
活跃 ULog 不变式、静止 ULog "SITL GT 自动检测" 不变式
（§8.8.2）和 JSON 工件 schema。

有缺陷的替换在策略层；没有任何 buggy 运行飞行。推广到
**非 PX4** 飞行栈（ROSBag、ArduPilot、EuRoC）仍是 ADR-0037
路线图的范围。

#### 8.8.2 独立 GT 关闭静止 ULog gap

§8.8.1 报告在 `sample_logging_tagged.ulg` 上验证器对 4/6 buggy
类别返回 HOLDS —— 有信息的非判别，因为 BAUD-v1 的漂移前置
条件从未在该 ULog 触发。该行就是 §8.8.2 在 v0.2.5 中关闭的
残留 gap。

**§8.8.1 在该 ULog 上为何空真。** 闭环管道计算
`divergence = predict(belief) − ground_truth`，而 GT 流从
*同一* ULog 的 `vehicle_local_position` topic 重建 —— 即代理
自己的 EKF2 估计。在静止段，EKF2 估计几乎不动（报告的
x-range ≈ 2 mm），静止信念几乎不偏离。验证器对任何前置条件
要求观察到漂移的属性正确报告 HOLDS，但 GT 信号**按构造与
代理的融合自洽** —— 实验无法证伪代理。

**§8.8.2 改变了什么。** `sample_logging_tagged.ulg` 携带
`vehicle_local_position_groundtruth` + `vehicle_attitude_groundtruth`，
由 PX4 SITL 模拟器直接发出，**与 EKF2 独立**。该 ULog 上的 GT
姿态 x-range ≈ 33 mm —— EKF2 隐藏了悬停设定点附近的次厘米
振荡。v0.2.5 添加 `project_ghost.adapters.px4_ulog.GroundTruthSource`
和一个自动检测器，当 GT topic 存在时将 ULog 从 `EKF2_FALLBACK`
切换到 `SITL_SIMULATOR`。位姿适配器、验证器和 MCAP schema
未改变；只有 GT 源翻转。

**同一静止 ULog，同一 buggy 组件，同一验证器的 A/B：**

| 指标 | `EKF2_FALLBACK` (v0.2.4) | `SITL_SIMULATOR` (v0.2.5) |
|---|---:|---:|
| FPB `fire_fraction` | 0.0000 | 0.8585 |
| 判别类别数 | 2 / 6 | **6 / 6** |
| `all_discriminate` | False | **True** |

§8.8.1 中 4 个空真 HOLDS 的类别在独立 GT 下都正确翻转。已经
工作的两个继续工作。

**刷新的语料库矩阵。** 启用自动检测后，语料库矩阵全绿
（**18/18 单元判别**，`all_discriminate=True`）。15/18 隔离；
3 个非隔离单元全是 `calibrator_invents_confidence`，与 §8.8
的 BAUD-v1 ∧ MD-v1 共违规行相同。3 个 ULog 中的 2 个仍使用
`EKF2_FALLBACK`（`sample.ulg`、`sample_appended.ulg` 没有 SITL
GT topics），但它们的飞行*不*静止
（`fire_fraction` ≈ 0.94 / 0.98），所以即使在循环 GT 下前置
条件也会触发。

**审计轨迹。** `matrix.json` 工件带有每 ULog 的
`groundtruth_source` 字段（`"sitl_simulator"` 或
`"ekf2_fallback"`）；每个 verdict bundle 上的
`RealULogSmokeSummary` 携带相同信息。审稿人可以 `grep` JSON
验证哪些单元使用独立 GT，哪些回退到代理自己的估计。将
`ekf2_fallback` 行视为"已验证"是 §8.8.2 结果可能被误读的唯一
方式；显式字段使该误读无法静默发生。

**§8.8.2 尚未关闭什么。** 两个诚实的限制：

- `sample.ulg` 和 `sample_appended.ulg` 没有 SITL GT topics。
  它们全绿列依赖于飞行本身在 EKF2 fallback 下触发漂移前置
  条件；如果未来维护者在 `sample.ulg` 的静止变体上重新运行
  §8.8.2，这些列将回退到空真 HOLDS。
- SITL GT 独立于 EKF2 但不独立于模拟器物理。未来 ADR-0037
  贡献者关闭真实硬件飞行将从动作捕捉或 RTK GPS 获取 GT；
  enum 已枚举那些槽，尽管只实现了 `SITL_SIMULATOR`。

**可重现性。** 重新运行
`python docs/paper/scripts/run_multi_ulog_corpus.py` —— 自动
检测是默认。六个 smoke-A/B 测试
（`tests/adapters/test_real_ulog_smoke_gt_source.py`）固定
`fire_fraction` 定量提升、自动检测结果和 SITL-on-real-only-log
错误情况。六个适配器测试
（`tests/adapters/test_px4_ulog_groundtruth.py`）固定
`detect_groundtruth_source`、解析的 GT 样本的时间顺序不变式、
单位范数四元数不变式和捆绑语料库 GT 可用性 fixture。

### 8.9 跨副本和跨机器决定论

由 CI 与 matrix ubuntu+windows 强制执行，diff 化 MCAP 和规范化
JSON 的 SHA-256。

---

## 9. 限制和效度威胁

我们明确列出限制，与 ADR 的每属性 §Scope 部分本着相同精神。

- **Sim，非硬件。** 这里验证的 MCAP 来自模拟的过自信陷阱，而非
  真实飞行日志。
- **仅参考策略。** TLA+ 证明和属性语义针对特定的参考策略。每个
  非参考策略都需要自己的 ADR、自己的验证器专门化和自己的 TLA+
  规范。
- **TLC 有界。** TLA+ 证明在小常数下的有限状态空间上是穷尽的；
  生产规模常数下的行为依赖于 property tests，而非 TLA+ 证明。
- **Python↔TLA+ bridge 由检查完成。** Python 代码与 TLA+ 定义
  之间的未来差异可能默默地削弱声明。缓解：在每次参考校准器或
  决策策略更改时审查并重新运行 TLC。
- **统计 FPB 超出范围。** FPB-v1 是观察性的；带 Monte Carlo 界
  限的统计 FPB-v2 是未来 ADR 候选。
- **静止 ULog 上的空真 HOLDS（v0.2.5 为 SITL 关闭，硬件仍开放）。**
  §8.8.1 报告静止 ULog 上 EKF2 循环 GT 对 4/6 类别产生空真
  HOLDS。§8.8.2 通过对任何携带 `vehicle_*_groundtruth` topic
  的 ULog 自动检测独立 SITL GT track 来关闭该 gap —— 刷新的
  语料库矩阵为 18/18 绿色。剩余诚实 gap：对于没有 SITL GT
  topic（也没有外部参考）的真实硬件 ULog，管道仍回退到 EKF2，
  存在同样的空真 HOLDS 风险。`RealULogSmokeSummary` 的
  `groundtruth_source` 字段暴露了 fallback，使审稿人不会将其
  误认为验证；动作捕捉 / RTK GPS GT 源在 enum 中枚举但未实现。

---

## 10. 未来工作

- **ADR-0037（进一步解决，v0.2.5）**：真实飞行数据集成。
  v0.2.4 交付 PX4 ULog adapter 和 3-ULog SITL 语料库
  （§8.8.1）。v0.2.5（§8.8.2）交付 `GroundTruthSource` enum
  + 自动检测器，关闭携带 SITL GT topic 的任何 ULog 的静止
  ULog 空真 HOLDS gap —— 语料库矩阵现在是 18/18 绿色。
  开放：动作捕捉和 RTK-GPS 在 enum 中枚举但未实现；
  ROSBag / EuRoC MAV adapter 和非 PX4 栈仍待开放。
- **ADR-0038（候选）**：恢复延迟界限 unbounded 版本和分区定理的
  TLAPS 证明。
- **ADR-0039（候选）**：基于 Monte Carlo 对经验 fire rate 的统
  计 FPB-v2 界限。
- **ADR-0040（已接受，v0.2.4）**：基于
  `policy.drift_precondition(history)` 抽象陈述的 ERUR-v2。
  在 v0.2.4 中作为
  `project_ghost.properties.erur_v2.verify_erur_v2` 以及
  `DriftPreconditionProvider` Protocol 交付；三个策略
  （Mahalanobis、EWMA、PerAxisHysteresis）都实现该 Protocol。
  由 `tests/properties/test_erur_v2_property.py` 测试。
- **HAL backend campaign**：硬件后端（Pixhawk + companion）。
- **Conformance suite** 用 HAL 合约填充 pytest `conformance`
  marker。

---

## 11. 结论

**自主代理应当对其自身的认识论姿态有可验证的契约，并且这些
契约应当作为第三方可以证伪的可执行引用进行交付。** 这是本论
文存在所要捍卫的 load-bearing 命题。

认识论安全契约是与 STL 风格的关于信号的谓词以及 POMDP 风格
的 belief monitoring 相邻但不同的属性类（§1.2）：它们验证代
理必须满足的关于如何与自身不确定性相关的义务 —— 降级、恢复、
约束、行动。Project Ghost 为参考自主性监督器交付五个这样的
契约（BAUD、ERUR、MD、RLB、FPB），将每个契约与内容寻址的运
行和纯函数验证器一起打包为可执行的安全引用，并演示验证器在
真实 PX4 飞行遥测上对命名回归进行判别（§8.8）。

我们*不*声明的内容：认识论契约包含 STL 或 shielding（它们回
答不同的问题）；这是契约的最大集合（FPB-v1 可以收紧，关于
sensor-fusion 来源或执行预算的契约尚未编写）；我们对该术语拥
有独占许可声明（它与 epistemic-logic、
doxastic-logic 和 self-assessment 社区使用相邻词汇的方式有重
叠）。

我们*确实*声明的内容：该 framing 在操作上是可辩护的 —— 工件
可从 `pip install project-ghost==0.2.3` 重新运行；真实 PX4
飞行遥测上的判定可从单个 shell 命令重现；被引用的工件*就是*
证伪机制。

---

## 参考文献

与英文版本相同的 18 个参考文献。为避免重复和漂移，请参阅
[`docs/paper/project_ghost_v0_2.md` § References](../project_ghost_v0_2.md#references).

## 工件索引

与英文版本相同的工件集（ADRs、TLA+ 规范、验证器、可重现性脚本、
测试、CI 工作流、citation 文件）。规范列表见
[`docs/paper/project_ghost_v0_2.md` § Artifact index](../project_ghost_v0_2.md#artifact-index).
