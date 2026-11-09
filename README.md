# Si/Ti/Au/Ti/Si NEMD Agent Workflow

一套给本地 LLM Agent 使用的 LAMMPS NEMD 执行与取证框架：把“算一个界面热阻”拆成
可校验、可复现、可追责的固定流程，避免 Agent 自行改物理、伪造数据或跳过门禁。

仓库：<https://github.com/hizuru254/Si-Ti-Au-NEMD>（私有）

> **层序（唯一正确顺序，从下到上）**
>
> `Si 衬底 / Ti 粘附层 / Au 中间层 / Ti 粘附层 / Si 顶盖`
>
> 本文档和所有示例均以 `Si/Ti/Au/Ti/Si` 为准。旧版 `Au/Ti/Si/Ti/Au` 是错误层序，已废弃。

> **定位**：本仓库是“执行框架 + 工具链”，不是物理结论。仓库内的验证算例是合成结构，
> 只用于证明流程可执行；真实 TBR 必须用人类批准的几何、势函数和已平衡结构重算。

## 状态

| 项目 | 结果 |
|---|---|
| 几何 v1 | **APPROVED**（2026-11-10）：40/20/40/20/40 Å，界面 ±40/±20 |
| 势函数方案 | Ti-Ti 与跨界面用 **LJ**；Si-Si 用 Tersoff；Au-Au 用 EAM |
| 并行方式 | **串行**（MS-MPI 在本机报 `error 5`，命名管道 / smpd 服务不可用；3.7 万原子约 6.6 h/组） |
| 操作系统 | Windows 11（PowerShell 5.1，无 pwsh 7） |
| LAMMPS | `D:\LAMMPS\LAMMPS 64-bit 4Jul2026-MSMPI\bin\lmp.exe`（4 Jul 2026） |
| 势函数 | `D:\LAMMPS\Tersoff\` 下的 `Si.tersoff`、`Ti.meam.spline`、`Au_u3.eam` |
| 工具链演练 | `tools/selftest.py` **PASS**（Cu 768 原子，QC `n_valid=3`） |
| 三元素验证 | `Si/Ti/Au/Ti/Si` 1856 原子，3 seed × 30000 步，全部 exit 0；QC 按预期 FAIL |
| 形状预览 | 7 个 `Si/Ti/Au/Ti/Si` 初始结构，约 21k 原子，见 `shapes/` |

## 快速开始

```powershell
# 1. 克隆到纯 ASCII 路径（不要放在含中文的目录下）
git clone https://github.com/hizuru254/Si-Ti-Au-NEMD.git D:\si_nemd
cd D:\si_nemd

# 2. 按本机路径修改 config\params.json：
#    lammps.exe / lammps.mpiexec / potentials_dir

# 3. 工具链演练（不消耗真实机时）
$PY = "C:\Users\<you>\...\python.exe"
& $PY .\tools\selftest.py

# 4. 验证工程的前置校验
& $PY .\tools\preflight.py --config .\validation\params.json `
    --geom .\validation\geom.json --structure .\validation\structure.data `
    --potentials .\validation\potentials.in --dry-run
```

自检最后一行应为：

```text
[SELFTEST] PASS: 工具链可执行（物理判据未验证）
```

## 仓库结构

```text
.
├─ AGENT_MANUAL_V5_WIN.txt      # 本机（Windows 原生）已验证手册
├─ AGENT_MANUAL_V5_WSL.txt      # 另一台 WSL2 机器手册（未验证，附差异表）
├─ AGENT_MANUAL_V4.txt          # 已废弃：层序错误的旧版，仅作历史说明
├─ config/
│  ├─ params.json               # 全局参数与阈值（单一事实源）
│  ├─ scan.example.csv          # 扫描队列模板
│  └─ potentials.lock.example.json
├─ templates/in.pattern.template
├─ tools/
│  ├─ geomlib.py                # 几何/数据文件校验
│  ├─ preflight.py              # Gate 0：环境与输入契约
│  ├─ new_run.py                # 建版（原子、不可覆盖）
│  ├─ scan_status.py            # 只改 scan.csv 的 status 列
│  ├─ run_seed.ps1              # 单 seed 启动器（Windows）
│  ├─ run_seed.sh               # 单 seed 启动器（WSL，未验证）
│  ├─ postprocess.py            # 唯一允许的后处理
│  ├─ qc_check.py               # 全部门禁 + CSV + 报告
│  ├─ selftest.py               # 端到端演练（Cu）
│  ├─ build_stack_validation.py # 三元素验证结构（非生产）
│  └─ build_shapes.py           # 形状预览生成器
├─ examples/
│  ├─ geom.SiTiAu.v1.json       # 已确认几何（APPROVED，2026-11-10）
│  └─ geom.SiTiAu.legacy.json   # 旧几何反例
├─ validation/                  # 三元素验证工程（含一次完整运行的证据）
└─ shapes/                      # 7 个形状的 data / PNG / zip
```

## 文档

- [AGENT_MANUAL_V5_WIN.txt](AGENT_MANUAL_V5_WIN.txt)：本机执行手册。包含环境事实、G0–G6 门禁、S0–S9 流程、判据、异常分类、HITL、已实测的势函数接线。
- [AGENT_MANUAL_V5_WSL.txt](AGENT_MANUAL_V5_WSL.txt)：另一台 WSL2 + LAMMPS 29Sep2021 + 96 核机器的差异版。所有未验证命令都标了 `[未验证]`，并附首次上机检查清单。
- [AGENT_MANUAL_V4.txt](AGENT_MANUAL_V4.txt)：**已废弃**。它把层序写成 `Au/Ti/Si/Ti/Au`，不要使用。

## 形状预览

7 个 `Si/Ti/Au/Ti/Si` 初始形状：平面基准、矩形槽、深窄槽、60° 梯形槽、双面槽、45° 斜槽、交叉槽。
每个结构都有 LAMMPS data 文件、截面图和深度图；Ti 在预览中用单层近似表示。

![7 种形状总览](shapes/overview.png)

参数、原子数和 OVITO 打开方式见 [shapes/README_shapes.txt](shapes/README_shapes.txt)。
压缩包：[shapes/SiAu_shapes.zip](shapes/SiAu_shapes.zip)。

## 判据摘要

| 门禁 | 判据 |
|---|---|
| 日志完整 | 退出码 0、无 `Lost atoms`、有 `Total wall time` |
| 能量守恒 | `TotEng` 漂移 ≤ 1%（40–50% vs 90–100% 双窗） |
| 温度信号 | `dT_total > 5 K` |
| 拟合质量 | 每侧 R² ≥ 0.995、≥ 4 点、窗口在单一材料内 |
| 时间收敛 | 前后半段 TBR 偏差 ≤ 5% |
| 种子统计 | 3 个种子全部有效、相对标准差 ≤ 10% |
| 量级检查 | `1e-11 ≤ TBR_total ≤ 1e-7 m²·K/W` |
| 数据溯源 | `manifest.sha256` 覆盖全部输入，日志哈希与 `result.json` 一致 |

`TBR_total = ΣΔT_i / q` 是四个界面的串联总阻；与单界面文献比较时不能直接对等。

## 已知限制

这些是模型层面的限制，不能靠改文档消除：

1. **电子热导缺失**：EAM/Tersoff/LJ 只描述声子。Au 的电子热导占主导，模型严重低估 Au 侧热导，TBR 绝对值不能直接对实验/TDTR。
2. **界面化学缺失**：真实 Ti/Si 会形成硅化物，当前 Ti-Si、Ti-Au 交叉项是 LJ。
3. **Ti 势函数**：本机没有 Ti 的多元素 MEAM；验证结构用 fcc-Ti + LJ。生产需人类定稿。
4. **有限尺寸**：65.16 Å 面内、几十 nm 厚度小于 Si 声子平均自由程，需补长度/截面收敛。
5. **温度定义**：`fix ave/chunk` 的 `temp` 不扣除局域质心速度；有整体滑移时会高估温度，需先确认结构无漂移。
6. **样本量**：n=3 的标准差只是筛查线，不是统计保证。

更多细节见 `AGENT_MANUAL_V5_WIN.txt` 附录 D。

## 验证记录

`validation/workspace/run_v001` 是一次完整运行（3 seed × 30000 步）：

- 三个 seed 全部退出码 0、无 `Lost atoms`，约 97 s/seed（串行）；
- ΔT_total 357–393 K，TBR_total 1.18–1.30×10⁻⁶ m²·K/W；
- QC **FAIL**（R² 0.00–0.70、前后半段差 16–25%），原因是合成叠层的弱界面导致 Au 中间层滑移，不是工具链故障。

## 许可

仓库暂未指定开源协议。如需公开复用，请补充 `LICENSE`（例如 MIT 或 CC-BY-4.0）。
