# 原始 run 存档

本目录是 `anchor/workspace/run_vNNN/` 的文本/JSON 快照，用于**核对**报告里的数字，
不必重跑。每次新 run 都应追加进来（见文末命令）。

## 内容

每个 run 一个子目录：

```
run_vNNN/
  params.snapshot.json   本次用的完整参数（含 protocol 版本、flux、步数）
  geom.json              几何（层、界面、热源/冷源、bin）
  run_meta.json          run 级元数据（inputs 的 sha256、host、时间）
  qc.json                QC 结果（per_seed 的每一项 check）
  report.txt             qc_check 生成的报告
  tbr_result.csv         若通过 QC 才有
  interfaces.csv         逐界面 ΔT / TBR
  seed_XXXX/
    in.pattern           实际渲染出的 LAMMPS 输入
    log.pattern          LAMMPS 完整日志（含 thermo 表）
    profile.txt          fix ave/chunk 的温度剖面（1 ps 一帧）
    result.json          postprocess 输出（ΔT、R²、时间收敛、TBR）
    run_meta.json        seed 级 wall time / exit code
    tbr_planes.json      固定平面估计量
    tbr_global_fit.json  全剖面拟合估计量
```

**不包含**（体积大且可确定性重建）：`final.data`、`structure.data`、
`*.lammpstrj`、二进制 dump。

## 清单

`MANIFEST.csv`：run_id / scan_id / 窗口法 TBR / 时间收敛 / 是否有日志。

## 追加新 run

```bash
python3 - <<'PY'
import shutil, pathlib
R = pathlib.Path("/home/cc/si_nemd"); EV = R/"reports/evidence"
for src in sorted((R/"anchor/workspace").glob("run_v*")):
    dst = EV/src.name; dst.mkdir(parents=True, exist_ok=True)
    for f in ("params.snapshot.json","geom.json","run_meta.json","qc.json","report.txt"):
        (src/f).exists() and shutil.copy2(src/f, dst/f)
    for sd in src.glob("seed_*"):
        (dst/sd.name).mkdir(exist_ok=True)
        for f in ("in.pattern","log.pattern","profile.txt","result.json","run_meta.json"):
            (sd/f).exists() and shutil.copy2(sd/f, dst/sd.name/f)
PY
```

## 已知的坏 run（保留作证据，不要当结果用）

- `run_v051`：两层盒子未做跨界面去重，退火时 `Non-numeric atom coords`，6 s 退出
- `run_v001`/`run_v009`/`run_v010`：早期协议，温度梯度反向（平面法给出负 TBR）
- `run_v036`/`run_v037`（在 `_abandoned/`）：G0 被 hot/cold 计数拦下
- `run_v042`/`run_v043`：1.6 ns 长算例，中途停止（只跑到 ~175 ps）
