# 阶段 0–2 执行报告（新机器 WSL2 / 96 核）

- 日期：2026-11-12
- 执行者：接手 Agent（无历史对话，按 NEW_PC_HANDOFF.md 阶段 0–2 执行）
- 结果：**环境与流程打通；物理仍未通过 QC（fit_quality），与 Windows 上的 v1.1 失败同型**

## 1. 环境（阶段 0）

| 项 | 实测 |
|---|---|
| OS | Ubuntu 22.04.5 LTS / kernel 6.18.58.1-microsoft-standard-WSL2 |
| CPU | AMD EPYC 9684X 96-Core, 96 核 1 线程/核，1 NUMA |
| LAMMPS | `/usr/bin/lmp`，29 Sep 2021 - Update 2 |
| 已装包 | MANYBODY / MEAM / EXTRA-PAIR / MOLECULE / KSPACE / MPIIO / PYTHON 等 |
| MPI | Open MPI 4.1.2，`mpiexec -n 4 hostname` 正常 |
| Python | 3.10.12，numpy 1.21.5 |
| 磁盘 | /home 可用 982 GB（阈值 20 GB） |

`tools/selftest.py`：**PASS**（Cu 768 原子 × 3 seed 串行，n_valid=3）。

## 2. 路径 / 势函数 / 哈希（阶段 2）

- 势函数位置：`/home/cc/si_nemd/potentials/{Si.tersoff, Au_u3.eam, Ti.meam.spline}`
  （与 `/usr/share/lammps/potentials/` 副本逐字节相同）
- **哈希交叉验证**：Si.tersoff `5b55dc7b…`、Au_u3.eam `f34555e1…` 与本仓库
  `anchor/potentials.lock.json` 原值**完全一致** → 与 Windows 机器用的是同一批势函数文件。
- 改动（仅路径，不动物理/阈值）：
  - `config/params.json`、`anchor/params.anchor11.json`：`lammps.exe=/usr/bin/lmp`、
    `mpiexec=/usr/bin/mpirun`、`version_marker="LAMMPS (29 Sep 2021"`、
    `potentials_dir=/home/cc/si_nemd/potentials`
  - `anchor/potentials.in`、`anchor/potentials.strong.in`：`D:/LAMMPS/Tersoff/…` →
    `/home/cc/si_nemd/potentials/…`
  - `anchor/potentials.lock.json`：重算 sha256（potentials.in `adbe7d3d…`），status 保持 APPROVED
  - `tools/run_seed.sh`：删除 `-nonbuf`（29Sep2021 不支持该参数，实测
    `ERROR: Invalid command-line argument`）
  - `tools/selftest.py`：Cu_eam 路径改为 `/usr/share/lammps/potentials/Cu_u3.eam`

## 3. 结构 + G0（阶段 2）

`tools/build_geometry.py --scan-id ANCHOR11 --kind flat --t-nm 4.0 --ti 40 --si 40 --bin 2 --status APPROVED`

- 45,880 原子：Si 16,704 / Ti 19,448 / Au 9,728
- 盒子 65.16 × 65.16 × 230 Å，真空两端各 15 Å
- 镜像对称：Si_L 8352 = Si_R 8352；Ti_L 9724 = Ti_R 9724；Au 9,728
- preflight：**READY，errors=0，warnings=0**（Q9 无窗口重叠；hot=cold=1728）
- 报告：`logs/preflight_report.json`

## 4. 短测（1 seed × 20k 平衡 + 20k 生产，16 ranks）

版本：`anchor/workspace/run_v001`（新建，未覆盖任何旧 run）

| 指标 | 值 |
|---|---|
| 原子数 | 45,880 |
| ranks / 线程 | 16 / 1（`--bind-to core`） |
| wall time | 393 s（LAMMPS 自身 6:32）；平衡 101.6 steps/s，生产 103.7 steps/s |
| exit code | 0；无 ERROR，无 Lost atoms |
| TotEng 漂移 | 8.07e-6（阈值 1e-2） |
| 通量对称性 | 2.3%（阈值 5%） |
| dT_total | 94.46 K（阈值 >5 K） |
| TBR_total | 2.503e-8 m²K/W（量级校验通过） |
| 时间收敛 | 前半 2.338e-8 / 后半 2.229e-8，差 4.92%（阈值 5%，**贴边通过**） |
| 温度漂移 | 303.4 → 319.8 K，+16.44 K（阈值 ±25 K） |
| R²(min) | **0.256**（阈值 0.995）→ `fit_quality` FAIL |
| QC | FAIL：`fit_quality` + `n_valid_ge_3`（1 seed 预期） |

分界面 R²（left/right）与 dT：

| 界面 | dT (K) | R²_L | R²_R |
|---|---|---|---|
| Si_Ti_L (-60 Å) | 0.07 | 0.943 | 0.528 |
| Ti_Au_L (-20 Å) | 32.43 | 0.427 | 0.828 |
| Au_Ti_R (+20 Å) | 44.59 | 0.825 | 0.256 |
| Ti_Si_R (+60 Å) | 17.37 | 0.557 | 0.879 |

## 5. MPI 扩展性（同一结构，2500+2500 步，run_v002–v005）

| ranks | 平衡段 loop (2500 步) | steps/s | 相对 1 rank | 每核效率 |
|---|---|---|---|---|
| 1 | 233.68 s | 10.70 | 1.00× | 100% |
| 8 | 45.83 s | 54.55 | 5.10× | 64% |
| 16 | 24.75 s | 101.03 | 9.44× | 59% |
| 32 | 15.62 s | 160.06 | 14.96× | 47% |

全部 exit=0、无 Lost atoms。16 ranks 与主测试吞吐一致（101 steps/s）。

## 6. 异常与观察

1. **温度剖面非单调，且两端梯度反向**：生产第 1000 步起，
   z ∈ [-100,-92] Å（`hot_g` 所在）平均 251 K，z ∈ [92,100] Å（`cold_g`）371 K；
   到第 20000 步为 256 K / 397 K。结构镜像对称、`+eflux` 语义已由源码
   `src/fix_heat.cpp` 确认为加热，且 `f_hot=1.014 / f_cold=-0.991`，所以这不是
   符号错误或几何不对称；**平衡结束时温度场已不均匀**（1 ps 内热流不可能造成 ±50 K）。
   与 Windows v1.1-relaxed（R² 0.07–0.86）同型，说明是模型/平衡度问题，不是新机器问题。
2. **Ti 互混**：生产后 Ti 的 z 范围 -67.1…69.6 Å（初始 ±58.5），即向 Si 侧侵入
   **7–10 Å**，Ti 原子进入 Si 区 670（L）/1193（R）个。与交接文档的诊断一致。
3. **模板 `fix heat` 的 N 参数**：模板用 `${hot_n}`（=1728 个原子）作为 LAMMPS 的
   "每 N 步注入一次"参数，而不是 1。平均通量仍是 1 eV/ps（eflux·N·dt 每 N 步），
   但注入变成每 1.728 ps 一次的 1.728 eV 脉冲。人维护内容，**未改**，仅记录。
4. 其它：`-nonbuf` 在 29Sep2021 不存在（已从 run_seed.sh 移除）；无 WARNING。

## 7. 结论与下一步建议

- 环境、MPI、工具链、哈希锁定、G0、建版、后处理、QC 全部在本机跑通。
- 短测未通过 fit_quality（R² 0.26–0.94），与旧机器一致；需按交接文档阶段 3
  做长度收敛（1×/2×/4×）判断是否为有限尺寸效应。本次**未执行**长度扫描（未获授权）。
- 建议先人工确认：温度场反向梯度是否与平衡不足/自由表面热点有关；
  以及 `fix heat N` 用法是否应改为 1（属物理设置，需人类决定）。
