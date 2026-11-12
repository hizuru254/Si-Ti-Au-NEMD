# 协议 v1.3：为什么改、改了什么、怎么验证

> 2026-11-12，在 WSL2 / 96 核（EPYC 9684X）机器上，用 ANCHOR11（Si 40 / Ti 40 /
> Au 40 Å，45,880 原子）逐步定位到"TBR 不可信"的四个独立原因，逐条修正并验证。
> 本文件是这些修正的审计记录；判据（`qc_check.py` 阈值）与势函数**未改**。

## 1. 观察到的现象

| 版本 | 配置 | R²(min) | 温度剖面 | QC |
|---|---|---|---|---|
| run_v001（旧协议） | 全局 NVT 20k，heat N=1728，热源在自由表面 | 0.256 | z=−96 Å 处 251 K、z=+96 Å 处 397 K（反向） | FAIL |
| run_v009 | 全局 NVT 100k，heat N=1，热源内移 8 Å | 0.009 | −z 半侧 270 K、+z 半侧 327 K | FAIL |
| run_v012 | **两半各自 NVT 50k**，heat N=1，内移 8 Å | 0.5–5（见 §5） | 对称 | FAIL（R² 门限） |

## 2. 逐条根因

### R1 `fix heat` 的 N 参数被误用（数值）
模板写 `fix hot hot_g heat ${hot_n} __FLUX__`。LAMMPS 的语法是
`fix ID group heat N eflux`，其中 **N 是"每 N 步注入一次"**，不是原子数。
组原子数 1728 放进去，等于每 1.728 ps 一次性注入 1.728 eV。
平均通量不变（eflux·N·dt 每 N 步），但注入是脉冲式的。

证据（`src/fix_heat.cpp`）：`heat = heat_input*nevery*dt*ftm2v;
escale=(ke+heat−…)/(ke−…); scale=sqrt(escale)` —— 正 eflux 一定加热。
所以符号没问题，问题在 N。

修正：`heat 1 __FLUX__`。效果：通量对称性 2.3% → **0.0000**。

### R2 热源放在自由表面上（物理/建模）
原 geom 把 hot/cold 放在 z=±(100−8)…±100 Å，即 Si 的自由表面。
在 300 K NVT 平衡中，这两块 8 Å 表面被加热到 **600–750 K**（全局仍是 300 K）：
自由表面的欠配位原子在结构弛豫中吸收了大部分初始势能。
这个瞬态比 1 eV/ps 的注入量（20 ps 才 20 eV）大一个量级。

修正：`build_geometry.py --res-inset 8`，热源/冷源内移到 ±(84…92) Å，
表面区变成绝热平台，不参与拟合窗口（窗口在 ±(62…78) Å）。

### R3 全局 NVT 无法消除内部温度梯度（物理）
全局 Nosé–Hoover 只约束**总**动能。若两半之间已有 ΔT（由 R2 的瞬态和
Si/Ti 界面弛豫差异造成），总动能仍是 300 K，恒温器不会做任何事。
实测 run_v009 在 100 ps 平衡 + 19 ps 生产后，两半仍差 57 K。

修正：平衡段用**分区恒温**（模板 v1.3）：

```
variable zmid equal 0.5*(zlo+zhi)
region halfL block INF INF INF INF -100000.0 ${zmid} units box
region halfR block INF INF INF INF ${zmid} 100000.0 units box
fix eqL halfL_g nvt temp 300 300 0.1
fix eqR halfR_g nvt temp 300 300 0.1
```

两半各自由 300 K 恒温器控制 → 均匀初态，再进入 NEMD 生产段。

### R4 R² ≥ 0.995 在该体系/该热流下不可达（统计）
拟合窗口宽 16 Å、bin 2 Å → 8 个点。实测（run_v009，100 ps）：

- 单个 2 Å bin 的温度：块间标准差 **11–13 K**，100 个 1 ps 块平均后
  sem = **1.1–1.3 K**
- 窗口内体相温降：Si/Ti 窗口从 −38 Å 到 −22 Å 只从 283.15 变到 283.32 K，
  **≈0.2 K**

信号 0.2 K vs 噪声 1.2 K → R² 的分子是噪声、分母也是噪声，R² 无意义。
要把 16 Å 窗口的温降做到噪声的 ~50 倍（R²≈0.995 的近似要求），
需要 q ≈ 2×10¹¹ W/m²（当前 3.8×10⁹ 的 ~50 倍），会导致 ΔT 上千 K，
超出线性响应区并可能熔化界面。

**结论**：R² 门限对"体相线性"的检验在这个体系里失效，保留它只会永远 FAIL。
真正有物理意义、且信噪比足够的是**界面 ΔT**（4.5–12.7 K，SNR 5–8）。
因此新增 `tools/tbr_uncertainty.py`：块平均给出每个界面 ΔT 与 TBR 的
统计误差，要求 `dT_i/σ_i` 可核查。`qc_check.py` 的阈值**原样保留**，
`report.txt` 仍会写 FAIL；两种读数并列报告，不隐瞒。

## 3. 热流线性检验（决定能否提高热流降噪）

| 配置 | q (W/m²) | dT_total (K) | TBR (m²K/W) | 相对不确定度 |
|---|---|---|---|---|
| run_v012 | 3.774e9（1 eV/ps） | 7.30 ± 1.65 | **1.93e-9 ± 0.44e-9** | 22.6% |
| run_v013 | 1.132e10（3 eV/ps） | 24.52 ± 2.76 | **2.17e-9 ± 0.24e-9** | 11.3% |

两者在 0.5σ 内一致 → **线性响应成立**，因此扫描采用 3 eV/ps，
在同样机时下把信噪比提高约 2 倍（相对不确定度 22.6% → 11.3%）。

## 4. 今天的判定（人类门禁授权）

用户 2026-11-12 授权代理执行人类审核节点（H0/H1a/H6）。
本文件记录代理做的判断与依据，便于事后复核：

- H1a：`config/search_space.json` 置 `approved=true`；范围未改；
  `fixed.ti_A` 由 24 改为 **40**（与已验证的 ANCHOR11 叠层一致，否则不可比）。
- H0：锚点仍**未通过** R² 门限（见 §2 R4，属体系性不可达），
  因此锚点按"TBR ± σ 可核查"口径接受，用于**同一协议下的相对比较**，
  不作为可对外的绝对 TBR。

## 5. 复现步骤

```bash
cd /home/cc/si_nemd
python3 tools/build_geometry.py --scan-id ANCHOR13 --kind flat --t-nm 4.0 \
  --ti 40 --si 40 --bin 2 --res-inset 8 --status APPROVED \
  --out-structure structures/ANCHOR13.data --out-geom structures/ANCHOR13.geom.json
python3 tools/preflight.py --config anchor/params.scan_v13_flux3.json \
  --geom structures/ANCHOR13.geom.json --structure structures/ANCHOR13.data \
  --potentials anchor/potentials.in --template templates/in.pattern.v13.template --dry-run
python3 tools/new_run.py --config anchor/params.scan_v13_flux3.json --scan-id ANCHOR13 \
  --geom structures/ANCHOR13.geom.json --structure structures/ANCHOR13.data \
  --potentials anchor/potentials.in --template templates/in.pattern.v13.template \
  --scan-csv anchor/scan_patterns.csv
MPIRUN_EXTRA="--cpu-set 0-23" bash tools/run_seed.sh <RUN_DIR> 1001
python3 tools/postprocess.py --run-dir <RUN_DIR> --seed seed_1001
python3 tools/tbr_uncertainty.py --run-dir <RUN_DIR> --seed seed_1001
python3 tools/qc_check.py --run-dir <RUN_DIR>
```
