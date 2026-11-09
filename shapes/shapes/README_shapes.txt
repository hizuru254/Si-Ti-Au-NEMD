Si/Ti/Au/Ti/Si patterned substrate -- design preview
========================================================

用途：在 OVITO 里直观比较几种刻槽/填充形状。这些是**初始形状**，
没有做最小化、没有加势函数，不能用于任何数值结论。

堆叠顺序（从下到上）：
  Si 衬底 [-60,-30]  ->  Ti 粘附层（单层近似）->  Au 填槽+薄膜
  ->  Ti 粘附层（单层近似）->  Si 顶盖 [20,30]
  Ti 在预览中用一原子层表示（约 3 A），生产结构需要真实 Ti 层。
  厚度是预览值（Si 30/10、Au 44）；生产几何见 examples/geom.SiTiAu.v1.json
  （Si 40 / Ti 20 / Au 40 / Ti 20 / Si 40，上下对称）。

坐标与类型：
  盒子 x,y = 0..65.16 A；z = -65.0..35.0
  类型 1 = Si（金刚石，a=5.43 A）
  类型 2 = Ti（预览单层）
  类型 3 = Au（fcc，a=4.0725 A）

OVITO 使用：
  File -> Open -> 选 S*.data
  Add modifier -> Color coding -> Property = Particle Type
  Si 蓝、Ti 灰、Au 金。
  截面：Orthographic，沿 -y 看（x-z 面）。
  看图案：Slice 掉 z > -29 的 Au/Ti/Si 顶盖，或直接看 PNG。

形状清单（Au 薄膜名义厚度 44 A；P/W/D 单位 A）：
  S0_flat      flat baseline                atoms=20962  P=0.0 W=0.0 D=0.0 single phi=0.0
  S1_rect      rectangular W16.3 D8 P32.6   atoms=21179  P=32.58 W=16.29 D=8.0 single phi=0.0
  S2_deep      deep narrow W8.1 D14 P32.6   atoms=21071  P=32.58 W=8.145 D=14.0 single phi=0.0
  S3_trapezoid trapezoid W20 D5 60deg       atoms=21050  P=32.58 W=20.0 D=5.0 single phi=0.0
  S4_double    double-sided W16.3 D8        atoms=21298  P=32.58 W=16.29 D=8.0 double phi=0.0
  S5_rot45     rotated 45deg W16.3 D8       atoms=21154  P=32.58 W=16.29 D=8.0 single phi=45.0
  S6_cross     crossed trenches W12 D8      atoms=21235  P=32.58 W=12.0 D=8.0 single phi=0.0

设计意图（假设，待真实势函数验证）：
  S0 平面：基准。
  S1 矩形槽：增加 Si/Ti/Au 接触面积 + Au 嵌入。
  S2 深窄槽：更高界面面积，但深宽比大，易出现填充空洞。
  S3 梯形槽：60 度侧壁接近 Si 刻蚀面，应力集中较小。
  S4 双面槽：上下两个 Si 界面同时图案化。
  S5 45 度旋转：面内各向异性/声子失配调节。
  S6 交叉槽：二维约束，界面面积最大，但可能形成孤立 Au 柱。

注意：这些文件只用于看形状。生产用结构必须另行平衡，并通过 G0。
