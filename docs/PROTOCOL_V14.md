# 协议 v1.4：先平衡界面，再测 TBR

> 2026-11-12 晚。v1.3 修好了温度剖面本身（热源位置、注入方式、分区平衡），
> 但发现**测出来的 TBR 不收敛**：随时间单调上升。本文件记录原因、量化、
> 以及第一步补救（长预平衡）。

## 1. 现象

200 ps 生产段里 TBR 不是平台，而是单调上升：

| 点 | 20 ps | 60 ps | 100 ps | 160 ps | 全段 200 ps |
|---|---|---|---|---|---|
| P350（run_v026） | 1.21e-9 | 1.32e-9 | 2.79e-9 | 4.23e-9 | 3.37e-9 |
| D040（run_v027） | 1.83e-9 | 2.90e-9 | 3.89e-9 | 5.07e-9 | 3.75e-9 |

## 2. 原因：界面在持续弛豫，放热与热流同量级

从生产段日志里直接读 PotEng 与 Temp（`step temp poteng kineng etotal`）：

| run | t=1 ps | t=180 ps | ΔPE | 末端 dPE/dt | ΔT |
|---|---|---|---|---|---|
| run_v026 (P350) | −162391.7 | −162559.7 | −168 eV | −0.43 eV/ps | +27 K |
| run_v027 (D040) | −160509.5 | −161742.2 | −1233 eV | −1.38 eV/ps | +217 K |
| run_v013 (flat) | −161893.1 | −161965.3 | −72 eV | −0.72 eV/ps | +11 K |

生产段是 NVE，界面释放的势能直接变成动能 → 温度升高 → 温度剖面里混入
"界面弛豫热"，ΔT 随界面粗化一起变大。施加的热流是 1–3 eV/ps，
弛豫放热 0.4–1.4 eV/ps —— **同一个量级**，所以测出来的不是热阻，是弛豫。

## 3. 预平衡实测（tools/pre_equil.py）

区域 NVT、300 K、每 100 ps 写一个检查点，读 PotEng 判断是否到平台：

| 结构 | t=0（最小化后） | 100 ps | 200 ps | 230 ps | 末端 dPE/dt |
|---|---|---|---|---|---|
| F000 (flat) | −159696.6 | −161976.2 | −162067.2 | −162095 | ≈ −1.0 eV/ps |
| P350 | 见 preeq 日志 | — | — | — | ≈ −1 eV/ps |

**结论：230 ps 仍未到平台**，PE 已累计下降 2398 eV，速率没有明显衰减。
按此速率，要把 dPE/dt 压到 0.05 eV/ps 以下，需要 **1–3 ns** 的预平衡。

## 4. 成本

| 配置 | 吞吐 | 1 ns 单点 | 1 ns × 4 点并行 |
|---|---|---|---|
| 24 ranks × 1 job | 123 steps/s | 2.3 h | — |
| 4 job × 12 ranks | 65 steps/s each | 4.3 h | 4.3 h |

（并发 rank 总数不得超过 48，见 `AGENT_MANUAL_V5_WSL.txt` §14.2）

## 5. 判定实验：预平衡与热流都不是主因

### 5.1 用 200 ps 预平衡结构做 NEMD（run_v030 / run_v031，flux 3）

| run | 点 | TBR | 时间收敛 |
|---|---|---|---|
| run_v030 | flat | 4.46e-9 ± 0.26 | 2.36→5.13e-9，**54%** |
| run_v031 | P350 | 3.33e-9 ± 0.24 | 1.70→3.94e-9，**57%** |

未预平衡时是 55%。**预平衡没有改善** → 漂移不是初始态造成的。

### 5.2 回到 canonical 1 eV/ps（run_v032 / run_v033，50k + 200k）

| run | 点 | TBR | 时间收敛 | 温漂 |
|---|---|---|---|---|
| run_v032 | flat | 4.28e-9 ± 0.50 | 2.04→5.30e-9，**61%** | +17.7 K |
| run_v033 | P350 | 2.43e-9 ± 0.52 | 2.72→3.60e-9，**24%** | +21.9 K |

降低热流也没有用。**注意**：正因为如此，v1.3 里"flux 3 更好"的判断被推翻——
v012（flux 1）当时的 4.6% 是短生产段（100 ps）的偶然，生产段拉长到 200 ps
后同样是几十个百分点。

### 5.3 结论

漂移与热流、与初始态都无关，是**模型界面在 300 K 下持续粗化**。
在换势（真实 Ti–Si/Ti–Au）、ns 级预平衡、或降低测量温度之前，
TBR 没有稳态，图案排名不可信。详见 `docs/STATUS_20261112.md` §7。

## 6. 复现

```bash
python3 tools/pre_equil.py --structure structures/F000.data \
  --geom structures/F000.geom.json --potentials anchor/potentials.in \
  --out-dir preeq/F000 --steps 400000 --chunk 100000
python3 tools/preeq_report.py preeq/F000          # 看 dPE/dt
mpirun -np 24 --bind-to core --cpu-set 0-23 /usr/bin/lmp -in preeq/F000/in.preeq \
  -log preeq/F000/log.preeq
# 用检查点做生产
python3 tools/new_run.py --config anchor/params.preeq_prod.json --scan-id PEF000 \
  --geom structures/F000.geom.json --structure preeq/F000/preeq_0200000.data \
  --potentials anchor/potentials.in --template templates/in.pattern.v13.template \
  --scan-csv anchor/scan_preeq.csv
```
