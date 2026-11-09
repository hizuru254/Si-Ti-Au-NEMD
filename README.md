# Si/Ti/Au/Ti/Si NEMD Workflow

**A gate-driven, reproducible LAMMPS workflow for interfacial thermal resistance (TBR) and autonomous geometry screening of Si/Ti/Au/Ti/Si stacks.**

> **Status: research framework, not a validated physical result.**
> The execution chain, geometry generator, batch runner and optimizer are implemented and
> have been exercised end-to-end. The flat anchor (3 seeds × 120k steps) is prepared but
> has not completed on the target machine yet; the 1.8k-atom synthetic validation case is
> an intentional negative control that the QC gates reject. See [Validation](#validation-record)
> and [Limitations](#known-limitations) before using any number.

---

## Overview

This repository packages a non-equilibrium molecular dynamics (NEMD) workflow for
Si/Ti/Au/Ti/Si layer stacks into a set of small, auditable tools:

- a **parameterized geometry generator** for Si(001) / Ti(hcp) / Au stacks with grooves
  at the Au/Ti interface;
- a **strict pipeline** (`preflight → new_run → run_seed → postprocess → qc_check`)
  that records hashes, refuses to overwrite runs, and never fabricates a TBR;
- a **batch runner** that executes a scan queue unattended;
- a **surrogate optimizer** (Latin hypercube for small samples, Gaussian process +
  expected improvement for larger samples) that proposes the next design points;
- a **candidate report** that ranks only QC-passed runs.

The design goal is *human-on-the-loop*: a human approves the physical anchor and the
final candidate; the intermediate design, execution, QC and ranking are automated.

---

## Stack and geometry

```text
        Si (001) cap          40 Å
        Ti  hcp               20 Å (flat) / 24 Å (patterned)
        Au  fcc               40 Å  (t = Au film thickness)
        Ti  hcp               20 Å / 24 Å
        Si (001) substrate    40 Å
```

- In-plane cell: **65.16 × 65.16 Å** (Si 12×12, Au 16×16, Ti 22×13).
- Flat reference (`v1`, approved 2026-11-10): **40/20/40/20/40 Å**, interfaces at
  ±40/±20 Å, fit windows 16–20 Å, 15 Å vacuum at both ends.
- Patterned design (scheme **B**): grooves are etched into the **Ti** side of the
  Au/Ti interface and filled with **Au**; `t` is the Au film thickness and `D` is the
  etch depth. Patterned runs use Ti 24 Å, `bin=2 Å`, `D ≤ 8 Å` so that a clean Ti-side
  fit window remains above the groove.
- Ti is **hcp geometry with LJ interactions**. `Ti.meam.spline` is a single-element
  spline potential and cannot be used in a three-element hybrid; it is reserved for a
  separate pure-Ti bulk check.

---

## Pipeline and gates

| Stage | Tool | What it guarantees |
|---|---|---|
| G0 preflight | `tools/preflight.py` | environment, geometry Q1–Q8, structure/header, potential hashes, dry run |
| G1 build | `tools/new_run.py` | immutable `run_vNNN`, manifest, rendered seed inputs |
| G2 run | `tools/run_seed.ps1` / `.sh` | one seed per process, exit code, wall time, no overwrite |
| G3 postprocess | `tools/postprocess.py` | flux, ΔT, interface fits, `TBR_total = ΣΔT_i / q` |
| G4 QC | `tools/qc_check.py` | energy drift, signal, R², time convergence, seed statistics, range |
| G5 archive | `workspace/` | CSV, report, ledger, hashes |
| G6 report | `tools/report_candidates.py` | top-k candidates for human review |

Two mandatory human gates:

- **H0 — anchor**: the flat stack must pass QC with 3 seeds and a length/cross-section
  convergence check of <5%.
- **H6 — candidate**: a human reviews the physical plausibility of the top-k designs.

The search space itself is gated by `config/search_space.json` (`approved: true`).
Points outside the approved ranges are rejected; they are not silently promoted.

---

## Quick start

### Requirements

- LAMMPS with `MANYBODY`, `MEAM` and `EXTRA-PAIR` packages (tested with
  `LAMMPS 64-bit 4Jul2026-MSMPI`);
- Python ≥3.10 with `numpy`;
- Windows PowerShell 5.1 for the provided `.ps1` launchers, or bash for WSL/Linux;
- **an ASCII-only project root** (e.g. `D:\si_nemd`). Paths containing non-ASCII
  characters break both LAMMPS input handling and Python→PowerShell argument passing.

```powershell
git clone https://github.com/hizuru254/Si-Ti-Au-NEMD.git D:\si_nemd
cd D:\si_nemd
# edit config/params.json: lammps.exe, lammps.potentials_dir, workspace
python tools\selftest.py
```

Run one flat anchor (3 seeds × 120k steps, serial, about 5.7 h):

```powershell
powershell -ExecutionPolicy Bypass -File D:\si_nemd\anchor\start_anchor.ps1
```

Run one patterned point manually:

```powershell
python tools\build_geometry.py --scan-id S001 --kind rect `
  --t-nm 4.0 --ti 24 --si 40 `
  --W-nm 1.629 --D-nm 0.8 --P-nm 3.258 --phi 0 `
  --sided single --bin 2 --status DRAFT `
  --out-structure structures\S001.data --out-geom structures\S001.geom.json

python tools\preflight.py --config config\params.json `
  --geom structures\S001.geom.json --structure structures\S001.data `
  --potentials anchor\potentials.in --dry-run
```

### Autonomous loop

```powershell
# 1) approve the search space: config/search_space.json -> "approved": true
# 2) propose the next batch (<5 valid points: LHS; >=5: GP + EI)
python tools\optimize.py --summary workspace\scan_summary.csv `
  --space config\search_space.json --scan-csv config\scan.csv `
  --out config\scan.next.csv --n-propose 8

# 3) run the batch (--pilot = 1 seed / 5k steps; drop it for production)
python tools\scan_runner.py --config config\params.json `
  --scan-csv config\scan.next.csv --potentials anchor\potentials.in `
  --space config\search_space.json --pilot --max-points 1

# 4) render the candidate report
python tools\report_candidates.py --summary workspace\scan_summary.csv `
  --out optimization\candidates.md
```

`scan_runner` marks every point `done` or `failed`, writes `workspace/scan_summary.csv`,
and never relaxes a threshold. `optimize` only reads `is_passed=True` rows.

---

## Validation record

| ID | Case | Result |
|---|---|---|
| V1 | Cu + EAM, 768 atoms, `tools/selftest.py` | **PASS**, QC `n_valid=3` |
| V2 | Si/Ti/Au/Ti/Si, 1856 atoms, 3 × 30k steps | run completes; **QC FAIL by design** (weak synthetic interfaces, slip, non-monotonic profile) |
| V3 | Flat anchor, 36,072 atoms, Si(001)/Ti(hcp)/Au | G0 **READY**; 3k-step stability pilot: no lost atoms, drift 9e-6, TBR 3.0e-8 m²K/W |
| V4 | Rectangular groove, 38,000 atoms, 1 seed × 5k steps | full batch chain completes; **QC FAIL** (short pilot), status `failed` recorded |

The V2/V4 failures are the gates working, not a silent success. The real anchor
(3 seeds × 120k) is the next milestone.

---

## Known limitations

1. **Electronic thermal conductivity is absent.** EAM/Tersoff/LJ describe phonons only.
   Au is dominated by electrons, so the Au-side conductance is strongly underestimated;
   absolute TBR cannot be compared directly with experiment or TDTR.
2. **Ti is a model, not real Ti.** Ti uses hcp geometry with LJ interactions; there is
   no multi-element Ti MEAM in this stack. `Ti.meam.spline` cannot be used in the hybrid.
3. **No silicide chemistry.** Ti/Si and Ti/Au cross terms are LJ; no TiSi₂ formation or
   interdiffusion is represented.
4. **Finite size.** The 65.16 Å in-plane cell and the layer thicknesses are smaller than
   the phonon mean free path; length/cross-section convergence is required.
5. **n = 3 seeds.** The 10% relative-standard-deviation criterion is a screening line,
   not a statistically significant uncertainty.
6. **TBR_total is a series sum over four interfaces**; it is not directly comparable to
   single-interface literature values.
7. **Temperature definition.** `fix ave/chunk temp` does not remove local COM streaming;
   a slipping interface can inflate the apparent temperature. The production structure
   must be equilibrated and drift-checked.

---

## Repository layout

```text
.
├─ AGENT_MANUAL_V5_WIN.txt      # verified Windows-native manual
├─ AGENT_MANUAL_V5_WSL.txt      # WSL2 variant (unverified on target)
├─ AGENT_MANUAL_V4.txt          # deprecated (wrong layer order)
├─ README.md
├─ config/
│  ├─ params.json               # single source of truth for paths, thresholds, run length
│  ├─ scan.example.csv          # scan queue template (includes kind)
│  └─ search_space.example.json # search ranges + approval flag
├─ templates/in.pattern.template
├─ tools/
│  ├─ build_geometry.py         # Si(001)/Ti(hcp)/Au geometry, scheme B
│  ├─ preflight.py              # G0
│  ├─ new_run.py                # G1
│  ├─ scan_runner.py            # batch orchestrator
│  ├─ optimize.py               # LHS / GP + EI
│  ├─ report_candidates.py      # top-k report
│  ├─ postprocess.py            # G3
│  ├─ qc_check.py               # G4
│  └─ ...
├─ examples/                    # approved v1 geometry and a legacy counter-example
├─ validation/                  # 1.8k-atom negative-control project + evidence
├─ anchor/                      # flat anchor (strong-LJ variant)
├─ docs/AUTONOMOUS_LOOP.md      # loop design, cost model, review checklist
└─ shapes/                      # 7 preview shapes (data + PNG)
```

`structures/`, `anchor/workspace/`, `_test/` and `optimization/` are generated and ignored.

---

## Citation

If this workflow is useful in academic work, cite the repository:

```bibtex
@misc{si_ti_au_nemd_2026,
  title  = {Si/Ti/Au/Ti/Si NEMD Workflow: a gate-driven LAMMPS framework for
            interfacial thermal resistance and geometry screening},
  author = {hizuru254},
  year   = {2026},
  url    = {https://github.com/hizuru254/Si-Ti-Au-NEMD}
}
```

---

## License

Released under the MIT License. See [LICENSE](LICENSE).

---

## 中文摘要

本仓库把 Si/Ti/Au/Ti/Si 叠层的 LAMMPS NEMD 界面热阻计算拆成可校验、可复现、
可追责的工具链：几何生成、G0 前置校验、建版、三种子运行、后处理、QC 门禁、
批量调度、代理模型提议和候选报告。

- **层序**：Si(001) 40 Å / Ti(hcp) 20–24 Å / Au 40 Å / Ti / Si；图案化采用 B 方案
  （刻 Ti、填 Au），`t` 为 Au 膜厚，`D ≤ 8 Å`，Ti 24 Å、bin 2 Å。
- **人类只剩两个审批点**：H0 平面锚点（3 seed × 120k 通过 QC）和 H6 最终候选的
  物理合理性。搜索空间由 `config/search_space.json` 的 `approved` 控制。
- **现状**：执行链、几何生成器、批量调度器、GP/EI 提议、候选报告均已实现；
  平面锚点的 3×120k 尚未完成，因此**目前没有可发表的 TBR**。
- **模型限制**：Ti 为 hcp 几何 + LJ；无电子热导、无硅化物化学；65 Å 面内存在
  有限尺寸效应；`TBR_total` 是四个界面串联，不能直接与单界面文献对比。

细节见 [docs/AUTONOMOUS_LOOP.md](docs/AUTONOMOUS_LOOP.md) 与
[AGENT_MANUAL_V5_WIN.txt](AGENT_MANUAL_V5_WIN.txt)。
