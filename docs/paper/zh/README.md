# 论文中文版本（内部使用）

本文件夹包含规范英文技术论文
[`docs/paper/project_ghost_v0_2.md`](../project_ghost_v0_2.md)
的中文翻译，供作者和中文母语合作者使用。

## 文件

| 文件 | 用途 |
|---|---|
| [`project_ghost_v0_2_ZH.md`](project_ghost_v0_2_ZH.md) | 论文翻译 |
| `README.md` | 本文件 |

## 差异政策

**英文版本是规范的**。它将提交到 arXiv 并改编为 FMAS 2026 / RV
2027。两个版本之间的任何差异必须以英文版本为准。

何时更新中文版本：

- 当英文版本有重大更新（新章节、贡献重命名、表格重做）时。
- 当中文母语合作者报告翻译错误时。
- 每次发布前（确保引用的版本匹配）。

## 翻译内容

- 解释性散文、动机、范围。
- §8 评估的子节（简化版本；确切数字保留英文，规范表格在英文
  版本中）。
- 第 §1（引言）、§2（背景）、§9（限制）、§10（未来工作）、
  §11（结论）章节 —— 完整翻译。

## 不翻译内容

- 属性名称：BAUD-v1、ERUR-v1、MD-v1、RLB-v1、FPB-v1。
- TLA+ 规范名称：`BaudErur.tla`、`Rlb.tla`、`Fpb.tla`、
  `Rlb_unbounded.tla`。
- 不变式名称：`INV_BAUD`、`INV_ERUR`、`INV_PARTITION`、`INV_RLB`
  等。
- 策略名称：`MahalanobisDowngradePolicy`、`EWMADowngradePolicy`
  等。
- Bash 或 Python 代码片段。
- 代码仓库的文件路径。
- RLB-v1 statement 和证明 —— 逐字复制，仅周围的散文是中文。
- 参考文献 —— 规范英文格式。

## 推荐使用

- **中文母语合作者：** 先读中文版本理解动机，然后读英文版本了
  解定量细节。
- **中文内部演讲：** 用作幻灯片基础；仅在更精确时复制英文。
- **arXiv / FMAS / RV 提交：** 忽略此文件夹。使用
  [`docs/paper/arxiv/`](../arxiv/)。
