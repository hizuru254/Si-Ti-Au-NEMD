# 拆层实验：单界面（两层）能不能救回稳态 TBR

> 2026-11-13。起因：师兄建议"别 5 层一起算，两层两层来"。
> 本文是这条路的完整实测记录与判决。

## 1. 为什么要拆

5 层 `Si/Ti/Au/Ti/Si` 的串联关系是

```
R_5层 = 2·R(Si/Ti) + 2·R(Ti/Au) + 体相项
```

真正独立的界面只有两种。拆成单界面后：两侧都是厚体相，界面 ΔT 可以直接
从两个平台读出，不需要 16 Å 窗口外推（而外推对本体系偏低 2.6 倍）。

## 2. 实现

新增 `tools/build_pair.py`：造两层单界面盒子（`--pair ti-au` 或 `si-ti`），
面内 65.16 Å 沿用原配准，两侧各 `--thick`（本次 60 Å），界面在 z=0，
热源/冷源各内移 10 Å。

两个必须做的细节（都踩过）：

1. **跨界面去重**：五层生成器里的 `remove_close(…, 1.8 Å)` 必须搬过来，
   否则界面处有重叠原子，退火升温直接 `Non-numeric atom coords` 崩掉
   （第一次 `run_v051` 就是这么失败的，6 s 退出）。
2. **热源/冷源原子数**：Ti 每层面密度 572、Au 512，任何整层组合都差 ~10.5%，
   凑不出 5% 以内。`fix heat` 用 `N=1` 时功率恒为 eflux、与组大小无关，
   所以把 G0 的"必须严格相等"改为 **>12% 才报错**，并对本次的 10.5% 记 warning。

生成结果：29,720 原子（Ti 14,872 / Au 14,848），G0 **READY errors=0**。

## 3. 结果

| run | 热流 | 窗口法 TBR (m²K/W) | 全局拟合 TBR | 时间收敛 | 温漂 | TotEng |
|---|---|---|---|---|---|---|
| v052 | 1 eV/ps | 3.2e-10 | 9.6e-10 ± 43% | **65%** | +0.54 K | 4.8e-7 |
| v053 | 3 eV/ps | 1.7e-10 | 8.8e-10 ± 52% | **264%** | +0.14 K | 1.7e-7 |

两次都 `exit 0`、1200 s、无 Lost atoms。

## 4. 判决：拆层解决不了问题

1. **几何是对的**：能耗守恒 1.7e-7、温漂 0.14 K，比五层的 0.9 K 还好。
2. **但 TBR 仍不收敛**：65% 和 264%，比五层更差。
   原因不是层数，而是 Ti/Au 界面本身仍在互混
   （此前测到 700+ 个 Ti 原子溶入 Au 膜），热阻随时间变化。
3. **提取歧义照旧**：窗口法 1.7e-10 vs 全局拟合 8.8e-10，差 5 倍。
   界面附近同样有 ~8 Å 非线性过渡区。

所以"拆成单界面"降低的是几何复杂度，不是界面化学带来的不稳定性。
它**反向印证**了 `docs/PROTOCOL_V14.md §5.3` 的结论：LJ 交叉项 → 界面持续互混
→ TBR 无稳态，换几何绕不过去。

## 5. 这条路仍然有用（等真实势之后）

一旦拿到真实多元素势（NEP），**第一个该做的就是单界面**：
- 算力最省（3 万原子、一个界面）
- ΔT 最干净（两个平台之差，无外推）
- 是"新势到底有没有让界面稳定"的最佳试金石

顺序建议：单界面（Ti/Au、Si/Ti）→ 3 层验证串联可加性 → 5 层对照。

## 6. 复现

```bash
python3 tools/build_pair.py --pair ti-au --thick 60 --bin 2 \
  --out-structure structures/PAIR_TiAu.data --out-geom structures/PAIR_TiAu.geom.json
python3 tools/preflight.py --config anchor/params.v16.json \
  --geom structures/PAIR_TiAu.geom.json --structure structures/PAIR_TiAu.data \
  --potentials anchor/potentials.in --dry-run
python3 tools/new_run.py --config anchor/params.v16.json --scan-id PAIR_TIAU \
  --geom structures/PAIR_TiAu.geom.json --structure structures/PAIR_TiAu.data \
  --potentials anchor/potentials.in --scan-csv anchor/scan_v16_scan.csv
MPIRUN_EXTRA="--cpu-set 0-23" bash tools/run_seed.sh <run> 1001
python3 tools/postprocess.py     --run-dir <run> --seed seed_1001
python3 tools/tbr_global_fit.py  --run-dir <run> --seed seed_1001
python3 tools/tbr_plane.py       --run-dir <run> --seed seed_1001 --z 45   # 注意 z 别落在绝热死区
```
