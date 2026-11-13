# 新机器接管：从 clone 到 READY（30 分钟）

> 目标读者：**没有本项目历史**的新 Agent 或师兄。
> 5 分钟读完，按顺序执行即可复现锚点。任何一步输出与这里写的不同，先停下来查，不要往下走。

## 0. 前置条件

Linux/WSL2（Ubuntu 22.04 实测），需要：
- LAMMPS，**带 MANYBODY / MEAM / EXTRA-PAIR 包**（本机是 29 Sep 2021 Update 2，`/usr/bin/lmp`）
- Open MPI（本机 4.1.2）
- Python ≥3.10 + numpy（本机 3.10.12 / 1.21.5）
- Git

## 1. clone

```bash
git clone https://github.com/hizuru254/Si-Ti-Au-NEMD.git si_nemd
cd si_nemd
```

## 2. 改三处路径（唯一必须手改的地方）

```bash
# a) params 里的 LAMMPS 可执行文件
python3 - <<'PY'
import json
p = json.load(open("anchor/params.v16.json"))
p["lammps"]["exe"] = "$(which lmp)"
print(p["lammps"]["exe"], p["lammps"]["launch_mode"], p["lammps"]["mpi_ranks"])
PY
```

- `anchor/params.v16.json` 与 `anchor/params.v16_scan.json` 里的 `lammps.exe`（默认 `/usr/bin/lmp`）
- 若 LAMMPS 版本不是 29Sep2021，同步改 `lammps.version_marker`
- 势函数路径**已经是仓库相对路径**（`../../../../potentials/...`），不用改

## 3. 自检

```bash
python3 tools/selftest.py          # 期望 [SELFTEST] PASS（Cu 玩具，3 seeds）
```

若报找不到 `Cu_u3.eam`，改 `_cu_eam()` 里的候选路径。

## 4. 生成结构 + 过 G0

```bash
python3 tools/build_geometry.py --scan-id F000 --kind flat --t-nm 4.0 \
  --ti 40 --si 40 --bin 2 --res-inset 8 --status APPROVED \
  --out-structure structures/F000.data --out-geom structures/F000.geom.json

python3 tools/preflight.py --config anchor/params.v16.json \
  --geom structures/F000.geom.json --structure structures/F000.data \
  --potentials anchor/potentials.in --dry-run
```

期望最后一行：`结果: READY   errors=0 warnings=0`。
（`structures/` 不在仓库里，必须自己生成；这是唯一的"缺文件"。）

## 5. 跑一个 150 ps 锚点（约 45 min 单 job / 25 min 双 job）

```bash
python3 tools/new_run.py --config anchor/params.v16.json --scan-id F000 \
  --geom structures/F000.geom.json --structure structures/F000.data \
  --potentials anchor/potentials.in --scan-csv anchor/scan_v16_scan.csv

MPIRUN_EXTRA="--cpu-set 0-23" bash tools/run_seed.sh anchor/workspace/run_vNNN 1001

python3 tools/postprocess.py     --run-dir anchor/workspace/run_vNNN --seed seed_1001
python3 tools/tbr_plane.py       --run-dir anchor/workspace/run_vNNN --seed seed_1001
python3 tools/tbr_global_fit.py  --run-dir anchor/workspace/run_vNNN --seed seed_1001
python3 tools/qc_check.py        --run-dir anchor/workspace/run_vNNN
```

期望（本机实测，45880 原子，24 ranks）：
- wall time ≈ 2500 s，`exit_code=0`，无 `Lost atoms`
- 温漂 ≈ +0.9 K，`TotEng` 漂移 ≈ 2e-7
- `tbr_plane` ≈ **1.36e-8 m²K/W**（±5%）
- `qc_check` 会 FAIL，且**只**失败在 `fit_quality`（R²）与 `time_converged`
  —— 前者结构性不可达、后者是界面仍在演化，两者都已在 `docs/` 里给出证据，
  **不是流程错误**。

## 6. 想复现扫描

```bash
python3 tools/scan_parallel.py --config anchor/params.v16_scan.json \
  --scan-csv anchor/scan_v16_scan.csv --potentials anchor/potentials.in \
  --space config/search_space.json --workers 4 --ranks 12
python3 tools/rank_plane.py --workspace anchor/workspace --proto 1.6
```

## 7. 三个必须知道的坑

1. **并发 rank 超过 48 会崩塌**（56→7 步/秒、64→3.5，无报错）。多 job 必须用 `MPIRUN_EXTRA` 指定互不重叠的 CPU 集。
2. **不要用 `postprocess.py` 的单一数值对外**：窗口外推对本体系偏低 2.6 倍，用 `tbr_plane.py`。
3. **`-nonbuf` 在 29Sep2021 不存在**；不要加。

## 8. 参考

- `AGENT_MANUAL_V6_WSL.txt` 执行依据
- `docs/RESULTS_SUMMARY.md` 结论
- `docs/HANDOFF_STATE.md` 当前状态
- `reports/evidence/` 两个锚点 run 的原始日志（可核对，不必重跑）
