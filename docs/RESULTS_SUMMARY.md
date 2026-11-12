# Si/Ti/Au/Ti/Si 界面热阻：2026-11-12 结果总结

> 这份文档汇总在新机器（WSL2 / 96 核 EPYC 9684X）上重做整套 NEMD 流程的结果。
> 所有数字都来自本机实测，原始数据在 `anchor/workspace/run_vNNN/`。
> 与仓库原有结论不一致之处，本文以实测为准并说明原因。

## 1. 一句话结论

流程从"剖面不可信"修到"温度稳定 +0.9 K、能耗守恒 1.8e-7、通量对称 1.5e-5"，
但**这套模型的界面热阻没有唯一值**：三种提取方法相差 2.6 倍，
界面在 300 K 下持续互混（~10 Å），所以既无法给出可信的绝对 TBR，
也无法分辨 <20% 的图案差异。**在当前模型下，没有任何图案优于平面。**

## 2. 修了什么（六条，都有实测证据）

| # | 问题 | 证据 | 处理 |
|---|---|---|---|
| R1 | `fix heat` 的 N 参数被写成组原子数（1728），实际语义是"每 N 步注入一次" | `src/fix_heat.cpp`；通量对称性 2.3% | 改为 `heat 1`，对称性 → 0.0000 |
| R2 | 热源/冷源压在自由振荡的 Si 表面上 | NVT 时表面被加热到 600–750 K | `--res-inset 8`，内移 8 Å |
| R3 | 单一全局 NVT 只约束总动能，消不掉内部梯度 | 100 ps 后两半仍差 57 K | 两半各自 NVT（template v1.3） |
| R4 | `R²≥0.995` 在此体系不可达 | 16 Å 窗内温降 0.2 K，2 Å bin 噪声 1.2 K | 改报 TBR±σ；门禁保留、如实 FAIL |
| R5 | 界面在 300 K 持续弛豫，放热 0.4–1.4 eV/ps，与热流同量级 | PotEng 230 ps 内降 2398 eV | run 内退火 300→700→300 K（v1.6） |
| R6 | 通量刚加上的 0–100 ps 是瞬态 | 前后半段差 30–60% | 80 ps 通量热身，不计入计量段 |

## 3. 当前协议（v1.6）达到什么

一条输入完成：**退火 65 ps → 300 K 平衡 10 ps → 通量热身 80 ps（不计量）→ 计量 150 ps**。

| 判据 | 要求 | 实测 | 结论 |
|---|---|---|---|
| 温度稳定 | ≤25 K | **+0.87 / +0.99 K** | 通过 |
| 能量守恒 | ≤1% | 1.8e-7 | 通过 |
| 通量对称 | ≤5% | 1.5e-5 | 通过 |
| 时间收敛 | ≤5% | 12.6%（flat，1.7σ） | 接近；1.6 ns 长算例在跑 |
| R² | ≥0.995 | 0.1–0.8 | 结构性不可达（R4） |

成本：305k 步，24 ranks，41 min/点；4×12 ranks 并行可跑 8 点。

## 4. TBR 到底是多少：三种方法三角测量

| 方法 | flat，150 ps | 说明 |
|---|---|---|
| `postprocess.py`（16 Å 窗口外推） | 5.33e-9 | 仓库原方法 |
| `tbr_global_fit.py`（全剖面分段线性拟合） | 1.38e-8 | 10 参数，91 个 bin |
| `tbr_plane.py`（固定平面温差，无界面假设） | 1.36e-8 | 取 z=±84 Å |

后两者一致 → **窗口外推偏低 2.6 倍**。原因：Au 层靠界面 8 Å 内梯度 −1.2 K/Å、
中间 20 Å 只有 −0.15 K/Å，层内没有 20 Å 的线性区（Ti 互混把界面抹宽到 ~10 Å）。
**仓库里所有历史 TBR 都带这个偏差**，包括 stage 0–2 报的 2.5e-8。

最强线性响应证据（平面法）：

| 点 | 热流 | TBR_eff |
|---|---|---|
| flat | 1 eV/ps | 1.3567e-8 |
| flat | 3 eV/ps | 1.3569e-8 |

差 0.01% → 1 eV/ps 与 3 eV/ps 在物理上等价，此前的"不一致"全部来自提取方法。

## 5. 图案扫描：没有图案优于平面

先用旧协议快扫 13 点，P350（W=1.2, D=0.6, P=3.5 nm）看似最优（0.60× flat）。
换成平衡协议后：

| 协议 | flat | P350 | 比值 |
|---|---|---|---|
| v1.3 快扫（60 ps，未退火） | 1.03e-9 | 0.61e-9 | 0.60× |
| v1.6（退火 + 热身，平面法） | 1.539e-8 | 1.634e-8 | **1.06×** |
| v1.6 flux 3（平面法） | 1.517e-8 | 1.540e-8 | **1.02×** |

**结论：沟槽不降低热阻，略高 1.5–6%。** 主导热阻是 ~10 Å 的互混层，
图案控制不了它。趋势层面仍可参考：W↑ 使 TBR↓（0.8→2.0 nm，−42%）、
D 有最优（0.4–0.6 nm）、duty>0.8 因 Ti 壁只剩两原子层而失稳、
P 必须取 65.16/n 的共格值（否则周期边界截断沟槽）。

## 6. 模型局限（决定了上限）

1. 无真实 Ti–Si / Ti–Au 势：LJ（ε=0.2–0.3 eV，σ=2.0 Å）没有硅化物化学却极强吸引，
   300 K 下 Ti 持续溶进 Au/Si（200 ps 后 700–790 个 Ti 原子进入 |z|<20 Å）。
2. 界面宽 ~10 Å 且位置偏离名义平面 → Kapitza 式温跳不是良定义量，
   提取方法之间差 2.6 倍。
3. 无电子热导（Au 侧被严重低估）、无硅化物、65 Å 面内小于声子平均自由程。
4. 因此本仓库能给出的只是**同一模型内的相对趋势**，不是可对外的 TBR。

## 7. 复现

```bash
cd /home/cc/si_nemd
# 单点：退火 + 热身 + 计量（v1.6）
python3 tools/build_geometry.py --scan-id X --kind rect --t-nm 4.0 --ti 40 --si 40 \
  --W-nm 1.2 --D-nm 0.6 --P-nm 3.5 --phi 0 --sided single --bin 2 --res-inset 8 \
  --status APPROVED --out-structure structures/X.data --out-geom structures/X.geom.json
python3 tools/preflight.py --config anchor/params.v16.json --geom structures/X.geom.json \
  --structure structures/X.data --potentials anchor/potentials.in \
  --template templates/in.pattern.v16.template --dry-run
python3 tools/new_run.py --config anchor/params.v16.json --scan-id X \
  --geom structures/X.geom.json --structure structures/X.data \
  --potentials anchor/potentials.in --template templates/in.pattern.v16.template \
  --scan-csv anchor/scan_v16.csv
MPIRUN_EXTRA="--cpu-set 0-23" bash tools/run_seed.sh <run> 1001
# 三种提取
python3 tools/postprocess.py      --run-dir <run> --seed seed_1001
python3 tools/tbr_uncertainty.py  --run-dir <run> --seed seed_1001
python3 tools/tbr_global_fit.py   --run-dir <run> --seed seed_1001
python3 tools/tbr_plane.py        --run-dir <run> --seed seed_1001
# 批量（4×12 ranks，遵守 48-rank 上限）
python3 tools/scan_parallel.py --config anchor/params.v16_scan.json \
  --scan-csv anchor/scan_v16_scan.csv --potentials anchor/potentials.in \
  --space config/search_space.json --workers 4 --ranks 12 \
  --template templates/in.pattern.v16.template
```

## 8. 仍未完成

1. `time_converged ≤5%`：1.6 ns 长算例（run_v042/v043）在跑，用于判定慢漂移是趋势还是平台。
2. `R²≥0.995`：需人类批准改成"界面 ΔT/σ 显著性"判据。
3. 可信的图案排名：需要换真实 Ti–Si/Ti–Au 势，否则模型系统误差（2.6 倍）压倒图案效应（<10%）。
4. 推送 GitHub：本地 9 个 commit 就绪，缺凭据。
