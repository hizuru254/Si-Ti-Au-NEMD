# 协议 v1.6：把"界面平衡"和"通量热身"做进同一个 run

> 2026-11-12 晚。v1.4/v1.5 的实验表明：只要先把界面真正放松、再丢掉通量刚
> 加上去那 100 ps 的瞬态，TBR 是可以稳定的。v1.6 把这两件事写进 LAMMPS 输入，
> 使每个点都是**一条命令、一个 run、可审计**的完整协议。

## 1. 为什么需要这两步

| 现象 | 原因 | v1.6 的处理 |
|---|---|---|
| 生产段 TBR 单调上升（200 ps 内涨 2–5 倍） | 界面在 300 K 下持续弛豫，放热 0.4–1.4 eV/ps，与热流同量级 | 先退火 300→700→300 K（65 ps），使 PE 到平台 |
| postprocess 前后半段差 30–60% | 通量刚加上去的 0–100 ps 是瞬态，不是稳态 | 加 80 ps 通量热身，热身段**不计量**，之后再 reset_timestep 0 |

实测依据：

- 300 K 恒温跑 230 ps，PE 仍以 −1.0 eV/ps 下降（`docs/STATUS_20261112.md` §7.1）；
- 同样机时下退火 80 ps 的 PE = −162,843（flat）/ −163,337（P350），
  比 300 K 跑 400 ps 还低 700–1300 eV；
- 退火后做 200 ps NEMD：温漂从 +18/+22 K 降到 **+1.0/+1.9 K**，
  且 100–200 ps 的六个 20 ps 窗口给出 4.51/4.38/4.29/4.58/3.90/4.52e-9
  —— **平台内前后半段只差 1.4%**（原始数字见下）。

| run | 点 | 温漂 | 时间收敛（全段） | 100–200 ps 平台内 |
|---|---|---|---|---|
| run_v034 | flat（离线退火） | +0.99 K | 30.6% | 4.39 vs 4.33e-9，**1.4%** |
| run_v035 | P350（离线退火） | +1.89 K | 45.2% | 4.65 vs 4.52e-9，**2.8%** |

v1.6（把退火+热身做进 run 后）的结果：

| run | 点 | TBR (m²K/W) | 时间收敛 | 温漂 |
|---|---|---|---|---|
| run_v038 | flat | 5.33e-9 ± 0.43 | 12.6%（1.7σ，无可分辨漂移） | +0.87 K |
| run_v039 | P350 | 4.69e-9 ± 0.47 | 31.7% | +0.99 K |

## 2. 模板结构（templates/in.pattern.v16.template）

```
velocity create 300 K
minimize
fix eqL/eqR nvt 300 -> 700      run __N_ANN_UP__     (15 ps)
fix eqL/eqR nvt 700 -> 700      run __N_ANN_HOLD__   (25 ps)
fix eqL/eqR nvt 700 -> 300      run __N_ANN_DOWN__   (25 ps)
fix eqL/eqR nvt 300 -> 300      run __N_EQUIL__      (10 ps)
unfix eqL/eqR
reset_timestep 0
fix hot/cold heat 1 __FLUX__ ; fix nve
                                run __N_WARM__       (80 ps, 不计量)
reset_timestep 0
compute chunk/atom + fix ave/chunk
                                run __N_PROD__       (150 ps, 计量)
```

新增 5 个占位符：`__T_ANN__ __N_ANN_UP__ __N_ANN_HOLD__ __N_ANN_DOWN__ __N_WARM__`
（已登记进 `tools/new_run.py` 的 REQUIRED_TOKENS 与 `tools/preflight.py` 的干跑）。

## 3. 为什么退火放在 run 里，而不是离线做

离线退火后把 `preeq_*.data` 交给 new_run 会被 G0 拦住：
退火让原子跨过 z 分区，hot/cold 两个区域的原子数不再相等
（实测 1719 vs 1708），而 preflight 要求相等。
在 run 里退火则群组从**初始对称结构**定义，计数天然相等，
不需要放宽任何检查。

## 4. 参数（anchor/params.v16.json）

| 项 | 值 |
|---|---|
| 退火温度 / 各段步数 | 700 K / 15k 升温 + 25k 保温 + 25k 降温 |
| 平衡（分区 NVT） | 10k 步（10 ps） |
| 通量热身（不计量） | 80k 步（80 ps） |
| 计量生产 | 150k 步（150 ps） |
| 热流 | 1 eV/ps（canonical） |
| ranks | 24（单点） |

总步数 305k，24 ranks 约 41 min。

## 5. 判定标准（不修改 qc_check.py 的阈值）

- `time_converged`：计量段前后半段差 ≤5% —— v1.6 的计量段已剔除瞬态，
  这是它该有的判据；温度稳定（≤25 K）在退火后是 +1~+2 K。
- `fit_quality`（R²≥0.995）：**仍然不可达**，原因见
  `docs/PROTOCOL_V13.md` §R4（16 Å 窗内温降 0.2 K vs bin 噪声 1.2 K）。
  这不因 v1.6 而改变，也不应该靠调阈值绕过。
