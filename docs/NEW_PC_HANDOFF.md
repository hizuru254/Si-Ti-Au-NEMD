# 新电脑交接文档：Si/Ti/Au/Ti/Si NEMD（WSL2 + 96 核）

> **[历史文档]** 这是 2026-11-12 迁移时的交接说明，其中的路径/工具名多数已被取代。
> 当前状态请看 `docs/HANDOFF_STATE.md`，执行依据看 `AGENT_MANUAL_V6_WSL.txt`。
>
> 这份文档写给**新电脑上的 AI Agent**。它没有本项目的聊天历史，也没有旧工作文件。
> 先完整读本文，再读仓库里的 `README.md`、`AGENT_MANUAL_V5_WSL.txt`、
> `docs/AUTONOMOUS_LOOP.md`，然后按“阶段 0–2”执行；**不要直接开跑长任务**。

---

## 0. 你的角色与硬边界

- 你负责在这台 WSL2 / 96 核机器上继续一个已经跑了多轮的 NEMD 项目。
- **不改物理**：不改势函数、不改层序、不改热流、不改几何定义。
- **不改阈值**：不改 `qc_check.py`、`params.json` 里的判据。
- **不造数据**：QC FAIL 就写 FAIL；不要把预测值写进 `tbr_result.csv`。
- **不覆盖旧 run**：新建 run 版本；旧 run 留作证据。
- 不确定就停下来写报告，不要猜。

项目仓库（公开）：

```text
https://github.com/hizuru254/Si-Ti-Au-NEMD
```

本机路径：`/home/cc/si_nemd`（如果实际文件直接放在 `/home/cc`，先看第 2 节）。

---

## 1. 项目现状（截至 2026-11-12，必须知道）

目标：用 LAMMPS NEMD 算 Si/Ti/Au/Ti/Si 叠层的界面热阻 TBR，并把流程做成
可复现、可审计、可自动搜索的框架。

已完成：

- G0–G6 门控流水线、哈希锁定、三种子、QC、报告、ledger；
- 参数化几何生成器 `tools/build_geometry.py`；
- 批量调度 `tools/scan_runner.py`、GP/EI 提议 `tools/optimize.py`、候选报告；
- 中英双语文档、公开仓库。

最近三次锚点结果（**都 FAIL，不要重复**）：

| 版本 | 体系 | 结果 | 失败原因 |
|---|---|---|---|
| v1.0 | Ti 20 Å，36,072 原子 | QC FAIL | Ti 侧两个界面共用同一段 16 Å 窗口，四界面不可辨识；已加 Q9 检查 |
| v1.1 | Ti 40 Å，45,880 原子，bin 2 | QC FAIL | 温度从 300→421 K，势能降 674 eV；NVT 40 ps 没平衡够 |
| v1.1-relaxed | 用上一轮 final.data 再跑 20k+40k | QC FAIL | 温度已稳（5.4 K），但 R² 只有 0.07–0.86，时间收敛 29% |

关键诊断（新电脑上要接着验证/解决）：

1. **45.9k 原子、40 Å 层太薄**：即使体相 Si/Au，温度剖面也不线性；
   40 Å 小于 Si 声子平均自由程，线性外推 TBR 的前提不成立。
2. **Ti 已扩散进 Si 约 10 Å**：强 LJ 的 Ti–Si 界面没有保持尖锐；
   这是化学/势函数问题，不是再跑久一点能解决的。
3. 因此下一步不是“再跑 3 seed × 120k”，而是：
   - 先在这台 96 核机器上验证环境与 MPI；
   - 做 **长度收敛**（1× / 2× / 4× 层厚，1 seed，短生产），看 R² 是否随厚度改善；
   - 如果 4× 仍不线性，停止并报告，不要继续加长。

---

## 2. 先找到项目

WSL 里执行：

```bash
cd /home/cc
ls -la
```

分三种情况：

### A. 已有 `/home/cc/si_nemd`

```bash
cd /home/cc/si_nemd
git status
git log --oneline -5
git pull
```

最新提交应包含：

- `feat: v1.1 Ti40 anchor, Q9 window-overlap check, pilot launcher`
- `feat: relaxed-structure pilot launcher for v1.1`

如果 `git log` 里没有 Q9 / v1.1，说明副本太旧：不要在原地改，按 B 重新 clone。

### B. 没有 `si_nemd`，文件直接堆在 `/home/cc`

先 `ls -la /home/cc` 看清楚，**只移动项目文件**（`tools/ config/ templates/ examples/ docs/ validation/ anchor/ README.md AGENT_MANUAL_*.txt` 等），不要移动家目录里其他东西：

```bash
mkdir -p /home/cc/si_nemd
# 确认后再移动，不要用 mv * 盲移
```

然后按 C 拉最新代码。

### C. 重新 clone（推荐，保证代码最新）

```bash
cd /home/cc
git clone https://github.com/hizuru254/Si-Ti-Au-NEMD.git si_nemd_repo
```

用 `si_nemd_repo` 作为代码根；旧的 `si_nemd` 里的 run 数据保留，不要删。

---

## 3. 阶段 0：只检查，不跑 MD

先报告以下输出，不要启动任何 LAMMPS：

```bash
cd /home/cc/si_nemd   # 或 si_nemd_repo
pwd
git log --oneline -5
lmp -h | head -20
lmp -h | grep -iE "MANYBODY|MEAM|EXTRA-PAIR|MOLECULE"
mpirun --version
mpiexec -n 4 hostname
python3 -V
python3 -c "import numpy; print(numpy.__version__)"
```

期望：

- `lmp` 有 MANYBODY / MEAM / EXTRA-PAIR（MOLECULE 可选）；
- `mpiexec -n 4 hostname` 能打印 4 行，不报错；
- Python ≥3.10，numpy 可导入。

如果 MPI 不通，先修 MPI；**不要用串行硬跑长度扫描**。

### 3.1 找势函数

```bash
find /home/cc /usr /opt -name "Si.tersoff" -o -name "Au_u3.eam" -o -name "Ti.meam.spline" 2>/dev/null
```

如果找不到，从 Windows 的 `D:\LAMMPS\Tersoff` 复制到 WSL：

```bash
mkdir -p /home/cc/si_nemd/potentials
cp /mnt/d/LAMMPS/Tersoff/Si.tersoff \
   /mnt/d/LAMMPS/Tersoff/Au_u3.eam \
   /home/cc/si_nemd/potentials/
# Ti.meam.spline 仅纯 Ti 体校验用，界面模型不用它
```

### 3.2 改路径（必须改，否则 preflight 必失败）

仓库里的 Windows 绝对路径不能直接用。需要改：

- `config/params.json` 的 `lammps.exe`、`potentials_dir`；
- `anchor/potentials.in` 里 `"D:/LAMMPS/Tersoff/..."`；
- `anchor/potentials.lock.json` 的 SHA256（改文件后必须重算）。

建议用 Python 改 JSON/文本，不要用正则乱替换。改完跑：

```bash
python3 tools/preflight.py \
  --config anchor/params.anchor11.json \
  --geom structures/ANCHOR11.geom.json \
  --structure structures/ANCHOR11.data \
  --potentials anchor/potentials.in \
  --dry-run
```

要求 `结果: READY errors=0`。如果 `structures/ANCHOR11.data` 不存在，用生成器：

```bash
python3 tools/build_geometry.py \
  --scan-id ANCHOR11 --kind flat \
  --t-nm 4.0 --ti 40 --si 40 --bin 2 --status APPROVED \
  --out-structure structures/ANCHOR11.data \
  --out-geom structures/ANCHOR11.geom.json
```

Q9 会检查不同界面窗口不重叠；v1.1 应通过。

### 3.3 把 MPI 写进配置

复制一份 `anchor/params.anchor11.json` 为 `anchor/params.anchor11_mpi.json`，改：

```json
"lammps": {
  "launch_mode": "mpi",
  "mpi_ranks": 16,
  "omp_threads": 1
}
```

先不要用 96 全核；16 ranks 跑通，再做扩展测试。

---

## 4. 阶段 1：1 seed 短测 + MPI 扩展

### 4.1 串行 selftest（可选，但建议）

```bash
python3 tools/selftest.py
```

期望 `[SELFTEST] PASS`。如果它写死了 Windows 路径，先修路径再跑。

### 4.2 1 seed 短测（20k 平衡 + 20k 生产）

用 `anchor/params.anchor11_mpi.json` 再复制一份 `anchor/params.mpi_test.json`：

- `seeds: [1001]`
- `n_equil_steps: 20000`
- `n_prod_steps: 20000`
- `chunk_bin_A: 2.0`
- `launch_mode: "mpi"`，`mpi_ranks: 16`

然后：

```bash
cat > anchor/scan_mpi_test.csv <<'CSV'
scan_id,kind,W_nm,D_nm,P_nm,t_nm,phi_deg,sided,status,note
MPITEST,flat,0,0,0,4.0,0,single,pending,mpi smoke test
CSV

python3 tools/new_run.py \
  --config anchor/params.mpi_test.json \
  --scan-id MPITEST \
  --geom structures/ANCHOR11.geom.json \
  --structure structures/ANCHOR11.data \
  --potentials anchor/potentials.in \
  --scan-csv anchor/scan_mpi_test.csv

# 记下 RUN_DIR，然后
bash tools/run_seed.sh <RUN_DIR> 1001
python3 tools/postprocess.py --run-dir <RUN_DIR> --seed seed_1001
python3 tools/qc_check.py --run-dir <RUN_DIR>
```

1 个种子的 QC 会因 `n_valid_ge_3` 失败，这是预期的；看 `qc.json` 的
`per_seed.seed_1001` 和 `result.json` 的 R²/温度/时间收敛，不要把“种子数不足”
当成物理失败。

检查：

- `run_meta.json` 的 `launch_mode=mpi`、`mpi_ranks=16`；
- 日志无 `ERROR`、无 `Lost atoms`；
- `report.txt` 的 R² / 温度漂移 / TBR 与 Windows `run_v006` 同量级；
- 记录 16 ranks 的 wall time。

### 4.3 MPI 扩展性

用同一个短测，分别 1 / 8 / 16 / 32 ranks 各跑一次（可只跑 5k 步），记录 wall time，
确认加速比合理；**不要一上来 96 ranks**，先确认绑定/线程设置。

---

## 5. 阶段 2：长度收敛（本阶段的核心）

> **先不要跑。** 先把阶段 0–1 的报告发回给人类，确认 MPI 和短测没问题后再做。
> 以下是准备步骤，供人类批准后执行。

### 5.1 生成 1× / 2× / 4× 三个 flat 结构

保持面内 65.16 Å，层厚整体放大：

| 点 | Si | Ti | Au (t) | 约原子数 |
|---|---|---|---|---|
| L1 | 40 | 40 | 40 | 45.9k |
| L2 | 80 | 80 | 80 | 91.8k |
| L4 | 160 | 160 | 160 | 183.6k |

命令模板（每个点一次）：

```bash
python3 tools/build_geometry.py \
  --scan-id L2 --kind flat \
  --t-nm 8.0 --ti 80 --si 80 --bin 2 --status APPROVED \
  --out-structure structures/L2.data \
  --out-geom structures/L2.geom.json
```

> 人类批准这次长度扫描后，status 才可写 APPROVED，note 写
> `human-approved length scan 2026-11-12`；未获批准就保持 DRAFT，等 H1b。
> Q9 必须通过。

### 5.2 每个点跑 1 seed、40k 平衡 + 40k 生产

参数：`seeds: [1001]`、`n_equil_steps: 40000`、`n_prod_steps: 40000`、
`chunk_bin_A: 2.0`、`launch_mode: mpi`、`mpi_ranks` 16（L4 可 32）。

流程：`new_run → run_seed → postprocess → qc_check`。

记录：

- 原子数、ranks、wall time；
- 每侧最小 R²；
- 时间收敛（前后半段差）；
- 温度漂移；
- TBR；
- Ti 的 z 范围 vs Si 边界（是否仍互混 10 Å）。

### 5.3 判定

- R² 随 L1→L2→L4 明显上升并接近 0.995 → 长度是主因，选最大可行尺寸，
  再考虑 3 seeds × 120k；
- R² 仍 <0.995，且 Ti 仍扩散 → **停止**，不要继续加长；
  报告“有限尺寸 + Ti–Si 互混”是主因，需要真实 Ti–Si 势或换提取方法。

---

## 6. 报告格式（每次停下都按这个发）

```text
阶段：
机器/环境：Ubuntu 22.04, lmp 版本, MPI 版本
代码：commit hash
配置：params 文件、potentials 路径、ranks
结果：原子数 / wall time / R²(min) / 时间收敛 / 温度漂移 / TBR / QC
异常：ERROR / Lost atoms / 警告
下一步建议：
```

附上 `preflight` 输出、`report.txt`、`qc.json`、`run_meta.json` 的路径或内容。

---

## 7. 明确不要做的事

- 不要直接跑 `run_v11_full.bat`（那是 Windows 的；WSL 用 `run_seed.sh`）。
- 不要在 45.9k 原尺寸上跑 3 seeds × 120k；已知会 FAIL。
- 不要改 `qc_check.py` 的阈值、不要放宽 R²/时间收敛。
- 不要把 `final.data` 当成“已平衡”直接生产；它只是上一轮的松弛快照。
- 不要删除旧 run；不要覆盖 `run_vNNN`。
- 不要用中文路径；`/home/cc/si_nemd` 是 ASCII，保持。

---

## 8. 参考文件

- `README.md`：项目结构、状态、命令；
- `AGENT_MANUAL_V6_WSL.txt`：本机实测的操作手册（取代 V5）；
- `docs/AUTONOMOUS_LOOP.md`：H0/H1a/H6 门禁与搜索设计；
- `anchor/params.anchor11.json`：v1.1 参数（3 seeds，40k+120k，bin2）；
- `anchor/potentials.in`：Si Tersoff / Au EAM / Ti 与界面 LJ；
- `structures/ANCHOR11.geom.json`：v1.1 几何（Ti40，界面 ±60/±20）。
