# 会话状态与交接（2026-11-13 12:50）

> 上下文可能中断，这个文件保证任何新会话都能无损续接。**先读这个文件。**

## 0. 位置

| 东西 | 路径 |
|---|---|
| WSL 工作仓库 | `/home/cc/si_nemd`（HEAD 见 `git log -1`） |
| Windows 干净副本 | `F:\LJ KE\si_nemd`（`git clone` 而来，工作区干净） |
| 关键文档 | `docs/RESULTS_SUMMARY.md`（总结）、`docs/STATUS_20261112.md`（15 节流水）、`docs/PROTOCOL_V1{3,4,6}.md` |
| 推送用 patch | `reports/0001..0013-*.patch`、`reports/si_nemd_2026-11-13.bundle` |

## 1. 已经确定的事实（都经过本机实测）

1. **环境**：lmp 29 Sep 2021 U2、OpenMPI 4.1.2、Py3.10.12/numpy 1.21.5、96 核。
   - 29Sep2021 **没有 `-nonbuf`**；没有 `$(zmid)`。
   - **并发 MPI rank 上限 48**（48→128 步/秒；56→7；64→3.5，无报错）。
2. **协议 v1.6**（`templates/in.pattern.v16.template`）：run 内退火 300→700→300 K(65 ps)
   → 300 K 平衡 10 ps → 通量热身 80 ps（不计量）→ 计量 150 ps。
   温漂 **+0.9 K**、能量 1.8e-7、通量对称 1.5e-5。
3. **三种估计量**（同一批数据）：窗口外推 5.33e-9 / 全局拟合 1.38e-8 / 平面法 **1.36e-8**
   → 仓库原方法偏低 2.6 倍；**平面法 `tools/tbr_plane.py` 是最可信的估计量**。
4. **线性响应**：flat 在 1 与 3 eV/ps 下 TBR_eff = 1.3567e-8 vs 1.3569e-8（差 0.01%）。
5. **图案结论**：v1.6 全协议扫描 8 点，TBR_eff 全在 1.347–1.411e-8，
   散布 4.7% 而单点误差 4–5% → **没有任何图案统计上优于平面**。
6. **漂移是真实的**：TBR_eff 在 160 ps 内单调 +73%；300 K 与 700 K 的 PE 都不收敛
   （700 K 保温 150 ps 仍 −2.8 eV/ps）。

## 2. 正在进行（2026-11-13 12:50 启动）

**势函数替换实验**（用户要求用真实势）：
- 新文件 `potentials/potentials.mixed.lj.in`：Si=Tersoff、Au=EAM（都是标准真实势）；
  Ti-Ti 与所有交叉项改用**文献值 + Lorentz–Berthelot 混合**的 LJ：
  Si 3.83 Å/0.01743 eV、Ti 2.93 Å/0.0250 eV、Au 2.57 Å/0.0390 eV。
  旧文件是手挑的 ε=0.2–0.3 eV、σ=2.0 Å（强 6–14 倍），那是持续互混的根因。
- 对比实验 `pottest/{old,new}`：同一 flat 结构、300 K NVT 50 ps，看 PE 漂移与 Ti 互混。

## 3. 下一步（按顺序）

1. 读 `pottest/{old,new}/log.preeq` 的 PotEng 斜率 → 若 new 明显更平，说明交叉项是主因。
2. 用新势重跑 v1.6 anchor（flat）：`params.v16.json` 改 `potentials` 指向新文件，
   看 `time_converged` 是否降到 ≤5%（这是 QC 唯一还没过的实质判据）。
3. 若稳定：用新势重跑 8 点扫描（`scan_parallel.py`，4×12 ranks，约 2.6 h）。
4. 更新 `potentials.lock.json` 哈希 + preflight 重跑。
5. 重新生成 patch/bundle，复制到 `F:\LJ KE\si_nemd`，推 GitHub（需凭据）。

## 3b. 机器学习势可行性判定（2026-11-13，本轮新增）

| 项 | 结果 |
|---|---|
| 构建工具 | cmake / g++ / mpicxx / make 都在 ✓ |
| LAMMPS 源码 | `/home/cc/lammps/src`，含 ML-IAP、ML-PACE、ML-POD、ML-SNAP、ML-RANN、ML-QUIP、ML-HDNNP |
| 已装 lmp 的 ML 支持 | **无**（编译时没开任何 ML 包） |
| `pair_style nep` | **stock LAMMPS 没有**（NEP 属 GPUMD，需打补丁或改用 GPUMD 本体） |
| 最可能的真实势 | **NEP89**（89 元素通用 NEP，覆盖 Si/Ti/Au，材料建模社区已发布）；Si-Ti 专用 NEP 见 arXiv:2511.16646（训练库在 Zenodo） |

**结论**：机器具备编译能力，但迁移到 NEP 需要：
1. 取 NEP89 模型文件（或按 arXiv:2511.16646 的训练库自训）；
2. 编译带 NEP 的 LAMMPS（NEP_CPU 补丁）或用 GPUMD 本体跑 NEMD；
3. 用 NEP 重算 `build_geometry` 的晶格常数（NEP 的 Si/Ti 平衡体积与 Tersoff/EAM 不同）。

这是**下一步的主线**，预计 2–4 h（编译 30 min + 验证 1 h + 重跑锚点 1.5 h）。
本轮因上下文预算未执行，代码与数据状态已完整落盘。

## 4. 未解决 / 需人类决定

- **R²≥0.995**：结构性不可达（窗内温降 0.2 K vs bin 噪声 1.2 K），需批准改判据。
- **GitHub 推送**：WSL 无凭据（无 PAT / ssh key / gh），用户选择自行推或提供 PAT。
- **真三元势**：文献前沿是 NEP 机器学习势（arXiv:2511.16646, Si-Ti），
  但需要 GPUMD 插件，stock LAMMPS 29Sep2021 用不了。

## 5. 常用命令

```bash
cd /home/cc/si_nemd
git log --oneline -5
MPIRUN_EXTRA="--cpu-set 0-23" bash tools/run_seed.sh anchor/workspace/run_vNNN 1001
python3 tools/postprocess.py --run-dir <run> --seed seed_1001
python3 tools/tbr_plane.py  --run-dir <run> --seed seed_1001
python3 tools/tbr_global_fit.py --run-dir <run> --seed seed_1001
python3 tools/rank_plane.py --workspace anchor/workspace --proto 1.6
```

## 3c. NEP 可达性探针（2026-11-13）

| URL | HTTP |
|---|---|
| raw.githubusercontent.com/brucefan1983/NEP_CPU/main/README.md | **200** |
| raw.githubusercontent.com/brucefan1983/GPUMD/master/README.md | **200** |
| materialsmodeling.org/nep89/nep89.txt | 404 |
| github.com/nep-model/NEP89/.../nep89.txt | 404 |

结论：**NEP_CPU 源码可获取**（可编译成 LAMMPS pair style），但 **NEP 模型文件
（nep.txt）没有公开直链**——NEP89 需要到 materialsmodeling.org 申请/下载，
Si-Ti 专用模型需按 arXiv:2511.16646 的训练库（Zenodo）自训。

因此下一轮的第一步是：**取得一个含 Si/Ti/Au 的 nep.txt**（用户下载或提供镜像），
之后 clone NEP_CPU → 按其中 LAMMPS 接口编译 → 用新势重标晶格 → 重跑锚点。
