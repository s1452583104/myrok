# 历史流水（各会话的实现记录与修复清单）

> 由 `docs/PROGRESS.md` 拆出（2026-09-29）。**本文件 append-only、平时不用读**——
> 它是「当时怎么发现、怎么修的」的原始记录，用于回溯根因；当前状态与待办看
> [`docs/PROGRESS.md`](PROGRESS.md)。加新记录请 append 到本文件末尾。

### 三识别栈融合（2026-09-18，commit 2400e4d）
- **YOLO**：`config.yaml app.yolo_model` 已切 **gpu_1080_v9**（**64 类**方案 B，09-27 切换；v8 为 09-24、v7 为 09-21）。数据集为 64 类方案 B（`zhaizi_level_text` 合并类 + `sort_selector/sort_opt_*` 4 新类 + 09-27 新增 `city_btn`）。**v9 在同一 val 集现算 mAP50 0.7247 略低于 v8 0.7382**，切它是为功能（地图视图 `search_icon`/`city_btn` 只有 v9 出框）而非指标，详见下方「2026-09-27 三处补标 + 新类 `city_btn`（64 类）+ v9 训练」；v7→v8 见「2026-09-24（续）v8 训练 + 寨子等级 OCR 修复」；v6→v7 见 `docs/session-2026-09-20-方案B标注与v7训练.md`
- **OCR**：rapidocr-onnxruntime（PP-OCR ONNX 离线，py3.14 兼容），角色名等 YOLO 不训的类（账号/配置绑定）由 `fill_*` 名字模板失配时 OCR 兜底
- **融合规则**（`template_registry.build_recognizers`）：每个模板 id → Chain(模板匹配先行, 兜底)；兜底 = id 在 YOLO 类名单里 → YoloClassAdapter，`fill_*` → OCRText，`queue_recall_icon` 等不在名单的 → 纯模板不挂兜底（防运行时 KeyError）。**兜底腿用的是同一个 `spec.threshold`**（不是另设一套），见「2026-09-27 运行时到底谁在识别」
- **SharedYoloDetector**：全识别器共享一个 YOLO 实例 + 单帧缓存（key=截图 id+shape），`__call__` 推理接口
- 角色名类不 YOLO 训练（约束：账号/配置绑定，名字走 OCR/模板）
- **`zhaizi_level_text` 的等级 OCR 是工具侧的，不在实机链路里**：车头设等级是**盲进**（`level_minus ×12 / level_plus ×N` 不回读，`leader_sm.py:40-41` 记为已接受限制），`src/` 里没有任何代码读它；OCR 读等级只在 `tools/annotate_live.py` 预览与 `tools/check_zhaizi_level.py` 体检里用

### 2026-09-17/18 实机迭代修复（run2-run7 驱动验证）
| 问题 | 修复 | commit |
|---|---|---|
| WAIT_RETURN 25 分钟卡死，「图标不可辨」×104 | 门槛地图视图判据补 `search_icon`（简化模式下 alliance_btn 在干净地图仅 0.248；放大镜同为地图视图专属且全屏面板打开时不显示，不重演面板残留误判） | 9bf86b2 |
| 门槛被「创建部队」等全屏弹窗残留挡住 15 分钟白等 | 门槛 unknown 分支补齐 7 种面板关闭（war/warning/form→X 1671,64；replace→1500,170；rally_attack→960,540；ap_refill→1638,120；menu_expanded→1845,1010） | f3a4495 |
| 成员归一化无集结时段误抛异常 ×4 | 成员 normalize 补 `search_icon` 地图视图判据 | 9e20bc9 |
| 成员归一化关战争面板不等过渡动画死路（run6 03:46） | war_title 分支点 X 后等 `search_icon` 现形即归一化成功 | 00cb53f |
| 成员归一化关创建部队表单同样死路（run7 04:24，失败截图 form_title=1.000 实锤；车头停机后成员连带 no_rally_found 停机） | form_title 分支改「点 X→等放大镜现形→表单还开着才补点（≤3 次）」循环 | a241205 |
| 8 级寨子搜不到（run2 mumu1 六搜全空） | char_jy target_level 8→7（截图证实 7 级寨充足）；打寨子不耗行动力（此前「体力耗尽」系误判） | config |

### 2026-09-18 幽灵集结根因修复（run8-run11 证据链，commits 36f7421/e12942c/3d43388）
**现象**：每轮「连续失败停机」。run11 逐帧（`_cap8/` 12s 采样 + 定向截图）还原出完整根因链：
1. **行动力硬阻塞**（run8/run9）：集结发起+加入集结各耗 150 AP，140 自然上限跑不满 10 轮 → 自动补体力（每日免费 500「领取」1448,379 + 第二行「使用」1447,570；`_launch` 入口先清弹窗残留、补完循环确认关闭，弹窗 X 会被 toast 吞掉）36f7421/e12942c
2. **同城寨锁步静默拒绝**（run11 实锤）：两号城市相邻（X:552-554, Y:557-558，搜索原点相同）→ 永远搜到**同一座**最近 7 级城寨（X:599,Y:583）→ runner 锁步（行军点击仅差 4s）→ 后发起者被游戏**静默拒绝**：表单关闭、无 toast、无队列徽标、任何战争列表都无集结行、不扣行动力。旧实现照旧发布 `rally_launched` → 先手账号成员阶段轮空 6 分钟 `no_rally_found` 连续计败停机，**每轮复现**。run11 第 1 轮其实打赢了（集结 05:47:40 发车，容量 410,000 双号满编，城寨 05:54:21 消失，部队 ~06:08 回城，单轮 ~20 分钟）
3. **四重防护**（3d43388）：
   - **发射验证**（leader_sm）：行军点击后必须等派遣队列徽标出现才承认发射成功；等不到走 LAUNCH→END 放弃边（先于等待成员边注册，SM 契约：异常不重建 SM，raise 会六连撞断路器），绝不虚假唤醒成员
   - **让车门槛**（either_sm）：窗内（480s）对方已发起集结 → 本轮跳过开集结直接转填兵，发布 `rally_skipped`
   - **拒绝降级**：rally_rejected 且窗内对方确有集结 → 竞态输家轮空**不计失败**（弹 ctx failed/fail_reason，防 fail_streak 误停机）；member `no_rally_found` 且自己集结在途 → 同样降级；对方 `rally_skipped`（无集结可填）→ 成员阶段提前收尾进返城等待，不白烧 6 分钟轮询
   - **错峰抖动**：开搜前随机 0-45s，让「谁先发起」逐轮轮换，两号都能练到车头/填兵
   - **RallyEventTracker**（runtime）：进程级集结事件登记簿（跨 SM 重建存活），按 char_id 记录最近 rally_launched/rally_skipped，支撑上面三个决策
- 伴随变更：char_jy target_level 8→7（config）；两模拟器「简化模式」手动关闭（恢复 alliance_btn 等模板可见性）；AP 道具被自动化消耗属预期

### 2026-09-21/23 手工补图入库 + 数据集体检（新增 3 个工具）
**背景**：实机 `annotate_live.py` 预览大量漏标、寨子等级 OCR 读不出数字。根因是**弱类样本太少**——`zhaizi_level_text` 仅 12 实例（AP50 0.199）→ 框检不出 → OCR 拿不到输入。两个现象同一个根因。

- **`raw_imgs/`**（新）：8 个场景目录 + `README.md` 截图规范（必须整屏 1920×1080、不带 overlay、重状态多样性）；`.gitignore` 只放行 README。本轮入库 222 帧。
- **`tools/ingest_raw_imgs.py`**（新）：增量入库，三层预标注（模板匹配 / OCR 文本锚定 `zhaizi_level_text` / 门控位置先验）。**绝不重跑 `auto_label_yolo.py`、绝不重建 `dataset.yaml`**。硬链接入 `dataset/images/`、read-merge-rewrite 合并 train/val、删 `labels.cache`、渲染复核 overlay 到 `logs/review/`。
- **`tools/dedupe_dataset.py`**（新）：按内容去重 + 修 train/val 泄漏。
- **`auto_label_yolo.py` 加全量重建护栏**：它是截断式全量重建（类表从 63 缩回 50、手工追加帧全丢）。现在检测到会丢东西就报错退出（exit 2），要跑必须显式 `--allow-dataset-rewrite`。
- **修 `RapidOcrEngine.detect_text` 缓存 bug**：缓存键用 `id(screenshot)` 却不持有帧引用 → 数组释放后地址被复用时会命中缓存、返回**上一帧**的 OCR 结果。加 `self._cache_img = screenshot` 锁住引用（`yolo_detect.py:54` 早已记录同一条不变式）。

**过程中踩到并修掉的四个坑（均已加回归测试）**：

| 坑 | 现象 | 修法 |
|---|---|---|
| 模板全帧搜 | `preset_1..6` 的 44×44 图标在 6 个预设槽互相串位，**958/1918 个框越界**（`preset_*` 占 908） | 回退 ROI 闸门；ROI 内 0 命中时额外算一次全帧分数**只记分不入框**，让 0 框能区分「真没目标」与「ROI 错位」 |
| `--force` 重跑 val 抽签流偏移 | 同一帧既在 train 又在 val（实测漏 44 行） | `_merge_split(taken=另一 split 的行)`：帧分好不再搬家；收尾对账从 val 侧摘重叠 |
| `--force` 后某帧变 0 框 | 旧标注留在盘上成脏数据 | 撤硬链接 + 删 label，`_prune_split` 摘掉 train/val 失效行 |
| 去重键只有框、没有类 id | 不同类落在同一框时静默吞掉后一个，掩盖状态误判 | 去重键加类 id |

**体检结果**（788 图 / train 717 + val 71，零交集、零失效行、零重复）：
- 弱类实例数：`zhaizi_level_text` 12→**50**、`search_icon`→81、`join_btn`→134、`queue_battle_icon` 25→49、`barb_search_tab`→49、`queue_gather_icon`→20、`queue_fight_icon` 5→7。**仍为 0 实例的只剩 `selected_preset_5`**。
- 去重 10 组，其中 **3 组跨 train/val 泄漏**（v7 的 val 指标因此偏乐观），一律保留标注更全的一份。
- 删 6 张调试裁剪图：`preflight___back_region` 是 160×140 的裁剪却带着按 1920×1080 归一化的框（框完全错位），另 5 张空标注——其中 `preflight__mumu1_lvl_after_crop` 在等级区域上教「这里没有目标」，与 `zhaizi_level_text` 直接矛盾。

**待决策的既有标注约定问题**（非本次引入，未擅自改）：
1. `sort_selector`(18) 混了三种定义：裁剪帧整幅(1901×972) / 全帧顶部整条(1920×213) / 全帧收起条(398×45)——AP50 只有 0.421。
2. `queue_battle_icon`(49) 混了两种尺寸与位置：队列栏小图标(34×34 @ cx0.973) 与战争列表行图标(96×78 @ cx0.485)，33% 越界。
3. **非 1920×1080 的 50 张帧不能删**：`sort_selector` 与 `sort_opt_*` 的实例 100% 来自这些裁剪帧，删了等于把要补的类清零。（原计划的「清理」提议据此作废。）

### 2026-09-24 三个类的标注约定修正（新增 `tools/prune_labels.py`）

**判据来自运行时实现**：`YoloClassAdapter.recognize` 拿**框中心**判 ROI，越界直接 `continue` 丢弃。所以一条标注只要落在 ROI 外（或帧根本不是全屏），运行时**永远不可能被采纳**——它不产生收益，只占模型容量、把同一类的学习信号拉向用不到的模式。据此摘掉 24 条：

| 类 | 修前 | 修后 | 问题 | 处理 |
|---|---|---|---|---|
| `sort_selector` | 18 | **12** | 6 条框占整幅 99%×91%（261×35 裁剪帧里框就是整张图）= 教模型「整张图就是它」 | 摘 6 条退化框。剩下 12 条全是 ~270×31，定义终于统一 |
| `queue_battle_icon` | 49 | **33** | 混了两种元素：队列栏 33×33 @x1868（ROI 内）与战争列表行 70×69/63×52 @cx960（ROI 外） | 摘 16 条。剩下 33 条全是 33×33 |
| `warning_panel` | 7 | **5** | 混了**三块不同的面板**——实测字样分别是「预警」×5 /「警告」/「提示」 | 摘 2 条。剩下 5 条全是 210×58「预警」 |

- **`tools/prune_labels.py`**（新）：三条规则（退化框 ≥90% 整幅 / 有 ROI 的类落在非全屏帧上 / 框中心越出 ROI），默认 dry-run，`--apply` 才写。**摘完变 0 框的帧连帧一起撤**——0 框帧是负样本，而这些帧恰恰是正样本，留着等于教模型漏检。撤 8 帧，train 717→710、val 71→70。
- 数据集现 780 图 / train 710 / val 70，零交集零失效行。297 测试绿。

**踩到的坑**：`prune_labels.py` 第一版**只备份 labels、没备份被撤帧的原图**，8 帧图删掉后 `recordings/` 里也没有原件，只剩标注无从复原（其中 2 张全屏「警告」/「提示」面板图，其裁剪幸存在 `logs/review/_sheet_warning_panel.png` 里才得以判定）。已修为连原图一起备份 + 加回归测试。`--manifest` 参数化后工具可测。

### 2026-09-24（续）`preset_1..6` 的 ROI 重定（`templates/manifest.yaml`）

上一条留下的「`preset_*` 25 条越界」已查清并修掉。**标注是对的，错的是 ROI**，且这个闸门本来就在实机上静默失效。

**为什么窄窗这条路走不通**：六个槽是 44×44 图标，**只差中间一个小数字**。创建部队面板会整体上下移约 80px，而槽间距只有 84px——行程与槽距同量级，所以任何「每槽一个窗」的切法要么裁掉偏高/偏低的帧，要么为了覆盖行程而互相重叠（旧配置 `preset_1` 与 `preset_2` 的窗就已经重叠 10px）。**位置区分不了槽位，只有数字字形能区分**。于是改成六槽**共用一条覆盖整列行程的 ROI** `[1600,350,1712,930]`，把判别权完全交给 `minMaxLoc` 最优匹配。

**关键：标注侧和运行时侧对「匹配」的定义根本不同。** 标注用的 `multi_match` 会把 6 个槽**全部**报出来（全帧实测 1799 命中 / 1406 越界），所以当初的 958/1918 越界是真串位；而运行时 `TemplateMatch.recognize` 只取 `cv2.minMaxLoc` 的**唯一最优**。所以「放宽 ROI 会不会让相邻槽互相匹配」这个顾虑，在运行时侧问法应该是「**最优**那个会不会落到别的槽」。实测 780 帧：落在正确槽位时分数 **≥0.9935**，串到邻槽最高 **0.9616**——分得开。

**阈值必须跟着抬**。旧阈值 0.9 低于串位上限，会放行串位；而串位不是小事：`leader_sm._form_troop` 是 `self._click(f"preset_{N}")` **直接点匹配位置**，点错槽 = **派错兵**。新阈值 0.97，安全窗口 `(0.9616, 0.9935)`。

| 配置 | 正确 | 串位 | 无标注帧误报 |
|---|---|---|---|
| 旧（每槽 100px 窗 + 0.9） | 379 | 3 | **53** |
| 只放宽 ROI（+0.9） | 394 | 3 | **53** |
| 新（共享 ROI + 0.97） | **394** | **0** | **0** |

- 旧配置另有 **25 条标注被窗裁掉** → 新配置只剩 10 条越界，救回 15 条，与模板腿救回的 15 条命中一致。
- **副作用（有意）**：YOLO 兜底腿共用 `spec.threshold`（`build_recognizers`），0.97 等于**对 `preset_*` 关掉兜底**（实测 conf 0.5/0.9/0.96 全不触发，0.97 才触发）。图标在 640 输入下约 15px，模型读不出数字，兜底只会点错槽——宁可让模板失配（`_click` 空操作）也不点错。
- **新增** `tools/measure_preset_roi.py`（重标定用，导出上面四个数 + 阈值扫描）与 `tests/unit/core/test_preset_roi_anchor.py`（5 条锚点：六槽共 ROI / ROI 覆盖行程 / 阈值卡在窗口内 / 不圈编队界面 / 不退回 0.9）。锚点对旧配置实测 4/5 失败，不是空测试。302 测试绿。

**顺带查清的两件事**：
1. **`preset_6` 运行时永不点击**——`march_preset` 是 `Field(ge=1, le=5)`，GUI spinbox 也是 `setRange(1,5)`。`preset_6` 的模板/ROI/标注留着无害，但别指望它有用。
2. **`selected_preset_1..6` 在 `src/` 里零引用**，且 manifest 里没有对应模板（所以无 ROI、无识别器）——纯数据集类，运行时用不到。连同上面那条，说明方案 B 的 63 类里有 7 类目前是死重，是否精简需单独决策（会牵动类 id 重编号，没敢动）。

**仍需人工核对（已报，未擅自改）**：`manual2_formation_205054/205113/205119` 三帧的 `preset_1` 标注框**偏高 25px**（最优匹配分数 1.0000 落在真实图标位置，标注在 25px 外；槽距 84px，所以这明显是标注画歪而非串位）。`tools/measure_preset_roi.py` 会把这类「高分但小幅偏离」单独列出来提示核对。另 10 条越界标注来自 `manual3_formation_222943/222948` 两帧——那是**编队界面**，同一个预设控件出现在 **cx≈1486**（创建部队面板是 cx≈1656），属另一个界面，运行时不会在那时查询预设，所以有意不圈进 ROI。

### 2026-09-24（续）v8 训练 + 寨子等级 OCR 修复（`config.yaml` 已切 v8）

**两个独立 bug 叠在一起，症状都表现为「寨子等级读不出数字」**（用户最初报的问题）。

**bug 1：v8 训练静默跑在 CPU 上。** `runs/gpu_1080_v8/args.yaml` 记 `device: cpu`，GPU 全程 0%/0MiB，131s/epoch 白跑。根因是**用了系统 `python` 而不是项目 venv**：`C:\coding\python` 装的是 `torch 2.11.0+cpu`（ultralytics 8.4.38），venv 里才是 `torch 2.11.0+cu128`（8.4.100）。之前查不出来是因为在 venv 里隔离复现——当然正常。
- `tools/train_yolo.py` 改为**显式传 `device`**（默认 `'0'`）+ `_preflight_device()` 预检：设备要 CUDA 但解释器 torch 无 CUDA 时，直接打印解释器路径/torch 版本/venv 正确路径并 exit 2。`--resume` 分支也覆盖 ckpt 里的 device（否则续跑 CPU ckpt 会继续用 CPU）。文件头 docstring 原本写的是 `python tools/train_yolo.py`——文档自己在教人踩坑，一并改了。
- 1 epoch 探针验证：`args.yaml` 记 `device: '0'`、GPU 显存 1320MiB。正式跑 30 epoch 全程 GPU。

**bug 2：RapidOCR 在文本贴住裁剪边界时整个失败。** 不是降级成低置信度，是**返回空**。同一张肉眼无歧义的清晰裁剪图（"等级: 8"）：

| 处理 | 结果 |
|---|---|
| 无留白 | `[]` |
| 白边 10px | `等级` |
| 白边 40px | `等级：` |
| 白边 60px | `等级：8` |

而 `_ocr_level_text` 的 `pad_y` 只有框高的 **10%**（30px 的框 → 3px），垂直留白几乎为零——少外扩是**有意**的（防滑块像素卷入），所以修法不是撑大裁剪框，而是**裁完补一圈 60px 白边**：既不引入邻居像素，又给足 DBNet 留白。全库 42 个检出框实测 **17/42 → 40/42**，其中 39 个的数字来自含「等级」的文本块。放大倍数在白边存在后不再影响结果（60px 与 60px+2x 同为 40/42）。

**v8 对比 v7（同一 val 集现算）**——必须现算：v7 训练时的 val 集和现在不是同一套（09-24 做过 `prune_labels` 摘 24 条标注撤 8 帧 + preset ROI 重定），读各自 `results.csv` 等于拿两把尺子量。新增 `tools/compare_runs.py` 把两个权重都放到**当前** val 上重跑。

| | v7 | v8 |
|---|---|---|
| mAP50 | 0.6955 | **0.7664** |
| mAP50-95 | 0.5915 | **0.6632** |
| `zhaizi_level_text` | 0.091 | **0.665** |
| `preset_2` / `preset_3` | 0.812 / 0.521 | **0.995 / 0.995** |
| `troop_siege` | 0.388 | **0.995** |
| `barb_search_tab` | 0.695 | **0.995** |

**端到端验证**（`tools/check_zhaizi_level.py`，直接 import `annotate_live._ocr_level_text` 而非复制逻辑）：v7 **0/24 帧**读出数字（总共只检出 2 个框）→ v8 **22/24 帧**（28 个框，26 个读出数字）。两个修复可分离：v8 让框出来，白边让数字读出来。

- **回归**：只有 `selected_preset_3` 0.066→0（该 7 类死重之一，运行时零引用）与 `alliance_btn` -0.079。无实质回归。
- **val 集统计口径**：63 类里 **17 类 val 零实例**（根本测不了），弱类普遍只有 1–3 个实例 → 逐类 AP 噪声很大，别拿单类 0.0 下结论。`queue_fight_icon` 的 0.000 就是 1 个实例的噪声，不代表训坏了。
- `config.yaml app.yolo_model` 已切 **gpu_1080_v8**（顺带修掉那行过期的「v3 权重，50 类」注释）。
- 新增 `tests/unit/tools/test_annotate_live_ocr.py`（7 条：白边存在/白边不引入框外像素/取最右含数字块/合并行抠数字/无数字返回空/空结果/框在画面外不崩）。**去掉白边该测试立刻失败**，非空转。309 测试绿。

### 2026-09-24（续）`zhaizi_level_text` 标注污染修正（等级 1-6 不识别）

v8 上线后用户实测：**「7-10 级可以识别，1-6 级仍不识别」**。在他存下的 10 帧（等级 1..10）上低阈值复跑，坐实是**检测失败而非 OCR 失败**：

| 等级 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| `zhaizi_level_text` 框 | — | — | — | — | — | — | 0.18 | 0.28 | 0.24 | 0.18 |

7-10 有框但置信度只有 0.12~0.28，默认阈值 0.5 下等于不出框；1-6 **一个框都没有**。（这批帧带了 overlay，等级文字上被画过框，所以这个置信度是**偏保守**的下界；实机跑出来是 0.58~0.83。）

**根因：同一类的标注分裂成两套差 8 倍的框。** 三层预标注里的「OCR 文本锚定」那层，按「文本块里含『等级』」取锚点，而 RapidOCR 把

```
等级：3 您的城市附近暂未找到符合条件的野蛮人城寨。
```

**切成两块**，于是同一屏在不同帧上标成了两种东西：

- **紧框 ~95x30**，只圈「等级：N」——33 条（含 `manual3` 的 lvl1..lvl10）；
- **宽框 286~802px**，把后面那句提示文字一起圈进来——**17 条**，全在等级 1~8（且集中在 1~5）。

同一位置、同一类、两种尺寸，YOLO 只能回归到折中：**等级 1~5 那一片紧框只有 ~8 条、宽框有 15 条，宽框占优 → 学不出来**；等级 7~10 紧框有 ~16 条、宽框只 1 条 → 紧框占优，所以只有高等级能出框。这正好解释了「7-10 能、1-6 不能」这个不对称。

另 **2 条是锚错了对象**：`220414-378` / `220422-847` 其实是**世界地图上的城寨信息弹窗**（「等级7 野蛮人城寨」），画面里根本没有搜索面板的等级文本，预标注却锚到了「推荐兵力：1,400,000**等级4**的战斗单位集结进攻」这行提示里的「等级4」。

**修法**：新增 `tools/fix_zhaizi_level_labels.py`（默认 dry-run，`--apply` 才写；写前整份 labels + train/val 备份到 `dataset/_levelfix_backup_<时间戳>/`）。判据**不是**「宽 > Npx」这种魔数，而是「OCR 块的**整块**文字形如 `等级：N`」——含「等级」的长句一律不算锚点，这正是上面那两条污染的成因。锚点存在就把框改成锚点 bbox 外扩 4px，锚点不存在就删这条标注。

- **`PAD=4` 不是随手取的**：OCR 的 bbox 紧贴字形（实测 92x26），而本类**现有**紧框统一留了边距（`manual3` 的 100x34）。外扩 4px 正好对齐（92+8=100，26+8=34），同类内不会再出现两套框尺寸。
- `MAX_W_PX=200` 只用来**筛可疑项**，不是判据：现有紧框最宽 123px，最小宽框 286px，200 落在这个空档里；窄于它的一律不碰（免得把 33 条好标注也拿去重算出漂移）。
- 结果：**改紧框 15 条（330~801px → 98~103px），整条删 2 条；`zhaizi_level_text` 紧框 33 → 48，宽框 17 → 0。** 被删的 2 帧仍保留 `search_icon` 标注，不是空帧——它们含「等级4」（聊天行）与「等级7」（弹窗标题），留作**负样本**正好教模型别在那儿出框。
- 16 帧在 train、**1 帧在 val**（`220422-847`）→ val 组成变了，指标不能与 v8 那份直接比。

**踩到的坑（被新测试逮住）**：`--apply` 原本按「重算出的像素坐标是否完全相等」匹配要改的行，而归一化写回是 6 位小数——801/1920 = 0.417188，取整后重算就偏 1px。真实数据这次 17 条全中纯属侥幸。改成**按行号**匹配，并对不上直接 raise（宁可炸掉，也别静默留下「报告说改了、其实没改」的标注）。

新增 `tests/unit/tools/test_fix_zhaizi_level_labels.py`（14 条：锚点接受/拒绝真实污染长句/冒号半角全角变体/取最左/无锚点返回 None/宽框改紧/无锚点整条删/紧框帧不惊动 OCR/阈值落在空档/apply 前备份且备份里仍是旧框）。**323 测试绿。**

### 2026-09-27 三处补标 + 新类 `city_btn`（64 类）+ v9 训练

用户在 `annotate_live.py` 实机预览里报了三处「不出框」（补充 1/2/3），要求补标后自行展开 v9。

**新增第 64 类 `city_btn`（城堡按钮）**（用户拍板）。主页**地图视图**左下角那一格是回城城堡；**城市视图**同一格是地图图标。`map_btn` 模板实测是地图视图的城堡（见 09-16「城市视图死锁」那条），语义相反，所以新开一类而不是复用。

> ⚠️ **`city_btn` 不在 `templates/manifest.yaml`**。`build_recognizers` 只遍历 manifest 条目，所以**实机控制链路里没有任何识别器会查询它**（`_find("city_btn")` 返 None，不崩）。它目前只对 `annotate_live.py`（整帧裸跑模型）可见。要进控制链路得补 manifest 条目 + 模板图。

**三遍补标 `tools/relabel_extra_classes.py`**（默认 dry-run，`--apply` 才写；写前备份 labels → `dataset/_relabel_backup_<ts>/`）

| pass | 目标类 | 判据（实测间隙） | 结果 |
|---|---|---|---|
| home | `search_icon` + `city_btn` | 门控：`search_icon` 模板在左下 ROI 内 ≥0.85（面板盖住时 0.21~0.39） | 27 帧补 54 框 |
| preset | `selected_preset_1..6` | 槽位亮度占比：选中槽 0.62~0.77 / 未选中 ≤0.09（**7 倍间隙**） | 36 帧补 36 框，跳过 13 |
| sort | `sort_selector` / `sort_opt_*` | 条上「当前排序名」黄字占比：有条 0.038~0.062 / 没条恒 0.000（**37 倍间隙**） | 26 帧 |

- **preset 的互斥**沿用用户手工标注的约定：选中槽的 `preset_N` **换成** `selected_preset_N`，两类不共存（`manual2`/`manual3` 逐帧核对过）。列基准由**槽位编号**最小二乘反推——第一版拿 `min(cy)` 当首槽，选中 1 号时整列错一格，10 个已知帧只对 4 个。
- **sort 的两道闸**：① 非 1920×1080 的裁剪帧一律不碰（`sort_opt_*` 旧标注 18 条全来自 279x162 等裁剪帧，坐标相对裁剪——两套坐标系就是寨子宽框那种病）；② **先问「这条上有没有排序条」再谈下拉展开没展开**。`02_warlist/` 里混着战争详情页（列表滚动/点进某条集结后的界面），那个位置是列表行、没有条。上一版没这道闸，已在 2 帧详情页留下错标注，这次顺手清掉。

**`tools/prune_labels.py` 新增 `has_fullscreen` 规则**：裁剪帧上的标注，只要**同类在整屏帧上另有可用（非退化）实例**就撤帧——「同一类两套坐标系」；反之保留（该类只有裁剪帧，删了就归零，宁可留着）。默认 `False` = 保守：判不了就不删。

**`tools/ingest_raw_imgs.py` 三处加固**

- **内容级去重（md5）**：孪生帧一个落 train 一个落 val，val 指标直接虚高；都在 train 也是同一份输入配两遍不一致的标注。`tools/dedupe_dataset.py` 只看 `dataset/`，管不到入库这一侧——这道闸必须开在入口。实测拦下 7 帧（183 → 176）。
- **先写 split 行再落盘**：中途崩溃留下的是「指向缺失图的 split 行」（`_prune_split` 会摘掉）；反过来留下的是「有图却没有 split 行」的**孤儿帧**，没有任何工具会发现。并加 `_orphans()` 报告 + 修掉 1 个历史孤儿帧。
- 28 帧误分类截图移入 `raw_imgs/_pending_label/`（**文件保留，未删**）：`06_home_map/` 18 帧实为**城市视图**（左下角那格是地图图标，`map_btn` 模板 0.527 标不上；当 0 框入库等于教模型「map_btn 不该出框」，而 `_normalize_view` 正靠它出城）；`04_march_preset/` 8 帧实为**集结进攻弹窗**（`rally_attack_popup` 模板是旧 UI，0.222）；`02_warlist/` 3 帧战争详情页；`07_ap_refill/` 4 帧模板分 0.704 未达阈值。

**v9 训练**：`.venv/Scripts/python.exe -X utf8 tools/train_yolo.py --name gpu_1080_v9 --epochs 30 --batch 8 --imgsz 640 --workers 4`（GPU 全程，1.58~2.05G 显存，~13s/epoch + val）。数据集 **777 帧 / 708 train / 69 val / 64 类 / 2994 实例**。

**同 val 对比 v8（`tools/compare_runs.py gpu_1080_v8 gpu_1080_v9`）**

| | v8 | v9 |
|---|---|---|
| mAP50 | 0.7382 | 0.7247 |
| mAP50-95 | 0.6523 | 0.6207 |

整体 **−0.0135**。val 只有 69 帧 / 249 实例 / 44 类，**最大涨跌几乎全是 1 实例类**（`char_mgmt_btn` −0.663 是 1 个框、`alliance_btn` −0.281 是 3 个框、`sort_selector` −0.166 是 1 个框）——单类 0.0 或 0.99 都别下结论（09-24 已记过，这次又一次）。唯一像样的 6 实例级跌幅是 `queue_gather_icon` 0.466→0.000，但**在全部 5 个含该类的 val 帧上，v8 和 v9 都一个框都不出（conf ≥0.05）**，即 YOLO 兜底在两个版本里本来就是死的——该类由模板主判（校准 1.00/0.99/0.84，阈值 0.75），不构成运行时风险。涨的：`selected_preset_4` 0.000→0.995、`queue_march_icon` +0.323、`troop_check` +0.124、`search_icon` +0.011。

**val 指标掩盖了真正的问题——补标目标类得看整帧裸跑**（`annotate_live.py` 的用法）。在带目标元素的**训练**帧上跑 v8/v9（无 ROI 门控、conf 0.35）：

| 帧 | 标注 | v8 | v9 @0.35 |
|---|---|---|---|
| `06_home_map` 215548-458 | `search_icon` | 无 | `search_icon@0.59` |
| `06_home_map` 221951-427 | `search_icon` + `city_btn` | 无 | `search_icon@0.66` + `city_btn@0.36` |
| `02_warlist` 221849-452（下拉展开） | `sort_selector` + 3 行 | 无 | `sort_selector@0.80` + `sort_opt_latest@0.66` |
| `02_warlist` 221548-596（收起） | `sort_selector` | 无 | `sort_selector@0.28`（**低于 0.35**） |
| `04_march_preset` 220038-723 | 槽 3 = `selected_preset_3` | 无 | `preset_4@0.06`（**类别错**） |

**结论：补充 1 修好了；补充 2/3 只修了一半，剩下的根因是样本数、不是标注。**

- `selected_preset_N` 在选中槽上**输给 `preset_N`**：同一像素位置上 `preset_N` 有 57~73 条、`selected_preset_N` 只有 3~17 条（**13~20 倍**），模型默认押多数类。标注本身没错（两类互斥），但少数类赢不了。36 帧里选中槽分布极偏：1 号 13 帧、4 号 10 帧，5 号只有 3 帧、6 号只有 2 帧。
- `sort_selector` 收起帧 0.28 差一点：全库只 21 条，20 条在 train、**1 条在 val**。
- `city_btn` 27 条**全在 train、val 零实例** → val 指标根本没测它。

**要真修补充 2/3，需要的是更多帧（每类几十条量级），不是再标一遍**：选中态 2/3/5/6 号槽各补 10+ 帧（现 6/6/3/3）；战争列表**收起**态（未展开下拉）补 10+ 帧；`city_btn` 补几帧进 val，否则永远测不了。

**`config.yaml app.yolo_model` 已切 `gpu_1080_v9`**。切它的理由是**功能**而非指标：补充 1 的那两帧 v8 一个框都不出、v9 出；而 v8→v9 的整体差在 val 上属噪声。回滚只需把那行换回 `runs/gpu_1080_v8/weights/best.pt`。

**回归**：**358 测试绿**（新增 `test_prune_labels.py` 6 条、`test_ingest_raw_imgs.py` 8 条、`test_relabel_extra_classes.py` 4 条）。`dataset/dataset.yaml` 全程只读、64 类未变。

### 2026-09-27 运行时到底谁在识别（模板 vs YOLO）

用户问「实机运行时哪些是 YOLO 识别、哪些是模板匹配」。**答案是没有一个元素由 YOLO 主判——全部模板先行，YOLO 只在模板失配时兜底。**

装配在 `TemplateRegistry.build_recognizers`：每个 manifest id → `RecognizerChain([TemplateMatch, 兜底], threshold=0.0)`。链的 `threshold=0.0` 意味着**谁先报 `matched` 谁赢**，而两条腿各自报 `matched` 用的是**同一个 `spec.threshold`**：`TemplateMatch` 是 `max_val ≥ spec.threshold`，`YoloClassAdapter` 是 `conf ≥ spec.threshold`。所以模板没到阈值才轮到 YOLO，且 YOLO 也得过同一个门槛。

**53 个 manifest 条目的实际装配**

| 链 | 条数 | 说明 |
|---|---|---|
| 模板 + YOLO 兜底 | **50** | 正常路径 |
| 模板 + OCR 兜底 | **2** | `fill_阑珊寨子号` / `fill_Jy丶阑珊`——角色名与账号绑定，**故意不训 YOLO** |
| 纯模板（无兜底） | **1** | `queue_recall_icon`——被 YOLO 排除训练，挂兜底会在运行时 `_resolve_class_id` KeyError |

**门槛分布**：0.9 ×35、0.85 ×5、0.8 ×2、0.75/0.65/0.6/0.55/0.5 各 1、**0.97 ×6**。

> ⚠️ `preset_1..6` 的 0.97 是**有意把 YOLO 兜底关掉**（09-24 preset ROI 重定时的副作用，见上文）：图标在 640 输入下只有 ~15px，模型读不出槽位数字，兜底接手只会**点错槽**（`leader_sm._form_troop` 是 `self._click(f"preset_{N}")` 直接点匹配位置，串位 = 派错兵）。所以这 6 个是**纯模板**。其余 44 个的兜底门槛是 0.9/0.85 这种高度，实际也很少接手——**模板才是主力**。

**14 个类数据集里有、`manifest.yaml` 里没有 → 实机零引用**（只服务于 `annotate_live.py` 整帧裸跑预览与训练）：

`selected_preset_1..6`、`sort_selector`、`sort_opt_latest/nearest/shortest`、`city_btn`、`zhaizi_level_text`、`barb_search_tab`、`troop_check`

这解释了为什么用户报的补充 2/3 在实机上「没识别到」与 val 指标无关：那几个类在实机链路上**根本没有识别器**。要进控制链路得先补 manifest 条目 + 模板图（`city_btn` 现在就是这个状态）。

**顺带纠正一处文档误导**：`zhaizi_level_text` 的等级 OCR **不在实机链路里**。车头设等级是盲进（`level_minus ×12 / level_plus ×N`，不回读结果等级，`leader_sm.py:40-41` 记为已接受限制），`src/` 里没有任何代码读它；OCR 读等级只在 `tools/annotate_live.py` 预览与 `tools/check_zhaizi_level.py` 体检里用。之前本文档在「三识别栈融合」下写「方案 B 下寨子等级数字也走 OCR」，容易被读成运行时行为，已改。

### 2026-09-29 状态类改由像素判据接管（`selected_preset_*` / `sort_*` 摘出 YOLO）

承接上文「补充 2/3 只修了一半」的根因（`preset_N` 57~73 条 vs `selected_preset_N` 3~17 条，**同一像素位置差 13~20 倍**，模型永远押多数类），本次不再靠补标，改为**像素判据**。新增 `src/rok_assistant/core/recognizers/pixel_stat.py` —— 判据与几何的**唯一真相**，运行时与预览共用同一份，不可能漂移。

**几何实测钉死，绝不从标注反推。** `cx=1655`（44 帧零方差），槽 N 中心 `cy = 474 + 82*(N-1)`。旧 `plan_preset` 用 `fit_slots` 从**被校验的标注本身**反推列基准，是个闭环：标注错→几何错→自洽地错（实测 `top` 在 391~475 双峰漂移）。现在固定几何采样，`fit_slots` 降级为**交叉校验**：拟合值偏离 474 超 15px 就整帧不动。实测确有这类帧——`failure_*`（09-12）/`smoke__*`（09-07）的**标注**列基准在 448、`manual3_222851/222904/222930` 在 ~390。这两簇的来源**不同、只有一簇能确定**：390 ≈ 392 = 474−82，正是顶部菱形那一格，所以 `manual3_*` 那簇就是 09-27 记的菱形污染；448 那簇（474−26，既不是一个槽距也不在菱形上）来源未定——可能是更早会话里面板真的在别处，也可能是那批标注本身用了别的锚。**反正两种情况下都不该动**：交叉校验不通过就整帧跳过，是 fail-closed，比猜一个基准去重写好。

**两个实测陷阱（都锚了回归测试）**

1. **顶部菱形 `cy≈389`**：恒亮块（55×54，mean BGR `[231,175,8]`），`frac 0.80` —— **比任何真选中槽都亮**（真选中 0.72~0.75），且正好在槽 1 上方**一个槽距**（474−82=392）。44/44 帧都在，是永久 UI 构件、不是脏数据。**从 y=391 起扫 6 格就会把它当成槽 1**：这正是轨道自动定位不可用的原因——以菱形为锚的 base=392 得分**高于**真值 base=474。故 `slot_centers()` 从 474 起，永不取样它；硬编码 474 是工程上的正确选择。
2. **第 7 个槽 `cy=966` 真实存在**：`04_march_preset__MuMu-20260921-220257-719` 视觉确认芯片 1–7，8 格扫描里 966 有 6 帧选中。所以扫 7 格（让「没有选中态」和「选中的是第 7 槽」在日志里分得开），但只给 1..6 装识别器（`march_preset` 取值域）。

**判据与余量**：`frac = mean(patch.max(axis=2) > 200)`，槽心 ±22px 的 44×44。选中 **0.72~0.75** vs 未选中 **0.07~0.09**，**8~10 倍余量**；44 帧 argmax **41/44**（3 帧失手全是**标注本身错**，不是判据错）。fail-closed：`matched=True` 仅当「过闸 **且** 赢家就是自己」——最坏失败是「没点预设」，**永远不会是「点错槽」**。

**纠正一处我自己的测量错误**：计划里写的「25 个错标（3 个标在青色元素上 + 22 个整体偏高一个槽距）」是**我读错 YOLO 字段**造成的假象——标签格式是 `class cx cy w h`，我用了 `r[2]/r[3]` 当 cx/cy。按正确索引重测：真正的错位只有 `manual2_formation_*` 的槽 1 框在 446 而芯片在 474（5 帧），其余都在 ~9px 以内（标签间距 83.8 vs 真实 82）。所以本次预设侧的实际价值是**消除 `fit_slots` 闭环**，不是「修 25 个错标」。（manifest 里 09-27 写的「25 条被窗裁掉」是旧**每槽窄窗**配置的代价，与此无关。）

**落地**

| 位置 | 改动 |
|---|---|
| `recognizers/pixel_stat.py`（新） | 常量 + `bright_frac`/`yellow_frac`/`mean_v`/`slot_center`/`panel_verdict` + `PresetSlotJudge`（单帧缓存，键 `(id(screenshot), shape)` 且**持强引用** `_last`——否则帧回收后 id 复用会读到上一帧结论）+ `PixelStatRecognizer`（`bbox` 恒返回本槽 44×44 全屏框，`matched` 才是判据）+ `build_preset_recognizers` |
| `templates/manifest.yaml` | 顶层新增独立小节 **`pixel_stats:`**（`kind: preset_slot`，1..6）。**刻意不放进 `templates:`**：`TemplateRegistry.load` 要求 `entry["file"]`，而 `auto_label_yolo.py`/`ingest_raw_imgs.py`/`measure_preset_roi.py`/`relabel_extra_classes.py` 会对每个 spec `cv2.imread(spec.file)`——假 file 会**注入垃圾框**（正是这几轮在清的污染模式）。`registry._t` 一字未动，四个工具与 `test_preset_roi_anchor.py` 零影响 |
| `workers/leader_sm.py` | `_form_troop` 里裸 `self._click(f"preset_{N}")` → `_select_preset()`：先模板点 + `_wait_for("selected_preset_N", 2.0s)` 确认；模板失配=点击空操作则按实测几何 `_click_xy(*slot_center(n))` 兜底；3 轮不确认 **raise**（两号 `march_preset` 相同，点错是**系统性**错，宁可 loud 失败也不派错兵）。无该识别器时退回旧盲点行为（`test_leader_sm.py:83` 的 26 击断言靠这道守卫保持绿） |
| `workers/state_machine.py` | 新增 `_click_xy(x, y)`，与 `_click_result` 并列、同样走 `self._handle.click`（保留反检测抖动） |
| `tools/relabel_extra_classes.py` | 判据/几何全部从 `pixel_stat` import（保留私有别名重绑定，`src` 是库、`tools` 消费，绝不反向）；`plan_preset` 改固定几何 + 交叉校验；选中槽框**吸附到实测几何**；修掉「已有 `selected_preset_N` 还追加一条」的重复 bug（dry-run 报 `补 36` → 修后 `补 0 / 换 36 / 跳过 8`） |
| `tools/annotate_live.py` | 预览跑的是**裸 YOLO**、不走识别器栈，所以显式接一步（同 `_ocr_level_text` 先例）：先**滤掉** YOLO 的 `selected_preset_*`/`sort_selector`/`sort_opt_*` 输出（实测模型在标注为槽 3 的位置给 `preset_4@0.06`，不滤就是真框假框一起画），再加像素检出；绘制时中文标 `◇像素`、cv2 标 `[px]`，来源如实区分 |

**排序 UI 两条判据（互相独立）**：`yellow_frac(SORT_SELECTOR_PX) ≥ 0.010` 判「有没有条」（23 帧复测：有条 0.0375~0.0623，无条恒 0.0000）；`mean_v(SORT_DARK_ROI) < 90` 判「下拉展开没展开」（展开 30~90，收起 118~187）。**激活项没有判据**——三行填充/亮度一致，只有文字不同，所以预览只画条和下拉，三行的 `conf` **必须完全相同**（有差别就等于在声称哪一行是激活项，已锚测试）。`SORT_YELLOW_MIN=0.010` 是在 `02_warlist` **内部**标定的，不能跨屏迁移：创建部队弹窗那块罩着兵种行读数 **0.03**，照样过闸 → 必须用 `war_title` 门控，预览里宁可假阴性也不假阳性。

**重标已应用**：36 帧重写（全部吸附到 `slot_center(n)` 且 `frac > 0.60`），备份在 `dataset/_relabel_backup_20260929-200454/labels/`（777 文件），已删 `labels.cache`。

**回归**：**423 测试绿**（358 → 401 → 423）。新增 `tests/unit/core/recognizers/test_pixel_stat.py`、`tests/unit/tools/test_annotate_live_pixel.py`（16 条，含「不在战争列表上不找排序 UI」回归）、`test_relabel_extra_classes.py` 5 条（列基准偏离即跳过 / 几何吸附 / 永不取样菱形 / 不重复追加）。

**待验证（尚未跑）**：`tools/annotate_live.py --conf 0.35` 的实机预览，与实机一轮 `_run_goal.py` 看 `_select_preset` 是否 1 次点击即确认。

### 2026-09-12/13 修复清单（全部来自实机发现）
| 问题 | 修复 | commit |
|---|---|---|
| 点「+」后表单出不来 | `join_create_btn` 模板：先点派遣队列侧栏的「创建部队」气泡 | 6c51c35 |
| queue_panel 阈值 0.9 漏检（0.893 卡死帧） | 阈值降到 0.8 | — |
| 连续 9 搜无结果停机（等级缓存失步） | no_result 清缓存，重试前全量重同步 | a7a8177 |
| 两台同秒误判城寨「锁定」（弹窗慢加载） | 锁定判定 5s→10s | bbd0bcf |
| 成员 50s 轮询窗口 < 集结准备窗（solo 发车） | 10→60 次（~5-6 分钟） | a122c50 |
| 行动力不足弹窗死堵 | `ap_refill` 模板 + 关闭分支；耗尽走 3 轮失败自然停机 | aa52841 |
| WAIT_RETURN 行军后 2s 误判「已回城」 | 先关战争面板再读徽标 + 延迟一拍下结论 | aa52841 |
| 创建部队表单/搜索面板/集结弹窗残留 6 连异常 | 各自 normalize 恢复分支 + 回归测试 | 8579330 |
| **仅采集队在外空等 25 分钟**（用户反馈） | `queue_gather_icon`（绿色锄头）识别，仅采集不阻塞 | fa7fec7 |
| **上轮集结未回城就开下一轮搜寨**（用户要求 09-13） | **战斗队列门槛**：`queue_march_icon`（绿色脚印=行军）/`queue_flag_icon`（蓝色旗帜=驻扎/集结等待）在轮次入口（IDLE/NORMALIZE）拦截等待；无徽标或仅采集在外放行。WAIT_RETURN 同一判据重写 | f891eef |
| **门槛漏防复发（09-14 用户报告）**：集结期间仍重入搜索。实机两次误判：mumu0 22:27:16 部队刚出发被判「仅采集」、mumu1 22:37:43 行军中被判「队列已空」 | 根因：badge/flag 模板裁剪含背景像素，换场景正样本掉到 0.884/0.724（阈值之下）。紧裁剪重采两模板（badge 阈值 0.9→0.85）；判据改 `_queue_verdict` 四值，**unknown fail-closed**（等待返城继续等/入口拦截，超 5 分钟宽限期才放行告警）；实机 round1→round2 干净过渡验证通过 | b4bf4c7 |
| **双 worker 六连异常收工（09-15 00:09-00:22）**：mumu0 被底部快捷菜单展开态遮蔽（展开时联盟旗帜被整体隐藏）、mumu1 被「预警」警报面板（自动弹出）全屏盖住 | `menu_expanded`/`warning_panel` 两模板 + 两 SM normalize 恢复分支（点 ☰ 1845,1010 收起菜单 / 点 X 1671,64 关面板）；2026-09-16 实机验证菜单收起有效 | 5fdb010 |
| **队列图标模板质量（09-16 发现）**：09-14 版 queue_flag_icon 实际裁剪偏移主体是背景（自匹配 1.000 掩盖问题），实机旗帜漏检 0.459；图标圆心透出统帅头像，含背景模板跨头像掉分（gather 1.0→0.709） | 三图标 HSV 定位纯圆重裁：gather 正 1.00/0.99/0.84 跨头像、flag 1.000、march 纯圆，负全 ≤0.49；阈值 gather 0.75/flag 0.8/march 0.85，正负边际 ~0.05→~0.3 | 185156b |
| **预设主将未回城误开集结（09-16 用户报告）**：主将在返程/战斗态（黄色返回、红色交叉刀剑图标未覆盖）时 unknown 宽限 5 分钟一到就放行，默认武将代开车打不过寨子 | `_queue_verdict` 战斗元组扩展 `queue_return_icon`/`queue_battle_icon`（模板采样中，`_qsamples/` 后台采集）；unknown 宽限 5→15 分钟；battle 判定无宽限（越过宽限仍拦截，回归测试覆盖） | f9acef6 |
| **误开集结复发（09-16 用户报告二）**：主将战斗/返程态无模板时，混合队列里采集锄头匹配成功 → verdict='gather' 掩盖未识别战斗态照常放行（用户已手动取消集结） | `_qsamples/` 实机采样补齐四模板并全量校准（真识别链零误报）：`queue_battle_icon` 红交叉刀剑 0.5（正 7 帧 0.534-1.0/负 ≤0.466）、`queue_return_icon` 橙返程箭头 0.55（正 5 帧 0.619-1.0/负 ≤0.509）、`queue_recall_icon` 红盘白上箭头 0.65（正 1.0/0.719/负 ≤0.506）入 battle 元组——09-17 实机确认该帧实为战斗动画挥舞中的一帧（无独立召回态），模板保留同判 battle 无害；红盘系模板互有串扰但同判 battle 无害，漏检方向 unknown=fail-closed 安全 | 105ae30 |
| 部队已在集结中点「+」弹「部队替换」卡死（mumu0） | 不替换（白回城+多烧行动力），关弹窗走 VERIFY_JOINED 回读橙「替换」；两 SM normalize 加残留分支 | f891eef |
| **面板遮挡误判「无队列」（09-16 重启后实机）**：战争列表面板开着时右侧队列栏整体隐藏，queue_badge 判 False → 门槛放行搜索（mumu0/mumu1 双中招，mumu1 六连异常收工） | `_queue_verdict` 用「联盟旗帜可见=在地图视图」判读：地图上徽标消失才是真无队列；不在地图先关 war_title/warning_panel（X 1671,64），本拍 unknown fail-closed；`_find` 未匹配/未配置均返 None，用 `_rec.get` 区分 | 6834cc1 |
| **战斗中动画变体（09-16 用户截图 imgs/）**：刀剑图标是逐帧动画，双剑平行（不交叉）变体与交叉刀剑模板相似度仅 0.62-0.90，存在漏检带 | myrok-56 并行会话补 `queue_fight_icon`（多尺度反查原生帧 + HSV 纯圆裁剪，正 0.644-1.0/真负 ≤0.441，阈值 0.6；0.52-0.55 串扰带均为同判 battle 的红盘系），入 battle 元组 | 7a57c8d |
| **搜索面板残留白等宽限（09-16 实机 21:08 mumu1）**：搜索模式专属底栏同样整体隐藏队列栏，门槛判 unknown 拦截却没关面板，白等 15 分钟 | unknown 分支补 `search_back` 退出（bbox 居中点击） | e2ee7fb |
| **城市视图死锁（09-16 两号齐卡实锤）**：队列栏不显示、alliance_btn/map_btn 均不匹配——map_btn 模板实为地图视图的「进入城市」城堡 (92,985)，城市视图出城按钮是地图图标 (72,1034)，语义相反且无模板 → 门槛无动作可做 | unknown 分支无面板可关时直接点出城按钮 (72,1034) 回地图重新判读；实机验证死锁解除 | dde4bc5 |


### 2026-09-29 实机验证结果（补记，回应上面「待验证」那条）

- `tools/annotate_live.py --conf 0.35 --once` 在 mumu0 上跑通（capture→YOLO→绘制无异常）。
  战争列表帧上画出 **`排序选择器 0.04 ◇像素`**，框套在「最新发起」上——像素判据生效，
  且 YOLO 对 `sort_*` 的输出被正确滤掉（只出一条）。下拉收起故无 `sort_opt_*` 行，符合预期。
- `_run_goal.py` 实机：**`[车头] 预设槽 1 已确认（模板点击，第 1 轮）`**（20:31:40），
  随后「集结已发起：7 级城寨（预设槽 1）」。一次模板点击即确认，未走几何兜底、未抛异常。
  全日志 `预设槽.*未确认|异常|Traceback` 计数 **0**。
- **新发现（非本次改动引入）**：`queue_flag_icon` 在 mumu1 队列栏上稳定读 **0.758 < 阈值 0.8**
  （连抓 6 帧方差 0，位置正确 (1846,306)，其它队列模板全 ≤0.45）→ `verdict=unknown` →
  集结门槛 fail-closed 15 分钟 → mumu1 本轮不发起集结、mumu0 成员窗口白等，
  第 1/10 轮以「填不到兵」结束。修法建议重采模板而非降阈值（负样本集是照旧美术测的）。

### 2026-10-01 计划 A（判据层）落地（spec `2026-09-30-健壮状态判断与任务队列-design.md` 的前半）

**背景**：09-29 实机发现——`queue_flag_icon` 稳定读 0.758、连抓 6 帧方差为 0 → `_queue_verdict`
落 `unknown` → fail-closed 等 900s 宽限 → 到点告警放行 → 车头部队其实在外，开集结被游戏
**静默拒绝** → `rally_rejected` 计入连续失败（mumu0 吃到 2/3，再 1 次整轮停机）。
**方向性关键**：蓝旗语义是「驻扎/集结等待」=**阻塞**态，读对了反而会拦住这次注定被拒的开车。
所以 0.758 漏检不是「多等一会」，是**把安全的拦截变成了有害的放行**。

**根因（判据层缺位）**：唯一判据是像素，而像素会**稳定地**错。修法不是降阈值（那是拿假阳换假阴），
而是引入**可信度分层**：账本（自己写下的确凿事实）> 消息（跨 SM 直接消息）> 画面（像素）。

**交付（12 commits，`0cfd458..2f3a5c7`）**：
1. **`coordination/action_ledger.py`（新）**——进程级 `ActionLedger`，`threading.Lock` 保护，
   按 `char_id` 记 `troops_out / troops_out_since / last_rally_launched_ts / last_fill_ts / written`。
   **`written` 与 `troops_out` 成对**：只有「已确认」的动作才写（见第 3 条）。
2. **`workers/queue_gate.py`（新）**——`QueueGate.observe(verdict)` → `GateOutcome(decision, reason,
   verdict, source)`，`source ∈ {vote, ledger, grace}`；`VOTE_SIZE=3`、`unknown_grace=900.0`、
   `LEDGER_STALE_AFTER=3600.0`。**本计划的核心不变式**：多帧投票**只能延迟（hold WAIT），
   永远不能翻转**——投票不得把 `unknown` 变成 PROCEED。假阳代价是白等 15 分钟，假阴代价是
   一个注定被静默拒绝的集结且计入连续失败（3 次整轮停机）。
   `test_vote_only_delays_never_flips` / `test_vote_after_settled_unknown_never_proceeds` 钉住它。
3. **账本写入点**：`leader_sm` 发车确认后写、`member_sm` 填兵确认后写、`either_sm` 返城
   （`"none"` 落空分支）写。**未确认即不写**——`leader_sm` 的写入点另加
   `self._rec.get("queue_badge") is not None` 守卫：队列徽标识别器没配置就无法确认，
   不能记下未确认的效果。
4. **`runtime.py` 下发同一个 `ActionLedger` 实例**给三个 SM。集成测试按**对象同一性**断言
   （不是相等），防止将来改成各建一个。
5. **`core/recognizers/view_probe.py`（新）**——`ViewProbe` 一次截屏判 7 个视图 + 未知；
   `_normalize_view` 失败时抛 `归一化失败：卡在[创建部队]视图`，取代原先无从下手的
   `search_icon 不可见且 map_btn 归一化失败`。单个识别器抛异常按**未命中**处理并记 warning
   （`scores` 完整性被测试钉住），不让一个坏识别器炸掉整条归因。
   **`_normalize_view` 的清理清单没有被重写成探测循环**——里面每个 `if self._find(...)` 的顺序
   与坐标各对应一次实机事故（见本文件 09-16/09-17 各条），重写等于把踩过的坑再踩一遍。
6. **`infra/config.py` 的 `find_level_collisions`**——同等级且**至少一方填对方**时启动告警。
   两号同为 7 级互相填兵会命中此告警，**是有意的**：它正是「让车门槛 / `_FOREIGN_RALLY_WINDOW`
   该退休」的信号（删除本身留给计划 B）。

**测试**：423 → **478 绿**（+55，264.89s）。新增 7 个测试文件：`test_action_ledger.py`、
`test_queue_gate.py`、`test_action_ledger_writes.py`、`test_either_sm_gate.py`、
`test_normalize_view.py`、`test_view_probe.py`、`test_level_collision.py`。

**计划自身的 4 处缺陷（执行中发现并裁定，不是静默吸收）**：Task 2 的「10 passed」实为 **9**
（plan 文字错）；Task 4 的测试自相矛盾（`mark_troops_out(now=0.0)` 而门槛读墙钟 →
`troops_out_seconds≈1.79e9 ≥ 3600` → 断言方向与预期相反）；Task 5 的「早返回」实现**无法满足
它自己的** `call_count == 1` 测试（唯一解是删掉早返回）；Task 7 的 `_cfg` 造出违反真实
`RootConfig` 校验规则的配置（`either` 配空 `fill_target_leaders`）。

**修正 spec §八.2**：`_FOREIGN_RALLY_WINDOW` 在 `either_sm.py` 有**三处**用途（`:18` 常量、
`:127` 让车门槛、`:157` `rally_rejected` 降级、`:181` 成员提前收尾），不是 spec 写的「一个分支」。
其中 `:157` **必须被 Mailbox 的消息驱动降级取代**而非删除——直接删会让 `rally_rejected`
永远计入失败，正好退回 spec §六 要修的那个 bug。`:181` 则因 `:127` 不再发布 `rally_skipped`
而变成死代码。删除本身留给计划 B。

**待验证（尚未跑）**：Task 8 Step 2/3 的实机验证被推迟——模拟器未启动（`adb devices` 为空，
`adb connect 127.0.0.1:16384` / `:16416` 均报 `10061 目标计算机积极拒绝`）。
需启 MuMu、连 adb、两号登录后跑 `_run_goal.py`，然后 `grep -E "集结门槛" _driver.log`：
期望出现 `放行（判据来源 ledger）` / `grace` 且**不再有** `未知队列图标已持续 900.0s，放行搜索`；
再 `grep -E "卡在\[" _driver.log`。

**遗留**：`queue_flag_icon` 0.758 **仍未解决**——多帧投票消不掉**方差为 0 的稳定错读**
（三帧读到同一个错值，投票只是把同一个错答案数三遍）。它现在被账本挡在门外（部队在外时账本
直接判 WAIT），但**账本只在「本轮自己发起过」时才有话说**，跨轮 / 驱动重启后的第一个 unknown
仍会落到宽限放行。真正的修法是重采模板（需要实机截图）。

### 2026-10-03 补记（上一条的两处更正 + 最终评审结果）

**更正一：配置已变。** 上一条写「两号同为 7 级互相填兵会命中告警」——那是 2026-10-01 写作时的实况。
用户在 10-03 前改过 `config.yaml`：现在是 mumu0「阑珊寨子号」(either, 7 级) ⇄ mumu1「**阑珊填1**」
(either, **8 级**)，角色名也从「Jy丶阑珊」改成「阑珊填1」。所以 `find_level_collisions` 现在返回**空**，
启动告警**不会**出现。这正是计划 B 删让车门槛的前提条件。

**更正二：`queue_flag_icon` 0.758 对填兵方没被挡住。** 上一条说「它现在被账本挡在门外」——只对
**开过车的**那一号成立。填兵方（只填兵不开车的轮次）的 `mark_troops_out` 没有配对的清零路径，
账本永远停在「部队在外」，下一个 `unknown` 仍走 900s 宽限。详见 `docs/PROGRESS.md` 的
「计划 A 已知缺口」一节（含原因与触发条件）。

**最终评审（0cfd458..63df703，最强模型）**：0 Critical / 2 Important / 5 Minor。
- 结论 **With fixes**。安全不变式（投票只延迟不翻转；未确认不写账本）被独立验证为**实现正确且钉得住**，
  评审员无法构造出「投票或账本导致占用队列被错误放行」的调用序列。
- Important #1 = 上面「更正二」，裁定为 **park + 触发条件**（spec 自身缺口、fail-safe、修法属计划 B）。
- Important #2 = **本计划引入的新静默死等**：投票迟迟无法采信（判读在两态间反复）时 `settled` 恒为
  `None`，`observe` 返回 WAIT 且**从不启动宽限计时**，账本路径也进不去 → 车头永久停在 IDLE，
  而 runner 没有轮级超时。旧实现单帧即可放行，不会这样卡死。**已修**：投票超过 `UNSETTLED_AFTER`
  仍未采信则按 `unknown` 处理，交给账本 / 宽限接手。
- 5 条 Minor 全部 park（`settled == "battle"` 无上限等待属旧行为；`_normalize_view` 少 ~2s 重试预算
  即 Ruling 18；探针帧未存 `last_image`；`ViewProbe` 每号建两次；文档等级叙述与配置不符——已更正）。

#### 计划 A 裁定存档（28 条，含「错了会怎样」）

执行期（Task 1-7）：
1. Task 7 只交付 `find_level_collisions()` + 启动告警，不动 `config.yaml`（用户说自己改）。错：告警可能在其改完前误报一次，非阻塞。
2. Task 7 测试用合成配置（`RootConfig.model_validate`），不读 `config.yaml`。错：无成本。
3. Task 8 实机验证算「暂定」——配置可能改到一半，grep 不到 `卡在[` 不算 bug。错：实机证据推迟给用户，单测证据不受影响。
4. Task 1 的 4 条 Minor 全 park（读方法会插默认条目／并发测试用不同 key 测不出锁／`snapshot` 对 `slots=True` 脆弱／缺 `from __future__`）。错：将来 `char_id` 无界或加字段时要回头修，会在改动点暴露。
5. 计划写「Task 2 有 10 passed」是错的，**9** 才对。错：无成本。
6. `queue_gate.py:109` 的 `>=` 按计划保留（计划文字说「超过」）。错：恰在 3600.0s 边界早放行 1 秒。
7. `VOTE_SIZE`/`LEDGER_STALE_AFTER` 是默认参数，`monkeypatch.setattr` 对它们无效——park。错：将来想全局改这两个值的测试会静默失效、可能因错误原因通过。
8. `written` 与 `troops_out` 的耦合（`mark_rally_launched`/`mark_fill_done` 只设 `written`）跨任务携带、不当场修。错：将来任何只设 `written` 不设 `troops_out` 的写入点会把 unknown 静默变成放行——正是本计划要消灭的 fail-open。
9. `QueueGate.observe` 无锁、分三次读账本——park。错：将来跨线程共享 `QueueGate` 会读到撕裂视图。
10. either→member 交接加 `char_id=self._char_id`（超出 brief 文字）——接受。错：无成本。
11. 车头写入点在 `queue_badge` 未配置时无像素确认——确认不是现行 fail-open，仍在修轮补了守卫。错：该配置下不写账本，退回保守的 fail-closed 宽限路径。
12. 成员写入点缺 `char_id` 守卫——park。错：将来新的直接构造点会记到 `"?"`、被门槛忽略（退化成无账本）。
13. Task 4 brief 的测试自相矛盾（`now=0.0` vs 墙钟），采纳实现者的 `now=time.time()`。错：无成本。
14. `either_sm.py:127` 的 `放行（判据来源 …）` 告警没节流——park。错：那段窗口内日志刷屏。
15. runtime 共享账本下发没有测试——**升级为必修**（原本只是 Minor）。不修的代价：`ledger=self.ledger` 一旦被删，每轮重建账本、L0 永久退化成宽限，**且没有任何测试会红**。
16. Task 5 brief 的实现与它自己的测试互相矛盾——采纳「只删早返回」为唯一解。错：每次 probe 多跑 ~13 次 `cv2.matchTemplate`（有帧缓存，有界）。附：我提的「`VIEW_PRIORITY` 会变死代码」假设**被评审员驳回，他是对的**。
17. `ViewVerdict` 冻结却持有可变 `scores`；`UNKNOWN` 的 `confidence` 硬编码 `0.0`——park。错：将来有消费者改 `scores` 会让人意外。
18. Task 6 删掉的恢复路径（不再走 `_search_fortress` 的 3 次 `search_icon` 重试）——接受。错：`卡在[` 异常增多，计入 6 连 step 异常断路器。**触发条件：实机日志里 `卡在[` 变多就恢复重试。**
19. Task 6 两条 Minor park（`member_sm.py:3` 未使用的 `View` 导入；`test_member_sm.py:269` 只断言 `卡在[` 前缀）。错：(a) 无；(b) 那一处指错视图名抓不到，但专门测试会抓。
20. Task 7 brief 的 `_cfg` 造出违反真实校验规则的配置——采纳实现者改成 `role: "leader"`。错：无成本。
21. Task 7 告警文案「互为填兵目标」与单向 `or` 不符——**修**。错：一句日志文案。
22. Task 7 没有测试告警真被发出——**尝试补**，给了逃生口。错：无。
23. Task 8 Step 2/3 **推迟**（模拟器没起），不是跳过。错：门槛的 ledger/grace 与 `卡在[` 文案未在真机验证——逻辑都有单测，未验的是集成读数。
24. Task 8 Step 1 结果：478 passed / 264.89s。
25. Task 8 Step 4/5 完成（`63df703`）。范围说明：`.trae/skills/superpowers` 的改动不是本次工作，未 stage。

最终评审后：
26. 最终评审 Important #1（填兵方账本 `troops_out` 永不清零）**park + 触发条件**。错：计划 A 的头号收益对填兵方没兑现；但方向安全（账本只产出 WAIT，永不错误放行），且与计划 A 之前逐字相同，**不是回归**。触发条件：计划 B 的 FillTask，或实机日志再次出现填兵方的 900s 放行。
27. 最终评审 Important #2（投票迟迟无法采信 → 静默死等）**修**（`da90641`）。错：有界地落到同一条 unknown 路径（本来就有 900s 宽限），方向是设计已接受的那个。
28. 最终评审 5 条 Minor 全 park；其中 1 条是文档错误（等级叙述说 7⇄7，实际 7⇄8），直接更正。错：文档继续误导下一位读者。

**回头先读这四条**：#18、#26（带触发条件），#4、#7、#8、#12（「将来改动会撞到」类）。

**计划 A 收尾（2026-10-03）**：15 commits `0cfd458..72466e3`；全套 **481 passed**；最终评审 0 Critical / 2 Important（一修一 park）/ 5 Minor 全 park；定向复评「all findings addressed, no new breakage」。SDD 工作区已删（`.superpowers/sdd/2026-09-30-判据层/`），git 历史是记录。

## 2026-10-03 实机：日志乱码 + 预设列整体上移 42px

真机跑 `_run_goal.py` 报的两个问题，都定位到根因并修了（尚未跑完整验收）。

### 1. `_driver.log` 全是双编码乱码

**现象**：`杩炵画 6 娆?step 寮傚父` 这种。`杩炵画` 就是「连续」的 UTF-8 字节被按 GBK
解码的产物——典型双重编码。

**根因**：`python -X utf8 _run_goal.py > _driver.log`（PowerShell 5.1）两边编码打架——
Python 按 `-X utf8` 吐 **UTF-8 字节**，PowerShell 却按 `[Console]::OutputEncoding`
（本机 cp936）**解码**，再以 UTF-16LE 落盘。字节级验证：不带 `-X utf8` 时 Python 输出
`\xc1\xac\xd0\xf8`（GBK 的「连续」），带 `-X utf8` 时输出 `\xe8\xbf\x9e\xe7\xbb\xad`
（UTF-8 的「连续」）。

**只影响控制台那半边**：应用自己的 `logs/rok_assistant_*.log` 一直是干净 UTF-8
（`FileHandler` 不经过控制台）。

**修**：`_run_goal.py` 加 `_align_stdout_encoding()`——`GetConsoleOutputCP()` 读控制台
实际代码页（`chcp` 改过就是新值），`sys.stdout.reconfigure(encoding=f"cp{cp}",
errors="replace")`。`errors="replace"` 兜住代码页外的字符，别让一行日志把进程带崩。
必须在 `setup_logging` **之前**调：`StreamHandler` 持有的是 `sys.stdout` 这个**对象**，
reconfigure 改的就是它，控制台那半边同样受益。

### 2. 开集结卡在「创建部队」面板：预设列整体上移 42px

**现象**：驱动卡死不动，日志末行
`RuntimeError: 预设槽 1 高亮未确认（3 轮），拒绝派错兵，集结未发起`。

**根因**：`pixel_stat` 的预设槽判据按实测钉死的 `cy = 474 + 82*(N-1)` 取样，
但今天 9 帧实机量到的白框中心是 **`432 + 82*(N-1)`**（框高 42px，槽 1/2 中心 432/514，
9 帧零方差）——**整列上移 42px**。

关键：`march_btn` 仍在 (1395,925)、`form_title` 仍在 (960,68.5)，**只有预设列动了**。
所以「拿面板框当锚点」救不了，写死哪个值都只是换一个将来会过期的常数。

**模板点击本身是对的**：`preset_1` 模板在 (1656,430) 命中、得分 0.988，点击确实落对了槽；
坏的是随后用于确认的像素判据低了 42px，永远读不到高亮 → 3 轮重试 → 抛错拒绝发车。
（fail-closed 方向是对的：宁可不发车，不派错兵。）

**修（用户选的「自适应标定基准」）**：不再写死基准，改成运行时从帧里校准——
- `PresetSlotJudge.calibrate(top)`：挪基准 + 作废本帧缓存（缓存键含 `top`）；
- `PixelStatRecognizer.calibrate` 转发给共享 judge（同一列六个槽共用一份基准，调一次就够）；
- `leader_sm._calibrate_preset_column(hit, n)`：拿 `preset_N` 模板命中的 `cy` 反推
  `top = cy - 82*(n-1)`，**仅在命中落在预设列 ROI 内时**（`PRESET_COL_HALF_X = 56`；
  manifest 里 preset_* 的 roi 是 x 1600..1712）——真实命中必然在列里，列外的命中不是槽心。
- `PRESET_TOP = 474` 仍是默认值与标定锚点（测试钉住），**不再是运行时唯一真相**。

**已知取舍（记下来）**：若模板真的串到邻槽（命中错槽），基准会**跟着串**，确认就成了自证——
判据永远同意模板。这条由 0.97 阈值挡住：正确槽下限 0.9935、跨槽上限 0.9616，780 帧 0 次串位。
**将来若降阈值，这个自证风险要重新评估。**

**顺带发现**：
- 失败截图有时是在屏幕已经变了之后才截的（15:16 那帧是地图不是面板）——排查时别当现场。
- `mumu0` 当时是 `paused`（模拟器窗口消失）。

**测试**：`test_pixel_stat.py` +3（`panel_verdict` 收 `top` / `calibrate` 推动识别器 /
`calibrate` 作废缓存）；`test_leader_sm.py` +4（反推基准 / 列外命中忽略 / 基准推给 judge /
面板移动时自校准）。

### 数据集「0 框帧」污染清理（2026-10-03）

**起因**：用户问「训练集里是不是有非标准尺寸的图，会不会污染」。

**结论**：尺寸不统一**无害**（标签是归一化坐标，训练统一 letterbox 到 `imgsz: 640`）；
真污染是 **0 框帧**——777 帧里有 31 张标签为空。

**两类 0 框帧、两个成因**：

1. **模板素材裁剪图被当成检测样本灌进 `dataset/images/`**（24 张，全部非 1920x1080）：
   `scenes___z_join.png`(270x210) 画的就是绿色「+」按钮（`join_create_btn`），标签 0 行；
   文件名与类名一一对应（`z_redrally`→`red_rally`、`z_wartitle`→`war_title`、
   `z_magnifier`→`search_icon`、`z_sort`/`z_sorted`→`sort_selector`、
   `z_tabs`→`barb_search_tab`、`z_level`→`zhaizi_level_text`、`z_blue`→`blue_rally` ……），
   另有 4 张 `window_check__win_*.png` 窗口截图 + 1 张 `failure_i1_c1_*.png`(100x100)。
   **判据是尺寸**：manifest 的 ROI 是 1920x1080 绝对像素，裁剪帧的归一化坐标对不上
   屏幕位置，运行时永远不可能被采纳（`prune_labels.py` 规则 2）。撤掉不可能让任何类
   归零——它们的标签本来就是 0 行。
2. **动画过渡帧落在阈值下**（整屏 7 张里确认 1 张）：
   `failure_mumu1_char_jy_20260915_001019.png` 与四张已标 `warning_panel` 的帧近乎同图
   （64x36 灰度 mad=0.0087），而它自己的 `warning_panel` 模板读数只有 **0.664 < 阈值 0.85**
   ——就是 `queue_flag_icon` 0.758 那个病的同款：入库时读不到 → 写成 0 框。
   其余 6 张跑遍 53 个模板，最高原始分 0.654，全部远低于各自阈值 → 判背景、保留。

**为什么现有护栏没拦住**：`prune_labels.py` 只管**被自己摘空**的帧，管不到**生下来就是
0 框**的帧（且默认只跑 3 个类）；`dedupe_dataset.py` 只看逐字节相同（md5），抓不到
mad=0.009 这种视觉同图。

**新工具 `tools/audit_empty_frames.py`**：遍历 `images/`（不是 `labels/`——标签文件缺失
也是 0 框帧），分两组出报告。裁剪帧组按尺寸判、`--apply` 撤；整屏组靠近重复判
（64x36 灰度 mad，`--max-mad` 默认 0.03），**只出报告，`--drop <帧名>` 点名才撤**
——近重复是概率证据，不替人拍板。默认 dry-run，写前整份 labels + train/val +
**每一张被撤帧的原图**备份到 `dataset/_emptyfix_backup_<时间戳>/`。

**顺带修**：`dedupe_dataset.py` 删帧时**没有备份**（直接 unlink），违反本仓库自己定的
「删帧必须连图一起备份」规则——补上同款备份块 + 测试。

**安全性核对**：53 个 manifest 模板文件的 `file:` 全相对于 `templates/`，无一指向
`dataset/`；全仓无代码引用 `scenes___*` / `window_check__*` / `failure_i1_c1*`；
带标注的裁剪帧（`manual4_sort_open_*` / `manual5_fix_sort_open_*`）不在判据范围内，
一根汗毛不动。

**测试**：`test_audit_empty_frames.py` +11、`test_dedupe_dataset.py` +1。

**待办**：`--apply` 未执行（写盘动作被权限分类器拦下，需手动跑）：

    .venv/Scripts/python.exe -X utf8 tools/audit_empty_frames.py --apply \
        --drop failure_mumu1_char_jy_20260915_001019.png

预期 777 → 752 帧、train 708 → 684、val 69 → 67（val 少 2，指标不能与上一版直接比）。

---

## 2026-10-04 · YOLO 先行：链顺序对调 + 阈值解耦 + 定标

**用户要求**：「调整 yolo 和模板匹配的先后顺序，优先使用 yolo 进行匹配。」
走 `superpowers:brainstorming` 的 bounded 路径（设计在对话里给、停下等点头，不写 spec 文档）。

### 先摆数据，再动代码

改之前先量「YOLO 到底比模板强在哪」。三帧实机画面（`search_icon`）：

| 帧 | 模板分 | YOLO conf | 阈值 0.9 |
|---|---|---|---|
| `failure_..._095713`（当天卡死那帧） | 0.879 | 0.845 | **两个都没过** |
| p0 | 0.918 | 0.538 | 模板过 |
| p1 | 0.998 | 0.867 | 模板过 |

**结论一**：三帧上模板都 ≥ YOLO，且失败帧两边都够不到 0.9。**光调顺序救不了那帧**——
链返回第一个 `matched` 的，YOLO 在 0.9 阈值下 `matched=False`，照样落到模板。
真正卡住的是「YOLO 共用模板阈值」这条耦合。

**结论二（blast radius）**：53 个 manifest 条目里 50 个有 YOLO 腿，全都会受影响。

### 定标（本次最花时间、也最出意外的部分）

`tools/calibrate_yolo_threshold.py`：对每个 id，把 val 65 帧分成
present（GT 有此类的帧，取 YOLO 最大 conf）/ absent（GT 无此类**且模板也没命中**的帧，
取最大 conf = 假阳性地板）。阈值要落在两者之间。生产里 `YoloClassAdapter` 按框心过滤 ROI，
所以定标也必须套 ROI，否则测出来的假阳性生产根本看不到。

**首版结论是错的，而且错得很有诱惑力**：不修正标签时，`search_icon` 地板 0.721 / 最小正 0.649
（重叠），`alliance_btn` 更是「有它的 3 帧全 0.000、没它的帧 0.480」（反相关）。
照这个结果，正确做法是**放弃这个方向**。

**翻案证据**：逐帧 dump 发现 `search_icon` 的所有检出（含「无 GT」的帧）都落在同一位置 (85,811)；
两个「无 GT」帧是 `03_queue_panel__*` 队列面板场景。用模板做裁判——
`03_queue_panel__...220756-394` 上 `search_icon` 模板 **1.000**（框心 (86,811)）、
`alliance_btn` 模板 **1.000**（框心 (1846,869)），正是 YOLO 报出的位置。
**图标明明在画面里，是标注漏标了常驻 HUD。**

修正后（absent 剔除模板命中帧，漏标单独计数）：

| id | 最小正 | 中位正 | 假阳地板 | 漏标 | 判读 |
|---|---|---|---|---|---|
| level_minus | 0.933 | 0.976 | 0.000 | 0 | 干净 |
| search_btn | 0.921 | 0.981 | 0.000 | 0 | 干净 |
| war_title | 0.935 | 0.952 | 0.000 | 0 | 干净 |
| join_btn | 0.922 | 0.948 | 0.000 | 0 | 干净 |
| march_btn | 0.897 | 0.964 | 0.000 | 0 | 干净 |
| troop_infantry/cavalry/archer/siege | 0.853-0.960 | 0.907-0.969 | 0.000 | 0 | 干净 |
| search_icon | 0.649 | 0.868 | **0.000** | 2 | 干净（首版误判） |
| search_back | 0.338 | 0.963 | 0.000 | 1 | 弱，但有模板腿兜 |
| **alliance_btn** | **0.000** | **0.000** | **0.480** | 3 | 漏检 + 真误报 |
| **queue_march_icon** | 0.876 | 0.876 | **0.689** | 0 | 间隙仅 0.19 |
| preset_1..6 | 0.000 | 0.45-0.93 | — | 0 | 完全漏检 |

**全局统计：46/50 个 id 的假阳性地板 = 0.000。** 15 个类 YOLO 完全漏检（正样本帧上不出框）
——**无害**，YOLO 不触发就落到模板，行为与改前一致。

### 改动

1. `core/template_registry.py`
   - `TemplateSpec` 加 `yolo_threshold: float | None = None`；`load()` 读 manifest 的 `yolo_threshold`。
   - 新增模块常量 `DEFAULT_YOLO_THRESHOLD = 0.5`（附「换模型要重标」说明）。
   - `build_recognizers`：YOLO 腿用 `yolo_threshold`（不再用 `spec.threshold`）；
     `template_match` 链装配成 **`[YOLO, 模板]`**；`fill_*` 保持 `[模板, OCR]`；
     无 YOLO 类的 id 保持纯 `TemplateMatch`。
2. `templates/manifest.yaml`：`preset_1..6` / `alliance_btn` 写 `yolo_threshold: 1.01`（关腿）、
   `queue_march_icon` 写 `0.85`。8 个条目带覆盖，其余吃全局默认。
3. `tools/calibrate_yolo_threshold.py`：定标脚本（从临时脚本提升——阈值常量跟着模型走，
   换权重必须重标）。
4. 测试：`test_yolo_fallback_respects_threshold` **重写**为
   `test_yolo_threshold_decoupled_from_template`——它原来断言的「YOLO 0.6 < 模板阈值 0.9 → 不命中」
   正是本次要拆掉的耦合。新增顺序锚定 `test_yolo_wins_over_a_matching_template`、
   覆盖关腿 `test_yolo_threshold_override_can_disable_the_leg`、
   fill_ 仍模板先行 `test_fill_leg_stays_template_first`。

### 效果与遗留

失败帧 `failure_mumu0_char_zhaizi_20261004_095713` 现在 `视图=地图 命中=('search_icon',)`：
YOLO 0.845 命中，框心 (83,810) 与模板 (86,811) 差 3px（8px 抖动内）。p0/p1 也照旧命中
（改由 YOLO 腿给出）。

- **实机复跑已过（10-04 11:52 起，两号各 3 轮）**：见下节。
- **`search_back` 的 0.338/0.379 两个弱正样本**说明 YOLO 在这个类上不稳；有模板腿兜着，
  但若模板也掉分，这里会先暴露。
- **13 个类 val 无正样本**（`red_rally`/`swap_btn`/`settings_btn`/`tab_fortress`/`replace_popup`/
  `click_to_enter`/`switch_confirm_yes`/`char_avatar_*`/`char_mgmt_title`/`profile_title`/
  `toast_no_fortress`/`queue_battle_icon`）：顺序翻转对它们是**未验证**的，已观测到的
  假阳性地板均为 0.000。
- **ViewProbe 的判定跟着变了**（它复用同一批链）：`search_icon`/`alliance_btn` 是 MAP 锚点，
  YOLO 更容易命中 → MAP 判定更灵敏（今天那个「归一化失败」顺带缓解）。反过来，
  `map_btn` 若误报会把 CITY 顶到 MAP 前面；实测 `map_btn` 在 0.5 下惰性（正样本最小 0.427），
  暂不构成问题。

### 实机复跑（2026-10-04 11:52 起，两号各 3 轮）

改完当天下午就拉了真机跑（用户要求）。驱动脱离式启动（`nohup .venv/Scripts/python.exe -X utf8
_run_goal.py > _driver.log 2>&1 &`），日志落在 `logs/rok_assistant_20261004_115236.log`。

| 指标 | 改前 09:48 那次 | 本次（YOLO 先行） |
|---|---|---|
| `归一化失败：卡在[…]` | **18 次** → 连 6 次 step 异常收工 | **0 次** |
| ERROR 总数 | 多次（全是归一化） | **1** |
| 完成轮数 | 0（mumu0 没跑完一轮就停） | mumu1 3 轮 / mumu0 3 轮 |

轮次时间线：mumu1（`阑珊填1`，member）1@11:56:26 → 2@12:04:12 → 3@12:12:08；
mumu0（`阑珊寨子号`，leader）1@12:01:03 → 2@12:08:29 → 3@12:16:36。全链路
`NORMALIZE → SEARCH_FORTRESS → SELECT_RALLY_TIME → FORM_TROOP → LAUNCH` 与 member 的
`OPEN_WAR → FIND_JOIN → CLICK_JOIN → …` 都跑通，**没有一次 `卡在[`**。

改动要解决的正是 `归一化失败`（模板 `search_icon` 0.879 < 0.9 → 视图判 unknown）。改前那次的
18 次失败与本次的 0 次，就是这个改动的直接产出。

#### 唯一一条 ERROR：预设槽 1 高亮未确认（既有问题，非本次引入）

12:10:19 mumu0 抛 `预设槽 1 高亮未确认（3 轮），拒绝派错兵，集结未发起`，runner 记
「出现异常，已截图记录，退避后自动重试」，25s 后 12:10:42 走 `预设槽 1 已确认（几何补点，第 1 轮）`
自愈，该轮最终完成。

**判定它是既有问题，靠两条证据，不是靠感觉：**

1. **历史日志里有原样复现**。`logs/rok_assistant_20261003_152733.log` 与
   `…_151151.log`（10-03 两次运行，在任何改动之前）都有同样的
   `预设槽 1 高亮未确认（3 轮），拒绝派错兵，集结未发起`，且前面同样是 3 次
   `模板点击后未确认，按实测几何补点`。同一条代码路径、同一个 RuntimeError 串。
2. **代码路径上这次改动够不着它**。`_select_preset` 里点击位置来自 `self._find(f"preset_{n}")`，
   而 `preset_n` 的 YOLO 腿被 `yolo_threshold: 1.01` 关掉，`[yolo@1.01, 模板@0.97]` 等价于
   改前的纯模板行为（`_calibrate_preset_column` 拿到的 `hit` 也是同一张模板给的）；确认判据是
   `selected_preset_{n}`，走**像素判据**（`recognizers/pixel_stat.py`），根本不经过识别链。

**顺带纠正一个差点用错的对照**：我一度想拿 `_driver_run1_20261004.log` 当基线，`grep` 返回 0
就以为「改前没这症状」。实际那文件是轮转时创建的 **0 字节空文件**——0 是「文件空」不是
「症状不存在」。改前真正的基线在 `logs/` 下按时间戳命名，不在根目录的 `_driver*.log`。

## 2026-10-04 · 纯车头补挂集结前置门槛（bug：主将在城外就开集结）

用户报的原文：「目前在集结开始之前没有检测是否有行军队列。导致集结武将在城外未回归时
就开始集结，选不中武将。请在集结开始之前检查是否有在外的行军或返回或集结中的队列」。

### 根因（不是「门槛判据不对」，是「门槛没接在这条路上」）

`QueueGate` + 队列判读这套东西 10-01 就做完了，判据本身没问题——问题是它只挂在
`EitherStateMachine.step()` 里。而 `factory.create_state_machine` 对 `role == leader`
返回的是**裸** `LeaderStateMachine`：

```python
if character.role == RoleEnum.LEADER:
    return LeaderStateMachine(...)          # 没有 gate
```

当前 `config.yaml` 里 `char_zhaizi` 正是纯 `leader`，于是它每轮开头**一次都没查过队列**，
上一轮集结部队还在行军/返程/集结中就直接开下一轮。武将不在城里 → 「创建部队」表单载不出
预设 → 卡在 `预设槽 N 高亮未确认`。这与 10-04 实机复跑里那条唯一 ERROR 是同一个症状家族。

判据实现本来就在错的地方：`EitherStateMachine._queue_verdict` 整段只用 `self._leader._rec` /
`_find` / `_handle` / `_refill_ap` ——它从头到尾讲的就是车头自己的事，只是因为历史原因长在
either 上。纯车头要它，就得先把它挪到 `LeaderStateMachine`。

### 改动

| 文件 | 改动 |
|---|---|
| `workers/leader_sm.py` | `queue_verdict()` 从 either 搬入（方法体逐行等价，`self._leader.X` → `self.X`）；`__init__` 收 `queue_gate=None`；新增 `step()` 覆写，在 `IDLE`/`NORMALIZE` 入口观测门槛，`WAIT` 就原地返回；`_gate_log()` 30s 节流 |
| `workers/either_sm.py` | `_queue_verdict` 留一层薄壳 `return self._leader.queue_verdict()`（保住既有测试对 either 实例的 `monkeypatch.setattr(sm, "_queue_verdict", …)`）；给自己的子车头显式 `queue_gate=None` |
| `workers/factory.py` | `role == LEADER` 且 `ledger is not None` 时构造 `QueueGate(ledger, character.id)` 注入 |
| `tests/unit/workers/test_leader_sm_gate.py` | 新增 7 条 |

两个设计点值得记住：

1. **either 刻意不给子车头传门**。either 自己那面门已经在 `step()` 里观测同一份判读，再给
   子车头一面，`QueueGate` 的内部投票缓冲和 `_unknown_since` 计时器会被同一批帧喂两遍，
   采信节奏翻倍（3 帧变 1.5 帧），`unsettled_after` 也跟着错。
2. **门槛放行时补写账本回城**。纯 leader 原本只有 `_launch` 里的 `mark_troops_out`，
   **没有对应的回城写入**（either 那边是在 `WAIT_RETURN` 判空时写的，纯 leader 不走那条路）。
   不补这一笔，账本会永远停在「在外」——而门槛的 unknown 分支正是读账本的，图标一旦不可辨
   就会 fail-closed 干等 `unknown_grace`（900s）。那等于把「开错车」换成「卡 15 分钟」，
   修了个寂寞。

### 写入口径：只在 `verdict == "none"`，`gather` 不写

一开始我写的是 `verdict in ("none", "gather")` 都写，理由是「仅采集队列在外 = 战斗部队已回」。
改成只写 `"none"`，因为两处硬约束：

- `ActionLedger.mark_troops_home` 的 docstring 自己写着口径是**「派遣队列判空」**，而
  `gather` 恰恰是队列**非空**；账本的立身之本就是「只记已确认的事实」。
- `test_either_sm_gate.py::test_wait_return_gather_does_not_mark_home` 已经把这个口径钉死在
  either 侧（理由：写回城会让下一轮门槛误判）。同一面旗帜、同一个问题，两处给出不同答案
  是纯负债。

代价：采集队列在外的轮次账本仍停在「在外」，后续遇 unknown 会多等一段。**方向安全**——
账本只会产出 WAIT，永远不会错误放行。这个取舍与 PROGRESS「计划 A 已知缺口」里那条是同一个
（纯 leader 这一侧已随本次关闭，缺口只剩 either 的纯填兵轮次）。

### 测试

新增 7 条，钉住：拦得住（`battle` → 留在 IDLE 且 `gate._settled == "battle"`）、
放行时补写回城（`none` → `troops_out is False`）、`gather` 放行但**不**写回城、
未采信（`unknown`）时不写、未注入门槛时行为逐字节不变、factory 真的接了线、
没账本时 factory 不接门。

### 实机验证（2026-10-04 13:46 起，驱动重启）

改完就重启驱动跑真机（先杀干净上一轮遗留的两个 `_run_goal.py` PID，再
`nohup .venv/Scripts/python.exe -X utf8 _run_goal.py > _driver.log 2>&1 &`）。
`config.yaml` 里 `char_zhaizi` 正是纯 leader，改动直接落在它身上。

**拦住的那一轮（第 3 轮，实锤）**：

```
14:03:03  [集结门槛] 队列判据尚未采信（投票 1/3 帧）
14:03:36  [集结门槛] 有行军/驻扎队列在城外，等待回城后再搜索
14:04:09  [集结门槛] 有行军/驻扎队列在城外，等待回城后再搜索
14:04:36  mumu0 -> SEARCH_FORTRESS        ← 队列清空后放行
```

第 2 轮 13:56:55 发起、约 14:00:55 发车（绿脚印）、14:01:50 到寨子开打
（红交叉刀剑），第 2 轮在 14:02:29 结束时**部队正在寨子战斗中** —— 这正是用户报的
场景。门槛把 mumu0 摁在 `IDLE` **93 秒**（14:03:03 → 14:04:36），一拍没搜，
队列判空后才放行。改前这里会直接开搜 → 武将不在城里 → `预设槽 N 高亮未确认`。

**独立佐证**：第 2 轮开头（13:55:27）门槛是**放行**的。这不是漏判——43 秒后
13:56:17 打出「预设槽 1 已确认（模板点击，第 1 轮）」，说明那一刻主将确实在城里。
判据与实际状态一致。

**判据本身用探针复核过**（`_probe_queue.py`，只读抓帧打印各模板分数，不点击）：
部队在寨子战斗时 `queue_battle_icon` 命中、`queue_badge` 0.9+；队列清空后
`queue_badge` 掉到 0.19、各图标 0.25~0.42、判读 `none`。分数分布与判读方向一致。

### 顺带修掉一处误导性日志（验证过程自己踩的）

`_gate_log` 的 30s 节流不分内容，于是**每轮第一拍固定的「投票 1/3 帧」会把窗口吃掉**，
紧接着真正采信的那条「有行军/驻扎队列在城外」被压掉。日志读起来像「门槛放行了」——
我在看 13:55:27 那一轮时就是这么被误导的，一度以为修了没用。改成**换了理由立刻打、
同一条理由仍节流**（leader 与 either 两处同口径），并加测试钉住。

#### 遗留

- 驱动在 12:18 仍在跑（mumu0 第 4 轮），未跑到 10 轮自然停止点；上面的结论基于前 3 轮。
- `预设槽 1 高亮未确认` 这个既有问题**没修**：它自愈了，且根因是像素判据取样位置，属于
  10-03 那条线的遗留，与 YOLO 先行无关。要修得单开。

## 2026-10-04 · 城寨等级改多选 `target_levels`（搜不到就换下一级）

用户原话：「多次搜索城寨搜索不到时，可能是因为对应等级的寨子在附近已经被消灭殆尽。
此时加入失败次数检查，多次搜不到时，可降低一级进行搜索并集结」。随后经三轮问答收口：
**复数字段 + 1–10 复选框**（用户答「使用复数字段，使用1-10复选框」）、**每级 5 次**
（「改成 5 次」）、**跑完一圈就放弃**、**下限即列表最低级**（不另设 `min_level`）、
以及最后一条覆盖：**「希望列表顺序完全自由（比如想 6→4→5）」**。

> 我一开始提的校验是「必须降序」（理由是降级语义自然降序），被用户明确否掉。
> 记住这条：**列表顺序是用户的表达，不是可推导的约束**——校验只该管
> 「非空 / ≤3 / 1..10 / 不重复」。

### 改动

| 层 | 文件 | 改了什么 |
|---|---|---|
| 配置 | `infra/config.py` | `target_level: int` → `target_levels: list[int]`；新增 `MAX_TARGET_LEVELS = 3` 与 `_check_levels` 校验（非空/≤3/1..10/不重复，**不管顺序**） |
| 配置 | `infra/config.py` | `find_level_collisions`：判据由「`a.target_level == b.target_level`」改成 **`set(a.target_levels) & set(b.target_levels)` 非空**，文案改成报出真正重叠的那几级 |
| 状态机 | `workers/leader_sm.py` | `_MAX_NO_RESULT` 3 → **5**；构造参数改名 `target_levels`，存 `self._target_levels`；新增 `_current_level(ctx)`（= `_target_levels[ctx["level_index"]]`，**不做越界钳制**）；`_select_level` 用当前下标；新增 `_switch_level` 与降级边；`_launch` 发布当前等级；`_give_up` 日志报「已试等级」 |
| 状态机 | `workers/either_sm.py` / `workers/factory.py` | 构造参数与传参改名，两个角色都传 `character.target_levels` |
| GUI | `gui/config_dialog.py` | `QSpinBox` → 1–10 复选框（2 行 × 5）+ 「搜索顺序：…」标签；勾选顺序即搜索顺序；选满 3 个后未选中的框置灰；表格列显示 `8→7→6` |
| 配置 | `config.yaml` / `config.example.yaml` | 两个角色迁成列表 |

### 状态机细节（值得记住的两点）

**降级边的注册顺序。** `StateMachine.step` 按注册顺序取**第一条** from_state 匹配且 guard
通过的转移，所以 `CHECK_RESULT` 的三条出口必须按「重试 → 降级 → 放弃」排：

```python
self.add_transition("CHECK_RESULT", "CONFIRM_SEARCH", self._retry_search,
                    guard=lambda ctx: ... no_result_count < _MAX_NO_RESULT)
self.add_transition("CHECK_RESULT", "CONFIRM_SEARCH", self._switch_level,
                    guard=lambda ctx: ... no_result_count >= _MAX_NO_RESULT
                    and level_index + 1 < len(self._target_levels))
self.add_transition("CHECK_RESULT", "END", self._give_up,
                    guard=lambda ctx: ctx.get("search_outcome") == "no_result")
```

最后那条 `_give_up` 的 guard 只判 `no_result`：**「还有下一个等级」这个条件由降级边的
guard 表达**，绕完一圈（下标越界）自然落到这里。两条 guard 用 `>=` / `<` 互补，互斥。

**计数按级清零，不是整轮额度。** `_switch_level` 里 `no_result_count = 0`。因此
`_give_up` 的日志**不能**报累计次数（会读成「只搜了 5 次就放弃」），改报
`self._target_levels[:level_index + 1]`（已试过的等级）。

**`_current_level` 不做钳制。** 下标越界由转移 guard 挡在 `_switch_level` 之前；若在这里
`min(idx, len-1)` 静默钳制，「下标算错」会被伪装成「一直在搜最后一级」——最难查的那类问题。

### GUI 的顺序表达

复选框天然表达不了顺序（`6→4→5` 和 `4→5→6` 勾出来一模一样）。做法：

- `self._level_order` 保存**勾选先后**，`_refresh_level_order()` 把它写成
  「搜索顺序：6 → 4 → 5」显示在下方；
- **信号在 `setChecked` 之后再接**——否则初始化回填会按回调顺序重排 `_level_order`，
  配置里存的顺序就丢了（这条有专门测试 `test_level_boxes_initialized_from_config_in_order`）；
- 想调顺序 = 取消再重勾（重勾排到末位，`test_level_recheck_moves_to_end` 钉住）；
- 超上限时**撤销本次勾选**而不是弹窗（`setChecked(False)` 递归回 `_on_level_toggle`，
  但那时 level 已不在列表里，等于无操作）。

### 测试（+21 条，533 → 554）

- `tests/unit/workers/test_leader_sm.py` +5：`test_max_no_result_is_five`、
  `test_switch_to_next_level_resets_counter`、`test_full_cycle_over_three_levels_gives_up`
  （15 次 CHECK_RESULT）、`test_switch_order_follows_config_not_sorted`（6→4→5 照走，
  用 `_LEVEL_CACHE` 观察每步实际设的等级）、`test_found_after_switch_launches_that_level`。
  **注意**：造「搜不到」不能用 recognize 调用次数判定——每次 `CHECK_RESULT` 失败时
  `_wait_for` 按 interval 会重试 9 次（timeout 8.0 / interval 1.0），改成传
  `found_when(ctx)` 判据回调。
- `tests/unit/infra/test_config_models.py` +6、`tests/unit/infra/test_level_collision.py` +2、
  `tests/integration/test_config_dialog.py` +7、`tests/unit/workers/test_worker_factory.py` +1
  （工厂按序原样透传列表）。
- `test_no_result_toast_retries_then_ends` 的期望由 3 次改 5 次（单元素列表 = 旧行为）。
- 全套 `pytest tests/ -q` → **554 passed / 278.20s**。

### 迁移时容易漏的

`target_level` 是**位置参数**（第 3 个），所以除了关键字调用，`test_state_machine.py` 里
4 处 `LeaderStateMachine(handle, {"x": rec}, 7, 1, ["cavalry"])` 这种**位置传参**也会炸，
grep `target_level=` 抓不到——改字段名时两种调用都要扫。

---

## 2026-10-04 实机验证：10 轮完整闭环（target_levels 降级 + 计划 A 门槛）

`_run_goal.py`（mumu0 leader 阑珊寨子号 / mumu1 member 阑珊填1）17:54:11 起跑，
19:49:56 双方 `10/10 轮完成`，驱动 `全部 worker 已收工` 自行退出。全程约 116 分钟，
日志 `_driver.log`（旧日志备份为 `_driver_prev_*.log`）。

### 两项待验功能均通过

- **`target_levels` 降级路径**：实机触发 2 次 —— 19:25:30、19:41:32
  `[车头] 6 级连续 5 次搜不到，改搜 5 级（列表第 2/3 个）`，随后设 5 级并
  `集结已发起：5 级城寨`。6 级城寨被清光后按列表顺序降级、计数按级清零、每次
  全量重同步等级，行为与单测一致。代价：第 9、10 轮因此明显变慢（每级 5 次无结果 ×
  每次「降到底再升到目标级」约 1.5 分钟）。
- **计划 A 判据层**：门槛全程 **0 次** 900s 宽限放行（`未知队列图标已持续…` 0 条），
  改为 **17 次** `队列图标不可辨，账本显示部队在外 Xs，继续等待`（source=ledger，决策 WAIT）。
  即 `queue_flag_icon` 读不可辨（unknown）时，**账本覆盖了旧的 grace 放行**——正是 10-04
  阻塞条目想要的修复：把「安全拦截」从「有害放行」改回来。
  `放行（判据来源 ledger）` 0 次：账本始终判「在外」，不需要放行。
  两次典型区间：18:37:47–18:38:01（在外 382→392s）、18:48:05–18:48:30（402→427s）、
  19:00:19 前（401→435s），随后图标重新可辨转 `battle`。

### 实机抖动（均已退避自恢复，未致停机）

1. **车头 `_launch` 行动力临界失败 ×3**（18:23:35 / 19:04:26 / 19:43:42）：
   `行动力补充后 march_btn 点击失败，集结未发起`。链路：`leader_sm.py:588` 补体力后
   `_click_retry("march_btn")` 失败 → 抛错 → runner 退避重试 → `_launch` 重跑，此时
   `_find("ap_refill")` 仍命中 → 再 `_refill_ap()` → 成功发起（三次均在 ~30–45s 内恢复）。
   **成因**：`_refill_ap()` 返回 True 只代表「弹窗已关」，不代表 AP 已够；行军点击再次
   触发 AP 不足弹窗时，`_launch` 直接抛错而**不做二次补体力**。
   失败截图探针（`recordings/failure_mumu0_char_zhaizi_20261004_182335.png`）确认
   视图=弹窗遮罩、`ap_refill` 命中。→ 修法见 PROGRESS 已知问题 8。
2. **成员 `SWITCH_TO_SELF` 归一化失败 ×1**（19:28:15）：
   `归一化失败：卡在[未知]视图（联盟旗帜与放大镜均不可见）`；退避重试后恢复。
   全程 `卡在[` 的 step 失败仅此 1 条。
3. **成员第 4 轮填兵失败 ×1**：`加入未生效，重开战争列表重试` → `联盟旗帜不可见`
   连试 11 次耗尽 → `第 4 轮失败结束：no_rally_found（连续失败 1/3）`。
   该轮车头集结无人填兵但仍完成本轮；后续轮次正常，未累计到 3 连败。

### 其它观测

- 预设列自校准 + `预设槽 1 已确认` **10/10 轮**成功，**0 次**「高亮未确认」（cy=472 稳定）。
- `面板等级已是 6 级，跳过调整` 8 次（等级缓存差量生效）；其余轮走全量重同步。
- 集结已发起 / 填兵出发各 10 次；放弃本轮 0 次。
- 成员轮编号含 1 次失败（第 4 轮），故 `轮完成` 日志 19 条 = 车头 10 + 成员 9。

## 2026-10-04 修：车头 `_launch` 行动力临界（补一次不够就再补再点）

上一节实机 3 次 `行动力补充后 march_btn 点击失败，集结未发起`（均靠 runner 退避自恢复）
的根因修复。**用户裁定：只修这一项，§3.3/§3.4/§3.5 三项不再单独验收**（已从
`ACCEPTANCE.md` 删除，编号保留跳跃）。

### 根因

`_refill_ap()` 返回 True 只表示**弹窗已关**，不表示 **AP 已够**。旧 `_launch` 的顺序是
「弹窗在 → 补 → 点行军 → 又弹 → 再补 → 再点」，**只有两轮**；两轮之后仍点不出去就直接
`raise`。实机上 AP 处在临界（补的 50/100 仍不够一次集结消耗）时正好落在这条路径上，
一轮 6 分钟全靠 runner 退避把 `_launch` 重跑一遍才恢复。

### 修法

`leader_sm.py`：新增 `_AP_REFILL_MAX = 3`，把 `_launch` 里「补体力 → 点行军」改成有界循环：

- 每次迭代先看 `ap_refill`（入口残留或上轮补完仍不够）→ 补；
- `_click_retry("march_btn", attempts=3)`；
- `_wait_for("ap_refill", timeout=3.0)` 仍在 → 记 warning、进下一轮；
- 循环跑满仍复现 → `for...else` 抛
  `行动力补充 3 次后 march_btn 仍点不出去（疑似体力耗尽/道具用尽）`，放弃本轮，
  交 runner 的连续失败计数停机（不再无限补）。

### 测试

`tests/unit/workers/test_leader_sm.py` 新增：

- `test_launch_refills_ap_repeatedly_until_march_goes_out`：假弹窗「前两次行军点击复现、
  第三次才发出去」→ 断言行军点 3 次、每日领取点 2 次、`rally_launched` 正常发布。
- `test_launch_gives_up_after_ap_refill_cap`：弹窗永远复现 → 断言按上限抛错、行军点
  `_AP_REFILL_MAX` 次、补体力 `_AP_REFILL_MAX - 1` 次（第 1 轮入口无残留弹窗，跳过补充）。

辅助函数 `_ap_popup_by_march_click(handle, res, reappear_until)` 按点击序列造弹窗状态；
`_unique_march_point(sm)` 把 `march_btn` 点击坐标从默认 `(50,50)` 挪到 `(77,88)` ——
`_make_sm` 里所有 mock 的 bbox 中心都是 `(50,50)`，不挪就没法只数行军点击
（首版测试就栽在这：断言 `count((50,50)) == 3`，实际 26）。

### 待办

**实机确认未做**——要真跑到行动力耗尽才走得到这条路径。等一次自然耗尽或手动压体力。

---

## 2026-10-05 · ONNX 推理后端 + 绿色 zip 发行包

用户需求：**「打包目标是发给别人用的安装包。训练用的数据不要放进打包目录，
打包时使用 ONNX」**。三项决策（AskUserQuestion）：绿色 zip 包（非安装向导）、
ONNX CPU 推理、首启自动探测 MuMu 路径。

开工前仓库里**没有任何打包设施**：无 `.spec`、无 build 脚本，`.gitignore` 连
`dist/` 都没忽略，`docs/` 里也没写过。三件事要一起解决——体积、路径、首启。

### 1. 为什么是 ONNX：体积

`.venv` 5.4 GB，大头是 `torch 2.11.0+cu128`（ultralytics 的传递依赖），
而生产推理只跑一个 6.3 MB 的 yolov8n。把 torch 打进发行包不可接受。

关键判断：**只替换 `_model()` 返回的对象**，不动调用方。
`YoloClassAdapter.recognize`（`yolo_detect.py`）消费结果的方式是
`result.boxes` 里每个 box 的 `.conf[0]` / `.cls[0]` / `.xyxy[0]`，
`SharedYoloDetector.detect` 调 `self._model()(screenshot, device=..., verbose=False)`。
所以只要新后端满足「可调用 + `.names` 属性」这个鸭子类型契约：

- `YoloClassAdapter`、`template_registry.build_recognizers` **一行都不用改**
- `tests/unit/core/test_yolo_detect.py` 里 `shared._yolo = fake` 的注入缝**继续有效**，
  现有测试作为回归锚
- 类名与文件名保持不变（模型仍是 YOLO，换的只是执行后端），manifest 的
  `yolo_threshold` 语义不变

新增 `core/recognizers/onnx_detect.py`（letterbox / postprocess / NMS / `OnnxYoloModel`）。
预处理与后处理必须与 ultralytics **逐位一致**（conf 0.25 / iou 0.7 /
`agnostic_nms=False`），否则 `tools/calibrate_yolo_threshold.py` 标定出的阈值全部失效。

**踩到的坑**：`cv2.copyMakeBorder` 的颜色参数给标量只会填第一个通道 →
填充变成 `(114,0,0)` 蓝色而不是中性灰。由单测发现，改成接受 int 或元组并归一化。

**另一个坑**：parity 脚本首版按置信度排序后 `zip()` 配对两个后端的框，小的置信度
重排序就会拿不同对象对比，报出 661.7 px 的假偏差。改成按 IoU ≥ 0.5 的贪心匹配后：
匹配 61 个、最小 IoU 0.924、最大中心偏差 2.3 px。

**排除 ONNX 回归**：校准输出里有很多「漏检」行，写了个临时脚本逐类比较两个后端的
最大置信度 —— **`.pt` 有而 `.onnx` 完全没有的类：0**；最差回归 −0.071
（`queue_badge` 0.909→0.838），最大改进 +0.259（`city_btn` 0.000→0.259）。
结论：漏检是模型既有局限，不是 ONNX 造成的。

### 2. 路径：计划里写错的一处

原计划是 frozen 时 `os.chdir(exe目录)` 一处收口。**实测行不通**：PyInstaller 6 的
onedir 模式把 `datas` 放在 `<exe目录>/_internal/`（即 `sys._MEIPASS`），
chdir 到 exe 目录照样找不到 `templates/`。已向用户报告这处偏差。

改成 `infra/app_paths.py` 显式区分两种根目录：

- `resource_dir()` —— 只读资源，冻结时 = `_internal`，源码运行时 = 仓库根
- `user_dir()` —— 可写数据（`config.yaml` / `logs/` / `recordings/`），= exe 同级

穿透点：`main_window.main()`（`ensure_user_files()` + `setup_logging(user_dir()/"logs")`）、
`controller.py`（默认 config 路径）、`runtime.py`（`resolve_asset(template_dir)`、
`resolve_asset(yolo_model)`、`screenshot_dir=user_dir()/"recordings"`）。

**非 ASCII 路径**：Windows 上 `cv2.imread` 遇到中文/日文路径会**静默返回 None**。
用户把包解压到 `D:\游戏\rok-assistant` 时 53 张模板会集体加载失败。加
`template_registry.imread_unicode()`（`np.fromfile` + `cv2.imdecode`），
并用单测钉住「`cv2.imread` → None / `imread_unicode` → (8,8,3)」的对比。

**帧缓存 `id()` 复用**：`SharedYoloDetector` 的缓存键是 `id(frame)`。ultralytics 的
`Results` 会间接引用原图，所以原来不用自己持引用；ONNX 后端的 `Detections` 只存
numpy 框，帧一旦被回收 `id()` 就可能被复用 → 命中别的帧的缓存。加了
`self._cache_img` 强引用。（`ocr_text.py` 的 `RapidOcrEngine` 有同样的不变量。）

### 3. 首启：自动生成配置

`config.example.yaml` 原本含用户真实角色名和 MuMu 绝对路径，**不能原样发出去**。
脱敏重写：路径留空串、角色名换占位符、实例名换「实例0」。

`app_paths.ensure_user_files()`：没有 `config.yaml` 就从 `config.example.yaml` 复制，
再调 `mumu.detect_mumu_paths()` 回填空字段。**已存在则绝不改动。**

`detect_mumu_paths()`（`infra/mumu.py`）：winreg 查 `SOFTWARE\Netease\MuMuPlayer*`，
再 glob `%ProgramFiles%` / `%LOCALAPPDATA%` 下的 `Netease/MuMuPlayer*/shell|nx_main`，
以及各盘 `{C..G}:/模拟器/MuMuPlayer*/nx_main`。adb 优先用 MuMu 自带的
（版本和它的 adb server 匹配），其次 `shutil.which("adb")`。**不抛异常**——
探测失败只让用户手填，不该阻断启动。本机实测探到
`C:\模拟器\MuMuPlayer\nx_main\MuMuManager.exe`。

**回填实现改了两次**：首版走 `yaml.safe_load` → `safe_dump` 往返，实测**把
`config.example.yaml` 里的注释全抹了**。那份注释是这份配置唯一的说明书
（`target_levels` 顺序自由、`role` 三种取值、哪些字段互斥），首启就吃掉的话
新用户只能对着光秃秃的键值猜。改成**逐行正则替换**只动那两行；值用单引号包裹
（双引号 YAML 里 `\M` 不是合法转义，单引号才是字面量）。

GUI 的「⚙ 配置」页加了**「自动检测 MuMu/adb 路径」**按钮（探测失败时的手动重试），
复用同一份 `detect_mumu_paths()`。

### 4. 打包

- `packaging/launcher.py` —— 入口脚本。`main_window.py` 用相对导入
  （`from .character_card import ...`），不能直接当 PyInstaller 入口。
  顺便挂 `--selftest`。
- `rok-assistant.spec` —— onedir、`console=False`、`upx=False`
  （upx 压过的 onnxruntime DLL 有加载失败的报告）。`collect_all`
  `rapidocr_onnxruntime`（模型在 wheel 数据目录里，且 `RapidOCR` 是函数内懒
  import，静态分析抓不到）、`onnxruntime`、`pyclipper`、`shapely`。
- `tools/build_package.py` —— 前置检查 → PyInstaller → **产物断言** → 打 zip。
- `.gitignore` 加 `dist/`、`build/`、`models/*.onnx`（保留 `models/.gitkeep`）。

**瘦身 55 MB**：cv2 的两个 `opencv_videoio_ffmpeg*.dll` 我们从不读视频，
是 delay-load，删掉不影响 `import cv2`。**首版过滤没生效**——它们是 PyInstaller
自带的 `hook-cv2` 在 `Analysis` 里加的，在 spec 顶部过滤 `collect_all` 的返回值
拦不住，必须在 `Analysis` **之后**过滤 `a.binaries`。383 → 326 MB，zip 175 → 150 MB。

### 5. 验证：`--selftest`

绿色包最坑的失败模式是「开发机上好好的，解压到别人机器上缺东西」——开发机
`import cv2` 走的是 venv，掩盖打包遗漏。所以加了 `infra/selftest.py`：
`exe --selftest` 不开窗口，跑一遍**真实识别链路**（读模板 → 装 59 个识别器 →
拿一帧喂 ONNX → 跑 OCR），逐项 PASS/FAIL，写 `logs/selftest.log`。

冻结包实测 **9/9 通过**：`resource_dir` 正确解析到 `_internal`、cv2 无 ffmpeg DLL
仍能解码往返、ONNX 单帧 **30ms**（目标 < 100ms）、59 个识别器、OCR 三个模型就位、
`config.yaml` 自动生成并探到 MuMu 路径。GUI 启动存活 12s、无 `startup_crash.log`。

（`--selftest` 的 stdout 在 GBK 控制台会乱码，加 `sys.stdout.reconfigure`；
日志文件本身是 UTF-8 不受影响。）

### 6. 依赖清理

`pyproject.toml`：base 加 `onnxruntime>=1.17`；**删** `ultralytics`、`paddleocr`、
`pywin32`（全仓从未 import，Win32 走 `ctypes.windll`）；新增 `train` extra
（`ultralytics` / `onnx` / `onnxslim` / `paddleocr`）和 `build` extra（`pyinstaller>=6.16`）。

### 待办

- **干净机测试**（拷到没装 Python 的机器跑 `--selftest`）——本机不算数。
- **冻结包连真模拟器跑一轮**——`--selftest` 只证明识别链路通，不证明点击链路通。

---

## 2026-10-05（续）连接模拟器：真机验证 + 根因更正

### 1. 计划 A/B/C/D 全部落地

- **A 自动 `adb connect`**（`core/handle_source.py`）：`_ensure_connected()` 首次
  使用前连一次，`_run_checked()` 失败重连再试一次；`capture`/`click`/`swipe`
  都走它。`is_alive()` 保持纯查询。
- **B 扫描模拟器**（`infra/mumu.py:list_instances` + 配置对话框）：按 MuMu 里的
  **名字**选，不再让人猜「实例号」。打开对话框自动扫一次（`QTimer.singleShot(0, ...)`），
  结果缓存，所有模拟器页共用。
- **C 术语**：「实例」→「模拟器」；新增 `gui/labels.py` 收拢分工/兵种/状态中文映射；
  校验错误路径 `humanize_loc()` 翻中文。
- **D 文档**：新增 `docs/配置说明.md`（面向非程序员，随绿色包分发），
  `config.example.yaml` 补注释，`README-用户.txt` 同步。

### 2. 真机验证（无头，`QT_QPA_PLATFORM=offscreen`）

先 `adb kill-server` 抹掉手动连接的前提，`adb devices` 里**没有** `127.0.0.1:16384`
（只有一个无关的 `emulator-5554`），然后跑配置对话框：

```
rows: ['● 如愿 · 运行中', '○ 15634025219 · 未启动', '○ 如愿-2 · 未启动']
picked mumu_index: 0
status: ● 已连接，截图 1920x1080
preview px: (320, 180)
```

即：扫描按名字列对了、「测试连接」在**没有手动 connect** 的前提下直接成功。
另外两条：选中未启动的「如愿-2」→ 报「模拟器「如愿-2」没有启动，请先在 MuMu 里
启动它，再点「测试连接」」；手动填 `adb_address` 模式仍能连（方案 A 无回归）。

### 3. 根因更正：**是我自己的环境 bug，不是 MuMuManager 不稳**

上一轮把 `list_instances` 的失败判成「MuMuManager 偶发卡死/崩溃」，还据此加了
重试和「请稍后重试」文案。**判错了。** 真正原因是
**`QT_QPA_PLATFORM=offscreen` 被继承给子进程**：`MuMuManager.exe` 自己就是 Qt
程序，会去加载父进程指定的平台插件，插件不在它目录里就当场崩。

A/B 三连（各 3 次）：

| 父进程环境 | `info -v all` 结果 |
|---|---|
| 不设 `QT_QPA_PLATFORM` | rc=0，1259 B |
| `QT_QPA_PLATFORM=offscreen` | **rc=3221226505**（0xC0000409），0 B |
| `QT_QPA_PLATFORM=offscreen` 但剥掉再传 | rc=0，1259 B |

**修法**：`infra/mumu.py:child_env()` 剥掉所有 `QT_*`。
`MumuLocator._subprocess_run`（**「测试连接」走的就是这条**）和模块级
`_default_run` 都传它；`AdbHandleSource._subprocess_run` 同样处理。
**重试删掉了**——环境修好后没有任何真实的偶发证据，留着只会掩盖问题。

### 4. 走查又抓到两个真问题

- **自动填的显示名不跟着换选走**：先点「15634025219」再点「如愿」，结果
  `mumu_index=0`（如愿）而显示名停在「15634025219」，用户认不出自己选的是哪台。
  修法：`_autofilled_names` 按**实例 id**（不是下标，增删会移位）记住「这个名字是
  我们自动填的」，换选时只在「空着」或「还是上次自动填的那个」时才改，
  **用户自己敲的名字绝不覆盖**。`_reload_tree` 顺手清掉已删实例的记录。
- **实例 id 前缀不一致**：首启模板给 `mumu0`，界面点「＋ 添加模拟器」却生成 `inst0`。
  统一成 `mumu{n}`。

`docs/配置说明.md` 也据此更正两处事实错误：`MuMuManager.exe` 在
`nx_main\`（不是 `shell\`，老版本才在 `shell\`）；扫描是**打开配置窗口就自动跑**，
不用先点按钮。

### 5. 验证结果

- 全量回归：**647 passed**（基线 639）。
- 打包冒烟：`tools/build_package.py` 产物校验含 `配置说明.md`（326 MB / zip 150 MB）；
  `dist/rok-assistant/rok-assistant.exe --selftest` **9/9 通过**。

---

## 2026-10-05（三）启动超时：定位 + 更正我自己的超时收紧

### 症状

用户（打包后的 exe）点 Start 报：

```
启动失败：无法运行 MuMuManager（请检查安装路径）：
Command '[...MuMuManager.exe', 'info', '-v', '0']' timed out after 6.0 seconds
```

### 排查（systematic-debugging）

**逐个证伪，都留了数据：**

| 假设 | 结果 |
|---|---|
| 无控制台（windowed 进程）让子进程卡住 | ❌ 0.6s 正常 |
| `_internal` 混进 `PATH` → MuMuManager 加载到我们的 DLL | ❌ 带/不带都是 0.13s |
| 查未启动的模拟器（`-v 1`/`-v 2`）会卡 | ❌ 0.14~0.16s |
| 查不存在的编号（`-v 9`）会卡 | ❌ 0.14s，返回 `player index not found` |
| 冻结环境本身有问题 | ❌ 用 `ShellExecuteW` 模拟双击（无控制台、cwd=exe 目录）→ rc=0 0.67s |

**查出来的真差异**：冻结包跑同一条命令 **0.67~1.11s**，开发机只要
**0.12~0.23s**（n=30）——**慢 4~6 倍**（冻结进程无控制台、`_internal`
挂在 PATH 上，起子进程本身就贵）。顺带发现 PyInstaller 会把 `_MEIPASS`
放进 `PATH`，环境里还有个 `QT_PLUGIN_PATH`（`child_env()` 已剥掉）。

### 我引入的回归

上一轮我把 `MumuLocator._subprocess_run` 的超时**从 10s 收到 6s**，
理由是「实机正常 124~208ms，给到 6s 已经很宽松」——**那个数字只在开发机的
venv 里量过**，冻结包慢 4~6 倍，余量远没有我以为的宽。错误信息里的
「6.0 seconds」正好证明用户跑的是收紧后的版本。

**改回 10s**，并写进注释：**别按开发机耗时定这个值。**

### 顺带修掉的误导文案

`resolve_adb_address` 原来 `except Exception` 一把抓，把 `TimeoutExpired`
也说成「无法运行 MuMuManager（**请检查安装路径**）」——超时恰恰说明路径是
对的、程序也起来了。用户按这句话去反复改路径，方向全错。
现在超时单独 catch，文案是「超过 10 秒没有响应……稍等一会再试」，
`FileNotFoundError` 才说路径。配置对话框的 `_explain_connect_error` 同步
加了超时分支。

### 新增诊断（永久保留）

`--selftest` 加了一行 **「MuMu 连接诊断（只诊断，不判定）」**：打印
`frozen` / `cwd` / `QT_*` / `_MEIPASS` 是否混进 `PATH` / 实际耗时与返回码。
**故意用 20s 超时**——用正式的 10s 去测只会复现同一个超时，问不出新东西。
MuMu 没装/没开不算包有问题，所以这项不判定成败。

### 诚实的边界

**没能复现用户那次 >6s 的调用。** 修掉的是「我确实引入的回归」+
「确实误导人的文案」；用户那次的真实耗时是多少，要靠他跑一次新包的
`--selftest` 把诊断行发回来才知道。测试：**650 passed**；冻结包 9/9 → 10/10。

---

## 2026-10-05（四）点 Start 后黑窗一闪一闪：根因 + 统一封装

用户报两件事：**（1）点 Start 后一直有黑色弹窗一闪而过、持续很多轮；
（2）只连上一个模拟器，另一个成员实例报错。** 本记录只讲（1），（2）见文末。

### 根因：无控制台的父进程会给控制台子系统子进程新开窗口

绿色包是 PyInstaller `console=False` 的 GUI 程序，**自身没有控制台**。
而 `adb.exe` 与 `MuMuManager.exe` 都是**控制台子系统**程序（PE Subsystem=3，
用 `struct.unpack_from('<H', data, pe + 0x5C)` 读出来的）。父进程没有控制台时，
Windows 会给每个这样的子进程**分配一个新的、可见的控制台窗口**。
`adb` **每截一帧、每点一下都要起一次**，于是连成串地闪。

**A/B 验证**（从真正无控制台的父进程里跑，窗口用 `EnumWindows` +
`GetWindowThreadProcessId` + `GetClassNameW` + `IsWindowVisible` 枚举）：

```
探针自身控制台 = 0
裸 subprocess.run           → 类=['PseudoConsoleWindow']  可见窗口数=1
infra.subproc.run（修法）    → 类=[]                       可见窗口数=0
```

注意窗口类是 `PseudoConsoleWindow` 而不是 `ConsoleWindowClass`——
Win11 把控制台路由给 Windows Terminal，第一次按老类名找是找不到的。

### 修法：`infra/subproc.py`，所有 fork 外部程序的地方都走它

新增一个只有 40 行的模块，把两件**只在打包后才暴露**的事一次做对：

1. `env=child_env()` —— 剥掉所有 `QT_*`（已知问题 9 那个坑）。
   实测冻结后 PyInstaller **自己会设 `QT_PLUGIN_PATH`**，
   所以这不是防用户，是防我们自己。
2. `creationflags=CREATE_NO_WINDOW` —— 别给子进程分配控制台窗口。

改到位的调用点：`core/handle_source.py`（热路径）、`infra/mumu.py` 的
`MumuLocator._subprocess_run` 与 `_default_run`、`infra/selftest.py`。
`tests/unit/infra/test_subproc.py`（9 条）里有一条
`test_no_bare_subprocess_calls_left_in_src` 扫描 `src/`，以后谁新写调用点
忘了带标志会直接红。

**这两个标志为什么必须有单测钉住**：从终端跑源码时父进程有控制台、环境也干净，
漏掉它们怎么试都是好的；只有打包后才现形。

### `--selftest` 新增「各模拟器连接（只诊断，不判定）」

照 `config.yaml` 逐台 `create_handle_source` + 真截一帧，把每台的结果
（成功 / 异常全文 / 耗时）写进自检日志。

加它的理由正是用户报的第（2）件事：**如果失败发生在 `create_handle_source`
阶段，worker 还没起来，运行日志里一个字都没有**，事后完全查不出来。
现在绿色包自己能回答「哪一台连不上、报什么错」。

### 用户报的第（2）件事：没能复现，也没有证据

查过的东西（都是**否定**结果）：

- 用户 `logs/` 里那次运行（17:14:34–17:16:12）：**两个 worker 都起来了**
  （mumu1 → 待机 17:14:46，mumu0 → 待机 17:15:05），**没有任何 ERROR 行**。
- 17:16:07 / 17:16:09 两条 `在 2.0s 内未停止` 警告**前面没有**
  `运行时启动失败，回滚已创建的 worker`，所以那是用户**点了 Stop**，
  不是启动回滚。
- 没有 `recordings/` 目录 → runner 的 `error` 状态**从未触发过**
  （`_save_failure_screenshot` 一次都没写）。
- 用户那个 exe 的 md5 与我们的 `dist` 一致，所以他手上已经有 10s 超时修复。
- 同一台机器、同一份 `config.yaml`：源码模式两台都连得上（1.36s / 2.10s），
  **冻结后也两台都连得上**（1.24s / 2.07s，`--selftest` 11/11 通过）。

所以**要么是当时的瞬时状态**（比如那台模拟器还没起、或 MuMu 正忙），
**要么报错发生在界面上而没进日志**。问了用户要报错原文，他答「记不清了」——
**没拿到原文就不动代码**（`/systematic-debugging`：没有根因不动手）。
后面按「最可能的情况」修的是**另一个真问题**（失败说不清是哪一台），
不是这次的根因，见本节末。

### 测试与冻结验证

- `pytest tests/ -q`：**659 passed**。
- 冻结包 `--selftest`：**11/11 通过**，含新增的「各模拟器连接」一项。

### 追加：按最可能的情况修「另一个成员实例报错」

用户答「记不清了，按最可能的情况先修」，并选择**保持「一台连不上就都不跑」**
的语义不变。所以不动回滚，只修**「失败时说不清是哪一台」**这个真问题。

最可能的情形：点 Start 时某台模拟器还没起来 → `resolve_adb_address` 抛
`MumuNotRunningError` → 整个启动回滚 → 界面弹一个泛泛的「启动失败：…」。
用户配了两台，看到的却是：

```
启动失败：MuMuManager 输出中未找到 adb 端口（模拟器 1 可能没有启动）:
{'0': {'index': 0, 'name': '如愿', ... <300 字符 JSON> ...}}
```

既没说清是哪一台（「模拟器 1」是 MuMu 界面上根本不显示的编号），
又被一坨 JSON 把重点冲掉。**这段文本完全在日志之外**——worker 还没起来，
运行日志里一个字都没有（用户的 `logs/` 里那次就是 0 字节），事后无从还原。

两处改动：

1. `RuntimeCoordinator.start()`：逐实例包一层，失败时点名并保留原始原因——
   `模拟器「阑珊填1」（mumu1，MuMu 编号 1）连不上：<原始原因>`，同时
   `logger.error` 落一份。测试 `test_start_error_names_the_emulator_that_failed`。
2. `MumuNotRunningError` 的文案：**原始 JSON 只进日志，不进异常文本**，
   正文改成「模拟器 N 没有启动（MuMuManager 查不到它的 adb 端口）。
   请先在 MuMu 里启动它，再点 Start。」保留「adb 端口」这个词——
   `config_dialog._explain_connect_error` 靠它匹配。测试
   `test_not_running_message_is_actionable_and_has_no_json_dump`。

**诚实边界**：这是「按最可能的情况」修的，**不是**已确认的根因。
用户的报错原文还是没拿到（他说记不清了）。如果重装后再撞上，
`logs/selftest.log` 的「各模拟器连接」那一行 + 运行日志能定位。
测试：**661 passed**（659 + 2）；冻结包 `--selftest` 11/11。

## 2026-10-06 每实例日志区 + 人性化层

两块改动一次落地：GUI 的**每实例日志区**，以及把随机化集中起来的**人性化层**（`HumanProfile`）。

### 1. 每实例日志区（GUI）

以前所有 worker 的日志混在同一个流里，分不清哪一行属于哪台模拟器/哪个角色。
现在每个角色卡片内嵌一个 `LogPanel`（`gui/log_panel.py`，只读、环形缓冲、每行加
`HH:MM:SS` 时间戳、超出上限裁头），卡片自己收自己角色的行。

归属**靠 worker 线程名**，不靠调用点改代码：`runner.py` 把 worker 线程命名成
`worker:<instance_id>:<char_id>`，`gui/log_handler.py:char_id_from_thread_name`
只切前两段取出 `char_id`（char_id 自身含冒号也安全）。新增的 `QtLogHandler`
在 worker 线程里 `emit`，Qt 自动排队到主线程追加到对应卡片——与既有的
`status_changed` 同一模式。**解析不出归属的行**（主线程的配置加载、连不上实例等）
返回空串，落到状态栏，不会错投给某张卡片。

两个容易踩的点已经处理：

- **只输出正文**：时间戳由卡片侧 `append_message` 加，handler 侧若再加会出双时间戳。
- **退出时 `logging.shutdown` 会遍历所有 handler 读 `flushOnClose`**，而此时 PyQt 已先销毁
  C++ 对象、`getattr` 抛 `RuntimeError`，`shutdown` 只吞 `OSError/ValueError`，
  异常会让它整个中断、后续 handler 不再 flush/close。`QtLogHandler` 预置
  `flushOnClose = False`（Python 侧属性）绕过；本 handler 无需 flush。
  窗口销毁时也会摘除 handler（见 commit `3118e13`）。

### 2. 人性化层：`HumanProfile`

新增 `infra/anti_detection.py:HumanProfile`，把「像人」的随机化集中到一处，
注入 `random.Random` 后可复现（测试用）；`debug_no_jitter=True` 时**所有**方法返回确定性值——
既是调试逃生口，也是既有测试的依赖。方法表：

| 方法 | 作用 | 机制 |
|---|---|---|
| `click_delay()` | 点击前延迟 | `Beta(2,5)` 形状（偏短、带长尾）+ 突发短间隔（`burst_prob`/`burst_scale`）；`delay_shape=uniform` 回退旧均匀行为 |
| `disperse(x, y, anchor)` | 坐标散布 | 高斯 σ=`click_offset_px`，裁剪到 ±3σ；`anchor` 可按目标覆盖 σ（`anchor_sigma`） |
| `poll_interval()` | 轮询节奏 | 在 `state_delay_min/max` 上均匀采样（**恒定轮询间隔是签名级机器特征**） |
| `jitter(base)` | 固定 sleep 乘性抖动 | ±`jitter_ratio`，`0` 保持 `0` |
| `retry_attempts(base)` | 重试次数 | ±1（下限 1），每轮路径形状也带随机 |
| `member_response_delay()` | 成员号响应集结的延迟 | 在 `member_response_delay_min/max` 上均匀采样，破两号 lockstep |

接线点（均通过可选注入，不注入即旧行为）：`StateMachine.__init__(..., human=None)`、
`_pause`（无基准走 `poll_interval()`，有基准走 `jitter(base)`）、`_find_retry`（`retry_attempts`）、
`runner` 的重启冷却与自身轮询、`either_sm` 的返城检测间隔、`member_sm` 的集结响应、`runtime`/`factory` 的
`create_state_machine`/`WorkerRunner`。`JitteringHandleSource` 改吃 `HumanProfile`；
`click` 增 `anchor` 形参（只用于选 σ，不往下传，`MockHandleSource` 仍记 `(x, y)`）；
**`swipe` 原先是直通转发、零抖动**，现在端点与时长都抖。

### 3. 复活的三个死字段

10-05 查配置时发现 `state_delay_min/max` 与 `jitter_ratio` **没有任何生产调用方**——
`JitteringHandleSource` 只包了 `click` 一条路径。本次接上：

- `state_delay_*` → `poll_interval()`（状态机拍与拍之间的轮询节奏）。
- `jitter_ratio` → `jitter()`（硬编码固定等待的乘性抖动）。

`grep -rn "jitter_offset\|jitter_delay" src/` 现在只剩 `anti_detection.py` 里的两处**定义**
（供既有单测使用）；`JitteringHandleSource` 已不再引用它们，死字段残留清干净。

### 4. 为什么 `state_delay` 默认取 `0.8/1.2` 而不是 spec 原本写的 `0.6/1.6`

这是一条**兼容不变量**，不是随便挑的数：

`poll_interval()` 在 `debug_no_jitter=True` 时返回 `state_delay_min/max` 的**中点**。
取 `0.8/1.2` 时中点恰好是 **`1.0`**——正是本分支之前 `_wait_for_result` / `_find_retry`
**硬编码的默认间隔**（旧签名 `interval: float = 1.0`）。于是**所有没有注入 `HumanProfile`
的状态机 / runner 调用点，节奏与改动前逐位相同**。

若默认取 `0.6/1.6`，中点会变成 `1.1`，每个未接线的调用点节奏都会漂移——
这正是要避开的隐性回归。

注意 `config.example.yaml` 仍然发 `0.6/1.6`：**那才是用户实际跑的区间**（示例在首次启动时
被复制成 `config.yaml`）。dataclass 里的 `0.8/1.2` 只是**键缺失时的兜底**，
存在的意义就是保住上面这条不变量。

### 5. 为什么 `member_response_delay` 默认关闭（`0.0/0.0`）

同样是为了「不注入 profile 就行为不变」：默认区间是空区间，`member_response_delay()`
返回 `0.0`，成员号收到集结事件立刻响应，与改动前逐字相同。两号解耦是**显式开启**的能力
（示例配置里默认给了一个非零区间），而不是默认就改掉所有人的时序。
这样这一层整体是**加法**：谁想用谁注入，不用的人一行不用改。

### 6. 本设计治不了什么（诚实边界）

时间/坐标的随机化能打散**机械式的规整**，但有几样**代码治不了**：

- **玩法规律**：号还是按同一套顺序做同一串动作，时序抖了，行为模式没变。
- **设备 / 账号指纹**：模拟器属性、机型、IP、账号元数据都不在这层能改的范围。
- **永远跑同样的轮数**：循环还是固定次数，这种规律是策略选择，不是抖动改得了的。

把这三条写下来，是为了不让人误以为「加了人性化层就等于不会被判定成脚本」。

### 7. 回归状态

- **全量回归未跑完**：`pytest tests/ -q` 跑到约 **60%+（430+ 条）**，**0 失败 0 错误**，
  随后**被操作系统因内存不足杀掉**。**没有全绿结果**，总条数以重跑为准——
  不要拿 661 当现值（本分支已新增测试）。
- 死字段 grep 干净（见 §3）。


### 2026-10-06 车头判据改由配置驱动（填兵目标不再绑死 manifest）

**疑问（用户）**：填兵流程打开战争界面后，识别「向谁填兵」用的是模板匹配还是 OCR？配置能随时改吗？用模板是不是有问题？

**确认**：两条腿，`RecognizerChain([模板, OCR], threshold=0.0)`——模板匹配（`TM_CCOEFF_NORMED`，阈值 0.9）是主判据，OCR（RapidOCR/PP-OCR ONNX）是兜底；名字列 ROI 由 manifest 里 `fill_*` 条目的 `roi` 给出。模板优先是因为 OCR 慢且受字体影响，不该抢在主判据前面。目标行定下来后按固定几何 `x=1335, cy+111` 点该行的「+」（`member_sm` 的实测常量 `_PLUS_X` / `_NAME_TO_PLUS_DY`）。

**问题（两个，都是真的）**：

1. **换车头 = 静默失效**。`_target_rec_id` 是 `f"fill_{target['name']}"`，配置一改名字，识别的 id 就变了；但 recognizers 字典只由 `manifest.yaml` 的 `templates:` 条目装配。配置点名了 manifest 里没有的车头时，`MemberStateMachine.__init__` 只打一条 warning，随后 `_find` 命中 `self._rec.get(id) is None` 静默返回 None → `_poll_join` 60 次轮询（~5-6 分钟）全部落空 → `no_rally_found` 终态。**用户以为改了配置就生效，实际整轮空转**。OCR 兜底本来就写着「名字取自 id，账号/配置改动不再失效」，但它也挂在 manifest 条目上，等于白写。

2. **OCR 兜底被 yolo_model 二次门控**。`build_recognizers` 里 `fill_` 分支嵌在 `if shared_yolo is not None:` 内——纯模板模式（没配 `app.yolo_model`）下 `ocr_name_fallback: true` 静默失效，`fill_*` 退化成纯模板。而 `ocr_name_fallback` 的语义是独立开关，与 YOLO 无关（YOLO 本就不训角色名这类账号绑定文本）。

**修复**：

- `TemplateRegistry.build_recognizers(..., fill_names=...)`：新增 `_build_config_fill_recognizers`，给「配置点名、manifest 里没有」的车头就地生成 `OCRText(expected_text=名字)`。名字直接从配置来，账号无关。manifest 已有的条目**优先**，不动它们（仍是模板先行）。
- `_fill_name_roi()`：ROI 优先沿用 manifest 里任一 `fill_*` 条目的 roi（单一真相），一条都没有时退回实测常量 `DEFAULT_FILL_NAME_ROI = (460,240,760,660)`。**刻意不退回全屏**——全屏 OCR 会把聊天框里的同名文本也认成目标行，`_poll_join` 随后按固定几何点到一片空地上。
- `ocr_name_fallback` 与 yolo_model 解耦：`fill_` 分支移出 `if shared_yolo is not None`。原先钉住旧行为的 `test_fill_spec_ocr_only_without_model` 改写成 `test_fill_spec_gets_ocr_leg_without_yolo_model`（行为是**有意**改的）。
- 多个 `fill_` id 共用**一个** `RapidOcrEngine`：原先 `_ocr_fallback_for` 每次调用各建一个，单帧缓存挂在后端上、等于同一帧被反复推理。现在 `build_recognizers` 顶部建一次。
- `runtime.py` 从 `RootConfig` 收集所有 `fill_target_leaders` 名字传给 `fill_names`；`member_sm` 那条 warning 改成指向 `app.ocr_name_fallback`（manifest 不再是唯一补救手段，旧提示语会把人引错方向）。

**验证**：真机战争列表帧（`logs/review/02_warlist__*.png`）上，manifest 有条目的 `fill_阑珊寨子号` 模板命中 1.00；凭空加的名字 `fill_凭空冒出的车头` 走 `@ocr` 腿、帧上无此行故不命中（链路通）。新增测试：registry 5 条（配置生成 / manifest 优先 / 开关关闭 / 无 yolo 也有 OCR 腿 / 共用一个后端）、runtime 1 条（空 manifest 下也要装出 `fill_车头`）、member_sm 1 条（warning 指向 ocr_name_fallback）。

**已知限制（未修）**：OCR 兜底对含生僻标点的名字会漏。实测 `Jy丶阑珊` 在 `logs/review` 帧上被 OCR 读成 `Jy阑珊`（`丶` 丢了），子串匹配失败；该帧模板也只有 0.54（该行渲染与模板不同源）。模板腿在它自己的源帧上是 1.000，所以现网目标不受影响；但**新配一个名字里带 `丶`/`·` 的车头、又没有模板时，OCR 会认不出**。要修得让 `OCRText` 的比较忽略标点，属改匹配语义（有假阳风险），未擅自做。

## 2026-10-07 防检测加固：等级回读 + 连点节奏 + 轮数界面 + 启动预检

用户收到风控警告邮件，但**判据只笼统写「检测到异常/自动化」，没有点名任何具体行为**。
没有判据可猜，只能回到通用原则：**消除机器签名**——机器签名最典型的两种是「**固定步数**」
与「**固定间隔**」。所以这一轮凡是让动作序列更像人手的都做，凡是把动作钉成常量的都不做。
用户同时提的两项「提速」——全局压低动作延迟、缓存并复用点击坐标——**明确不做**：前者与
「不要死板」自相矛盾，后者会把人性化层的高斯散布钉成常量，反而**加回「坐标重复」签名**。

以下改动全部用假件验证，**没有一条经过真模拟器**（待实机清单见 `docs/PROGRESS.md` 待办）。

### 1. 等级设置：从「固定 12 连点盲降」改为「回读实际等级 → 点差量 → 回读校验」

改动前 `leader_sm._select_level` 的等级设置是**盲进**：缓存未命中时硬连点 12 次
`level_minus` 降到底再升上来，每一下前面还挂着 3.1–5.5s 的 `click_delay`，是一段
**约 56 秒的固定动作序列**（类注释自己写着「v1 已知限制：等级设置盲进」）。这既是固定
步数签名，也无法感知点击丢失——目标 7 点成了 4 也照走。

现在主路径读面板上的「等级：N」，据此点差量，再回读校验、丢点就补。**点击次数随当前等级
自然变化**（已是目标就一次不点）。

**为什么用固定 ROI + OCR，而不是 YOLO 腿**：整条识别链的模板 ROI 本来就是写死的
（`templates:` 每条都带 roi），游戏一旦挪面板全部要重标——YOLO 腿唯一的好处「抗布局漂移」
在本项目是**伪收益**。而读数字的配方（ROI `[100,470,1040,620]` + `^等级\s*[：:]\s*(\d+)$`）
是 `tools/fix_zhaizi_level_labels.py` 里**离线验证过**的，直接搬进 manifest 当**数据**。
新识别族落在 manifest **顶层** `text_fields:`（与 `templates:` / `pixel_stats:` 并列），
**不进 `templates:`**——它没有模板图，进去会让 `entry["file"]` KeyError，或被四个工具
（`auto_label_yolo` / `ingest_raw_imgs` 等）逐个 `cv2.imread` 后**注入垃圾框**。
正则必须**整块**匹配：面板里另有「推荐兵力：1,400,000等级4的战斗单位集结进攻」这类含
「等级」的长句，子串匹配会锚错对象——这正是那次标注污染的成因。

**与 spec §4.2 的一处有意偏离**：spec 要求给等级差量点击设一个 `_LEVEL_MAX_CLICKS` 上限，
实现里**没有**设（`leader_sm._set_level` 只点 `abs(delta)` 次）。理由是差量天然有界——
`_read_level` 把读值校验在 1..10，`_current_level` 取自配置（配置校验同样 1..10），两端点
都落在 1..10，`abs(target - current)` 最大就是 9，上限**永不可达**。多设一个上限只会让盲降
路径（`_blind_set_level` 的 12+N 次）不再与改动前逐字等价，而「最坏情况与现状逐字相同」是
本次设计的前提。故有意省略，记此备查。

### 2. 为什么 `_LEVEL_CACHE` 最终**保留**而不是删除

原设计想删掉它（既然改为回读，缓存似乎就没用了）。**那会是一个实打实的回归**：缓存只服务
「OCR 读不出」时的盲降回退路径，而现状下缓存命中时第二轮是**零点击**；删掉它，读不出的
每一轮都要 12 连点降底。这违背本设计的前提——「最坏情况与现状**逐字相同**」。

所以缓存与 `_check_result` 里清缓存那段**都保留**，`_blind_set_level` 就是改动前
`_select_level` 的主体**逐字搬成的方法**，只是每点一下的停顿改由 `JitteringHandleSource`
按 `rapid=True` 承担（点击次数与顺序逐字未变）。代价是留着一个跨轮可变状态（玩家手动改过
面板等级时缓存会偏一轮），但这个代价只落在**步数本来就固定**（12+N）的降级模式里，对反检测
没有损失。回读路径**也写缓存，但仅在回读确认成功时**——否则「第一轮回读成功、第二轮回读
失败」的混合场景下缓存仍是空的，盲降又会退回全量降底。

### 3. 连点节奏为什么必须是**独立旋钮**（`rapid_click_min/max`）

等级连点的间隔从来**不是**旧的 `_LEVEL_CLICK_PACE` 决定的，而是 `JitteringHandleSource.click`
里那个 3.1–5.5s 的 `click_delay`。而人性化层的**突发分支**算的是
`lo + (hi-lo)*U(0, burst_scale)`，在 `lo=3.1` 下只有 **3.1–3.7s——等于没有突发**，那段逻辑
在当前配置下几乎空转。复用全局下限只有两条路，两条都不对：保持 3.1s（人手调数字盘不长这样），
或压低全局下限把**每一处**点击都提速（用户明确不要）。

于是新增独立旋钮，经 `HandleSource.click(x, y, anchor=None, rapid=False)` 下传；`rapid` 只由
`JitteringHandleSource` 用来**选择延迟区间**，**不向下转发**（与既有 `anchor` 同一条约定）。
下限 0.35s 沿用原 `_LEVEL_CLICK_PACE` 的取值，但**低于** 2026-09-11 的实测安全值——那次
实测的是 **0.4s** 间隔连点 19 次零丢失，常量却取 0.35s。`_LEVEL_CLICK_PACE`
随之删除，`leader_sm` 里不再有第二处硬编码 sleep——故真机待验清单里必须确认
0.35s 不丢点击（见 `docs/PROGRESS.md` 待办）。

### 4. 轮数/失败上限进配置界面 + 跑完自动复位

`max_rounds` / `max_consecutive_failures` 早就在配置模型里，只是**没接到界面上**，只能手改
yaml。现在配置对话框加了「运行」组。自动复位是真缺口：runner 跑满轮数后置 `done` 退出主循环，
但 GUI 的按钮**永远停在「运行中」**。现在 runner 在 `stopped_reason is not None` 时发
`worker_finished`（**用户点 Stop 时它是 None，天然区分**），runtime 收齐全部 runner 后发
`all_workers_done`，controller 转成 `run_finished` 信号，界面复位按钮并把停机原因写进状态栏。
修整轮把 `worker_finished` 的订阅绑到运行生命周期上——否则上一次运行遗留的迟到事件会让
新一次运行**中途误复位**。

### 5. 启动预检：`coordination/preflight.py`

点 Start 后先逐台建句柄并**真截一帧**，失败点名抛错
（`模拟器「X」（mumu1，MuMu 编号 1）连不上（已试 3 次，耗时 …）：<最后一条异常>`），
半启动状态从根上消失。用 `capture()` 而非 `is_alive()`——后者只查 `adb devices` 的状态字段，
实机上真正会炸的是 screencap。顺带判定 `1920×1080`：竖屏/登录页会让门槛白等 900s，启动时
说清楚比静默烧 15 分钟好。预检返回建好的 handle 供 `start()` 复用（走 `mumu_index` 时要调
MuMuManager，冻结包里实测 0.67–1.11s，不该建两遍）。这段**整个落在 worker 日志之外**——
worker 还没起来，运行日志里一个字都没有，所以既点名又写日志。

### 待实机验证的未知（本设计唯一的实质性风险）

**野蛮人页同 ROI**：搜索面板会记住上次 Tab，而**野蛮人页也有等级行**。若 `tab_fortress`
那次点击失败、且野蛮人页的等级行落在同一 ROI（100,470,1040,620），回读会读出一个
**看似合法**的数字，且因为回读自洽（读了就用、不做交叉验证）而**不会被自纠机制发现**。
已记入 PROGRESS 待办：实机在城寨页与野蛮人页各截一帧，确认该 ROI 只在城寨页读出「等级：N」。

另有一条评审 Task 4 时标出的：`_verify_level` 的校验 capture 紧跟最后一次连点，而
`JitteringHandleSource.click` 是**先 sleep 再点**，连点段结束后**没有**落定延迟，
可能读到点击尚未生效的旧帧（表现为回读仍 ≠ 目标 → 多补一轮差量）。同样记入待办。

### 回归状态

`pytest tests/ -q` → **751 passed / 0 failed / 0 error**（6m08s，输出无 warning/噪声）。
防检测加固分支新增单测后总条数由 711 增至 **751**。

**顺带更正两处旧记录（原文按 append-only 惯例保留，以此条为准）**：本文件 2026-09-18
「三识别栈融合」与 2026-09-2x「补充 2/3」两节里写着「车头设等级是**盲进**
（`level_minus ×12 / level_plus ×N` 不回读）」「`src/` 里没有任何代码读它」——
自本次起**不再成立**：等级设置改走**回读**（见上文 §1），`leader_sm` 现在真读面板
上的「等级：N」，`zhaizi_level_text` 那套配方也经 `text_fields.fortress_level` 进了
运行时链路（不再是「只在工具侧」）。

### 终审后的修复（同日，2026-10-07）

全分支终审（9 个提交，opus）判 **With fixes**，无 Critical，两条 Important 已修：

1. **`_on_start` 在启动失败后仍把界面置为「运行中」**——`GuiController.start()` 把
   异常吞进 `error_occurred`（模态框）后**正常返回**，`_on_start` 便无条件把
   Start 灰掉、Stop 点亮、状态栏写「运行中」，而实际什么都没跑。这恰好是本次
   新增的**启动预检**拦下坏模拟器时走的那条路，等于把新功能收在一个撒谎的界面上。
   改为 `GuiController.start() -> bool`，`_on_start` 只在 `True` 时切运行态。
   （此缺陷在 Task 6 之后由控制者发现，终审独立复核并从 Minor 升为 Important。）
2. **`docs/PROGRESS.md` 的「实机验证过」表里混进了没实机验证的东西**——表头写着
   「核心闭环链路（实机验证过）」，其中一行被改成描述新的**回读**流程，证据格却还是
   旧盲降流程的「多轮成功」。回读段**只过了假件**。已把证据格改为
   「多轮成功（回读段待实机）」，并把阈值参考里悬空的「见下」指到本节。

另修：`snapshot()` 改迭代副本（Task 5 引入的跨线程 `runners.clear()` 与 GUI 刷新
定时器的迭代相撞会抛 `RuntimeError`）；`preflight` 补回 `raise ... from last`；
`test_start_error_names_the_emulator_that_failed` 里 `assert "b" in msg` 是空断言
（同一句含 `adb`，`"b"` 白过）；补「耗时」段与「预检通过：N 台模拟器」的断言。

**一处措辞更正（本文件早前条目亦受影响）**：多处曾写「0.35s 间隔**实测** 19 连点零
丢失」。查 `git show 13ad757:src/rok_assistant/workers/leader_sm.py`，原注释记的是
**0.4s** 实测零丢失，而常量取 **0.35s**——即**刻意低于实测安全值**。这直接抬高了
实机待验第 3 条的分量：0.35s 从未被实机证明过。

**一处 spec 偏离（有意）**：spec §4.2 规定 `_LEVEL_MAX_CLICKS` 上限，实现**未加**——
差量由构造保证 ≤9，上限不可达。推理成立，但属对绑定 spec 的有意偏离，故在此留痕。

### 回归状态（终审修复后）

`pytest tests/ -q` → **752 passed / 0 failed / 0 error**，输出无 warning/噪声。

## 2026-10-08 离线授权与发码平台（试用 30 天 / Ed25519 激活 / 防解压重置）

设计文档：`docs/superpowers/specs/2026-10-08-授权与发码平台-design.md`（绑定权威，§12 列了 6 条已知局限）。
实现计划：`docs/superpowers/plans/2026-10-08-授权与发码平台.md`（10 个任务）。
当前状态速查见 `docs/PROGRESS.md`。本节只记**决定与理由**，不重复代码。

16 个提交（`3adaeca` 之后）快进并入 `main`，35 文件 +3154 行。全套 **870 passed**。

### 1. 为什么是「三处冗余 + 到期日不落盘」而不是「加密的到期日」

需求里的硬约束是**防「重新解压刷新试用期」**。三处存储里注册表
（`HKCU\Software\RoKAssistant\License`）与 `C:\ProgramData\RoKAssistant\license.dat`
**不在解压目录内**，所以重新解压只清得掉第三处 `<user_dir>\.roklicense`——这就是全部机制。

到期日**不落盘**、每次启动从 `licenses` 里的签名激活码现算，是因为记录只有 HMAC 保护，
而 HMAC 密钥 = `SHA256(主指纹 + 固定 salt)`，主指纹的输入（主板 UUID + CPU ID）全在
用户自己机器上，理论上算得出来。**现算则要求伪造者持有私钥**，严格更强。这条是
2026-10-08 早些时候改过 spec 才定下来的（见 `e9e5a2b`）。

同理，Ed25519 **签名不可截断**（验签需要完整的 R 和 S），所以激活码是 **122 字符**，
不是最初方案里的 45 字符——那版密码学上不成立（`7cda436`）。

### 2. 本次最贵的一条经验：**PyQt6 槽内未捕获异常 = `qFatal` = 整个进程 abort**

这一条单独驱动了 **5 处**修复，都是同一种形状。凡是在 Qt 槽（按钮 `clicked`、
对话框 `exec()` 内的嵌套事件循环）里可能抛异常的调用，都必须就地兜住——
**包住调用方没用**，因为异常是在槽自己的栈上逃逸的。具体踩到的：

- `MainWindow._license_ok()`：`status()` 抛 → 点 Start 杀进程。裁定**失败即闭**（返回 False），
  不能因为「读不出状态」就放行——那等于「把 `status()` 弄抛就能白拿授权」。
- `LicenseDialog._refresh_status()` / `_on_activate()`：激活窗是授权出问题时**唯一**的自救入口，
  它自己崩掉最糟。
- `LicenseTool._on_issue()` / `_refresh_status()`：发码工具同理（台账被 Excel / OneDrive 锁住时
  Windows 抛 `PermissionError`）。
- `MainWindow._open_license_dialog()`：终审发现的 I1 路径，见 §4。

**两个容易漏的异常类型**（都不是 `ValueError`，所以 `except ValueError` 兜不住）：
`bytes.fromhex(123)` 抛 **`TypeError`**；`codec.build_payload` 在 serial > 65535 时抛 **`struct.error`**。

### 3. 本机的 Windows 坑：带 HIDDEN / SYSTEM 属性的文件无法以 `O_TRUNC` 打开

`Path.write_text` 就是 `O_TRUNC`。而 `store._FileSlot.save()` 上一轮刚给文件戴上
`HIDDEN|SYSTEM`，第二次保存就会 `PermissionError` 被 `except OSError` **静默吞掉**，
三处冗余只剩注册表一处在更新。修法：写入前 `SetFileAttributesW(path, 0x80)`
（`FILE_ATTRIBUTE_NORMAL`）摘掉属性，写完再戴回去。
**测试里直写这些文件时也要先摘**（`store._set_attrs(p, _ATTR_NORMAL)`）。

### 4. 两轮评审各自抓到的东西（值得回看根因时参考）

**逐任务评审**（10 个任务，每个都过「spec 合规 + 代码质量」两阶段）抓到的实质缺陷：

- **Task 6**：计划漏了把公钥穿进 `Guard`，导致 7 条激活测试永远不可能通过。裁定用
  **依赖注入**（`Guard.__init__(..., public_key_b64=None)`，生产默认 `None` 用内嵌公钥），
  **不用**全局 monkeypatch——spec §8.2 明确要求「测试隔离走依赖注入」，而全局改
  `verify.PUBLIC_KEY_B64` 是全局可变状态。
- **Task 7**：计划把授权闸门放在「`try:` 之前」，但配置闸门就在 `try` 前一行，闸门会落到配置之后，
  计划自带的测试永远过不了。裁定放到**最顶上**，与 `MainWindow._on_start()` 的
  「先授权后配置」同序。
- **Task 9**：`format_code` 把 122 字符按 5 分组得 **25 组、24 个连字符**（末组 2 字符），
  而计划写 `122 // 5 - 1 = 23`。这是同一个算术错误的**第二次**出现（Task 1 那次是
  `len(groups) == CODE_CHARS // GROUP_SIZE` 得 24、应为 25）。用 ceil 写法。
- **Task 9**：`used_serials` 对畸形台账行**静默跳过** → `next_serial` 的 max 回退 →
  重发已卖出的号 → 客户机以「该激活码已被使用」拒掉作者刚发的码。改成**报错**。
  连带修 `append_ledger` 的 `fresh = not path.exists()`（漏掉「文件存在但为空」→ 不写表头 →
  `DictReader` 把首行数据当表头 → serial 列丢失，正好触发上面那条）。

**最终全分支评审**（opus，0 Critical / 2 Important / 8 Minor，判 With fixes）抓到的两条 Important：

- **I1**：`store.cached_fp_main()` 只捕 `ValueError`，而 `_parse()` 只校验字段**存在**不校验**类型**；
  一条结构合法但 `fp` 是数字的记录会让 `bytes.fromhex(123)` 抛 `TypeError`，一路传到
  `_open_license_dialog`（当时无兜底）→ **点「激活」整个进程 abort**——恰好砸掉「激活窗是
  唯一自救入口」这条设计意图。修：`except (ValueError, TypeError)`，并给该槽加兜底。
- **I2**：`GuiController.start()` 的授权闸门在 `try` **之外**，违反它自己 docstring 承诺的
  「捕获到异常返回 False」。GUI 路径因 `_license_ok()` 先兜住而安全，但这段代码的**明确目的**
  正是覆盖「不经过界面的调用方」（预检脚本、将来的 CLI）。修：单独包 try。

### 5. 两处「文档说了假话」的更正（本次一并修掉）

- **「到期后 Start 置灰」**：spec §2/§8.1、`main_window.py` docstring、`PROGRESS.md` 都这么写，
  但实现是**按钮保持可点、点击弹激活窗并拦下启动**，计划自己的测试也断言
  `isEnabled() is True`。spec §2 那句本身自相矛盾（置灰就点不了）。**实现是对的，错的是文案。**
- **spec §11 的「删掉 HMAC 就能重置试用期」**：用词错了。spec §12 第 2 条**自己**已确立术语——
  「**删掉**是「没有记录」（新试用），**改坏**是「有记录但无效」（判篡改锁死）」。
  删掉 `hmac` **字段**属**结构损坏** → 按 §12 第 7 条是**已接受**的局限，不是被防住的。
  改成「改坏 HMAC」。

### 6. 密钥边界（复核方法留在下面，将来改发码端时照做）

- 私钥 `secrets/license_private.key`（已 gitignore）**只在发码端**被读；
  `src/` 里**绝不出现**私钥。内嵌公钥 `licensing/pubkey.py` 是生成物，别手改。
- 测试用的固定密钥对在 `tests/fixtures/licensing/`，与真密钥对**必须不同**。复核三件事：
  测试私钥 ≠ 真私钥；`PUBLIC_KEY_B64` == 真私钥的公开部分（真码验得过）；
  `PUBLIC_KEY_B64` ≠ 测试公钥（测试不会误用真密钥）。
- 打包保险丝：`tools/build_package.py::_verify` 里一条硬失败，扫 `app_dir.rglob("*")`，
  命中 `license_private.key` **或路径里有 `secrets` 段**（**目录也算**）即失败。
  已用真实 326MB `dist/` 实测**不误报**（`"secrets" in rel.parts` 是整段精确匹配，
  stdlib 的 `secrets.py` 不会误伤）。

### 7. 收尾时**未做**的两件事（诚实边界）

1. **打包路径未实机验证**：现有 `dist/rok-assistant` 是加授权**之前**打的包。冻结包能否真激活
   只做了静态判断（`cryptography` 是运行时依赖、`verify.py` 在入口静态可达路径上、未被 excludes 排除）。
   真验要重跑 `build_package.py`，而跑冻结包 `--selftest` 会**在本机三处真实存储上写记录**，
   所以没擅自做。
2. **完成标准里的手工闭环**：`tools/license_tool.py` 用本机机器码发一张延长 30 天的码 →
   粘进激活窗 → 状态栏应显示「已授权，剩余 60 天」。同一段代码路径已用**离屏程序化**覆盖
   （真私钥签发 → 真机器码 → 临时 store → `licensed` / `days_left=60` / label
   「已授权，剩余 60 天」），字面的人工点击未做。

### 8. 一处与本分支无关的环境异常（留痕）

`.trae/skills/superpowers` 子模块在收尾时显示 `-dirty`：其内部
`tests/claude-code/analyze-token-usage.py` 被删除。本分支没碰过 `.trae/`，来源不明，
**未处理**（按用户要求，不确定在用的东西不要清）。

### 回归状态

`pytest tests/ -q` → **870 passed / 0 failed / 0 error**（4m25s）。

## 2026-11-01 时钟回拨不再判篡改（线上反馈：激活「没有任何效果」）

**现场**（用户本机，2026-11-01）：调系统时间测试 → 调到 11-10（试用 11-08 到期）→ 状态 expired →
在 11-10 这个时间上激活 → **激活成功**（`serial=1`，`applied_at=2026-11-10 12:10`，三处存储都写了）→
把时间改回真实 11-01 → 状态**仍是 expired**，点激活没反应（同一张码报「已被使用」，换新码报
「激活成功」但状态不变）。

**根因**：`guard.status()` 里「回拨超 24h 容差 → 判篡改 → 强制 expired」。记录里的
`last_seen = applied_at = 2026-11-10`（`activate()` 写的是 `eff`），而 `last_seen` 只增不减，
于是那个未来时间被永久钉进记录：真实时间追上它之前，每次 `status()` 都判篡改。spec §12.4 承诺的
「判篡改的用户仍可正常购买激活」在「先调到未来、再调回来」这条路径上不成立（§12 也没列这条）。

**修法（选 B，用户拍板）**：删掉两条判死规则——回拨超 24h、文件 mtime 在将来（连同
`state.clock_rolled_back` / `TAMPER_TOLERANCE_SECONDS` / `Store.newest_mtime` / slot `mtime()` 一并删除）。
保留 `effective_now = max(now, last_seen)` 与「`last_seen` 只增」——到期日是绝对日期、`applied_at`
又被 `last_seen` 夹住，所以「不给好处」已经堵死唯一的获利路径，判死对防作弊没有额外贡献，只剩误伤
（主板电池没电 / 系统校时 / 拿错时间）。判篡改现在只剩一条路径：**记录结构完整但 HMAC 验不过**。
回拨时记一条 `logger.info`（只进日志）。

**为什么没选 A（保留判死 + 激活时重锚 `last_seen`）**：A 下没买码的纯试用用户一旦调错时间仍被锁到
真实时间追上锚点，只能靠买码自救——把一个手滑变成一笔支出。

**验收**：`tests/unit/infra/licensing/test_clock.py` 重写（回拨超容差 = 不罚也不给好处、文件 mtime
在将来不判篡改、新增「调到未来 → 激活 → 改回时间仍是 licensed」这条回归）；本机实测修复后
`--selftest` 报 `licensed 剩余 30 天 到期 2026-12-10`——用**已经买过的那张码**恢复，无需重输、
无需清存储。代价：调时间白损失的 9 天不还（spec §12 新增第 8 条）。

## 2026-11-01（续）重输已用过的激活码不再报「已被使用」

**现场**（同一天的第二条反馈）：「再次激活显示激活码已使用」。记录本身没问题（`serial=1`
已在本机三处存储里），源码树状态也是 `licensed`——问题是这条**提示语**把用户挡住了：
已经授权成功的人重输同一张码，看到「该激活码已被使用」，只会以为码作废。
（顺带查明：`dist/rok-assistant.exe` 是 **10-09 15:11** 打的，早于今天上午的修复，
里面还是旧的判篡改逻辑——如果是在跑这个 exe，得重新打包才会生效。）

**改法**：`verify` 的「第四步 serial 未用过」取消，`check_code` / `REASON_USED` 与
`state.used_serials` 一并删除（它们只为这一步存在）。防重放本来就不靠这一步：靠的是
`state.apply_activation` 的**幂等**——serial 已在 `licenses` 里就原样返回，加不上第二次时间。
`guard.activate` 因此改成：验签通过就并入记录，若 `licenses` 条数没变（= 幂等命中）返回
`True, "该激活码已在本机激活过，授权时间未变"`；这样提示语永远描述**真实发生了什么**，
比「serial 是否在集合里」更不容易和实际行为漂移。

**顺带修的**：`gui/license_dialog` 激活成功时把**结果状态**一并显示
（「激活成功（当前：已授权，剩余 30 天）」）。上一轮那个 bug 的教训就是「激活成功」
四个字本身会骗人——重输已用过的码、记录被判篡改时，激活都可能成功而状态仍是到期。

**没做的**：没给「不同码、同一 serial」（台账回退重发号）单独报错。那种情况下新码加不上
时间，提示是「已在本机激活过，授权时间未变」——用户照样会找作者，信号没丢；为此在
`activate` 里再写一遍去重判断（和 `apply_activation` 两处逻辑）不划算。

## 2026-10-11 活动第二阶段「劫掠者城寨」：配置/GUI/车头支路 + 数据集入库（V12 训练但**不升级权重**）

**背景**：10-10 的活动让搜索面板从 2 页签变 3 页签（多出「劫掠者」）；10-11 早 07:09 实机复查
发现**第三页签的文字已变成「劫掠者城寨」**——活动第二阶段上线的是一类**不分等级的特殊寨子**，
点进去**没有等级行**（OCR 整页只读得到描述文字 + 「搜索」按钮）。几何完全没变：右页签仍是
x 511..697 / y 323..385，与中间页签同宽同高，只是 x 平移。所以这不是「第 4 个页签」，
是同一块页签换了个目标。集结流程与普通城寨逐字相同，差别只有「切哪个页签、要不要设等级」。

**配置模型：哨兵值 `RAIDER_TARGET = 0` 塞进 `target_levels`**（`infra/config.py`）。
`[0]` 是合法配置且**只能单独出现**，与任何 1–10 级共存都在 `_check_levels` 里被拒
（`[0, 6]` 报「不能再选其他等级」，`[0, 0]` 也走这条）。**没选另加 `target_raider: bool`**：
那会造出 `target_raider: true` + `target_levels: [6]` 这种自相矛盾的组合，还得把
「`target_levels` 不能为空」这条不变量放开——哨兵值让「非法组合根本表达不出来」。
配套 `target_label(v)`（0 → 「劫掠者寨子」）供日志/校验文案/GUI 共用，`find_level_collisions`
的告警也走它，不让哨兵值原样摊给用户看。

**GUI（`CharacterEditDialog`）**：等级网格下多一行「劫掠者寨子（不分等级）」复选框，
与 1–10 级**并列但互斥**——勾它就清空并禁用等级框，勾等级就把它的勾去掉并禁用。
做成「自动清空/禁用」而不是弹窗打断，理由和 `_on_level_toggle` 超 3 个时撤销勾选一致：
状态永远合法，用户不会被拦住。表格「目标城寨等级」列改用 `target_label`，
不显示「0」。

**车头（`leader_sm._select_level`）**：`target_levels == [0]` 时切 `tab_raider` 后
**直接 return**，不读等级、不点 +/-、不回读校验（那一页没有等级行，读不到会一路退回
盲降，12 次 `level_minus` 打在空处）。`__init__` 再断言一次列表形态（别处构造出混合列表
会按「0 级」这种不存在的目标搜一路）。**识别器缺失时抛 RuntimeError 而不是静默空操作**：
`_click` 拿不到 id 是静默 no-op，点不动页签就会在面板记住的旧页签上搜——等于「配置要劫掠者、
实际搜普通城寨」，比按异常结束本轮危险得多。`fortress_level` 事件字段照旧取
`_current_level(ctx)`，劫掠者时就是 0（文档里写明）。

**模板 `tab_raider`（新）**：与 `tab_fortress` 同一套做法——只裁页签**文字**
（134×32，文字本身 123×24 @ y 344..367），灰态命中、棕态不命中，阈值 0.9。
实测灰态 1.000 / 棕态 0.724 / 旧 2 页签布局 0.723，两侧余量都够。
**模板 PNG 是 gitignored 的**（只有 `templates/manifest.yaml` 进版本库），复现方式：
`tab_fortress.png` = `dataset/images/scenes__search_panel.png` 的 `[340:372, 486:620]`；
`tab_raider.png` = `logs/_cap_raider/fortress_page_5.png` 的 `[340:372, 536:670]`。
（`tab_fortress` 的 ROI 一并改成 `[280,310,760,400]`——只含页签行，面板描述文字在 y≥432。）

**数据集入库**：`tools/ingest_raw_imgs.py` 新增 `RAIDER_BOX` 与两条先验
（`tab_raider` 正向门控 `gate_tmpl`；`raider_search_tab` 反向门控 `gate_not_tmpl`，
与 `tab_fortress` / `barb_search_tab` 对称），`SCENES["01_zhaizi_search"]` 加两个类。
10-11 那批 12 帧里**只入 7 帧**：`cap_0/cap_1` 根本不是搜索面板（两个页签模板都 ≤0.39、
OCR 只读到一个「20」），`cap_2` + `fortress_page_*` 与 `raider_page_*` 组内两两
`mean|Δ|≈0.2`（只差动画像素）——每组挑 3 帧 + `cap_2` 就够，剩下的是纯重复。
入库结果：train 718 → **725**，val 69 不变；7 帧共 40 框，与逐帧手算的
4×(7 框) + 3×(4 框) 完全一致（城寨页那 4 帧有等级行所以多 3 个框）。
`dataset.yaml` 加 `64: tab_raider` / `65: raider_search_tab`（66 类），
`tools/class_names_zh.py` 补中文名，`test_pixel_stat_anchor` 的模板条目数 54 → 55。

**V12 训练了，但 `models/detect.onnx` 仍指向 V11 的导出产物**（已按 MD5 核对还原）。
`.venv/Scripts/python.exe -X utf8 tools/train_yolo.py --name gpu_1080_v12 --epochs 30
--batch 8 --imgsz 640 --workers 4` → mAP50 0.7943 / mAP50-95 0.6776（V11 是 0.7250/0.6037）。
**这个涨幅不能信**：val 只有 69 帧，涨的是 `warning_panel` 0.000→0.995、
`char_mgmt_btn` 0.000→0.995 这类**只有 1 个 val 实例**的类在抛硬币，同期
`settings_title` 0.995→0.000、`queue_march_icon` 0.995→0.497 也在反向抛。
按仓库规矩（「val 太小别拿单类 AP 下结论」）重新用 `tools/compare_runs.py` 把两个权重
放到**同一套** val 上复算，结论一致：两边都是单实例噪声，没有可归因的改善。

**不升级的真正理由**（换权重后照例重跑了 `tools/calibrate_yolo_threshold.py`，两份定标表在
`logs/_calib_v11.txt` / `_calib_v12.txt`）：V12 把 **`queue_march_icon` 的 YOLO 腿打死了**——
val 上正样本最低 0.881 → **0.278**、假阳地板 0.444 → 0.528（「无间隙，阈值救不了」）。
不放心单帧结论，又把 train+val 里**全部 21 帧带该类 GT 的帧**跑了一遍两个权重：
V11 中位 conf 0.768、4/21 帧过 0.85 阈值；V12 中位 **0.468**、**0/21** 过阈值
（`_probe_march.py`）。这是队列闸门（计划 A）最脆弱的一环，而 V12 换来的东西是
**模板腿本来就有的**：新类 `tab_raider` / `raider_search_tab` 在留出帧上 YOLO conf 只有
0.35/0.34（默认阈值 0.5 够不着，照旧由模板腿决定），`tab_fortress` 也没变好。
「为功能切不为指标」——V12 一个功能都不多给，却实打实退了一环，所以**不切**，
`runs/gpu_1080_v12/` 与它的 ONNX 留在盘上，等劫掠者那类帧攒够（新类有了真数据、
queue_march_icon 也许一起回来）再评。

**端到端验证**（现役权重就是 V11，链里没有 tab_raider 这个类，正好验证「模型不升级
不影响该支路」）：用生产识别器链（`TemplateRegistry.build_recognizers` + 现役
`models/detect.onnx`，脚本 `_probe_tabchain.py`）在实机帧上判两个页签——劫掠者页 `tab_fortress` 命中 0.985 @(404,356)
且 `tab_raider` 不命中（0.724）；城寨页反过来，`tab_raider` 1.000 @(603,356)、
`tab_fortress` 不命中（0.723）。互斥成立、余量大，`_click` 的「已在目标页 → 空操作」语义
由此得到。单测：`test_leader_sm.py` 新增 5 条（切页签且零等级点击 / 跳过等级日志 /
识别器缺失抛错 / 混合列表构造即拒 / 普通等级下 `_raider is False`），
`test_config_dialog.py` 新增 3 条（互斥、反向让位、取消勾选回到「至少选一个」），
`test_config_models.py` 新增 4 条。

**未做**：真机上还没跑过劫掠者支路（要活动期内真发一次集结）；劫掠者页「搜不到」时的
提示文案是否与 `toast_no_fortress` 模板一致也没验（那一页没有等级行，其余 UI 复用，
推测一致，等实机）。

## 2026-10-11 14:24 劫掠者城寨：12 点活动更新后的复采复核（结论：**无变化**）

定时任务（一次性 cron `caf4adac`，`7 12 11 10 *`）要求 12 点后复采一批实机帧，
确认页签 UI 有没有二次变化。实际执行时已 14:24，且模拟器里的游戏在这 5 小时里
**断线了**（弹「网络不稳定，连接已断开。」）——画面停在断线弹框上。

1. 用生产识别器 `net_error_confirm` 定位「确定」（conf 1.000 @(960,711)）点掉，
   重连后游戏停在「城内」视图（`map_btn` 1.000、`search_icon` 只有 0.765）。
2. `_probe_nav.py` 复刻车头的 NORMALIZE + SEARCH_FORTRESS 两步导航回搜索面板：
   点 `map_btn` → `search_icon` 0.765→0.913 → 点 `search_icon` → 面板开，
   `search_back` 1.000 / `search_btn` 0.999 / `tab_fortress` 0.985 / `tab_raider` 1.000。
3. `_probe_noon.py` 按「当前页 → 点 tab_fortress 中心 (404,354) → 城寨页 →
   点 tab_raider 中心 (604,354) → 劫掠者页」各截 6 帧，只打印数值判据。

复核结果（对照 07:09 基准，帧存 `logs/_cap_raider/noon_{a,f,r}_*.png`）：

| 判据 | 07:09 基准 | 14:2x 复采 |
|---|---|---|
| 页签行 y300..410 右页签外框 | x511..697 | x511..696 |
| 城寨页 `tab_fortress` / `tab_raider` | 0.723（棕）/ 1.000 @603（灰） | 同 |
| 劫掠者页 `tab_fortress` / `tab_raider` | 0.985 @404（灰）/ 0.723（棕） | 同 |
| 劫掠者页正文起始 y | ≈484 | 485 |
| 劫掠者页「等级：N」行 | 无 | 无 |

顺带确认了两件 07:09 没记的事：城寨页的等级行在 **(150,518)-(251,542)**（x<280，
所以窄的 `BODY_ROI` 框不到它，不是「等级行消失」）；面板打开时默认停在**野蛮人**
页签上（两个城寨页签都是灰态 = 同时命中），这也解释了 `_select_level` 为什么必须
无条件先点一次 `tab_fortress`。

按定时任务约定：界面一致 → 不改代码、不重训、不 ingest。新增 `_probe_nav.py`
（断线后导航回搜索面板）/ `_probe_noon.py`（页签复采判据），旧的
`_probe_reconnect.py` / `_probe_wait.py` / `_probe_where.py` 用完即删。

## 2026-10-11 劫掠者城寨搜完不弹详情面板（用户缺陷反馈 1）——实机复现 + 修复

**现象**（用户实机验证时反馈）：集结劫掠者城寨时，搜索完相机调转过去，红色集结按钮
**不自动出现**，必须手动点一下屏幕正中心才弹出来 → 自动流程点不到集结。

**根因（实机复现，不是推测）**。普通城寨点「搜索」后：面板收起 + 相机跳到目标 +
**详情面板自动展开**，`red_rally` 就在那儿——`_check_result` 只等 `red_rally`，
这条假设在城寨页成立。劫掠者城寨只做到「面板收起 + 相机跳过去」，**详情得再点一下
目标本身**（相机跳完后它就在屏幕正中）才展开。所以 `_wait_for("red_rally", 8.0)`
每次都超时 → 每次搜索都被记成 `no_result` → 5 次烧完 → `_give_up`
（`fail_reason=no_fortress_found`）。这就是「无法自动点集结」。

复现脚本 `_probe_raider_search.py`（`logs/_cap_raider/rs_*.png`）：

| 时刻 | `red_rally` |
|---|---|
| 点「搜索」后 0～20s（每 2s 采一帧，共 10 帧） | **一次都没出现** |
| 点屏幕正中心 (960,540) 后 2s | **conf 1.000 命中** |

计时脚本 `_probe_raider_cycle.py`：面板收起于点搜索后 **0.75s**（= 搜到了、相机到位；
无结果时面板留在原地）；点正中心后 **0.72s** 内 `red_rally` 命中。点完那一帧的右栏
OCR 确认弹出来的**就是劫掠者城寨的详情**（标题「劫掠者城寨」@(1318,317)、
「推荐兵力：1,600,000等级5的战斗单位集结进攻」、集结按钮 (1356,717)-(1447,768)
= `red_rally` @(1400,742)）。

**修复**（`leader_sm._open_raider_detail`，只挂 `self._raider` 支路）：

1. 等 `search_btn` 消失（**面板收起 = 搜到了**的判据，实测 0.75s）。按**轮数**上界
   （`_RAIDER_PAN_ATTEMPTS = 8`）而不是墙钟——`leader_sm.time` 在单测里是不推进的
   替身，墙钟循环会变成忙等；`_read_level`/`_verify_level` 同样是计数上界。
2. 面板**没**收起（无结果 toast / 慢加载）就一下都不点直接返回：那时正中心那一下会
   打在还盖着的面板上，把「没搜到」的判断搅浑。交给既有的 `no_result` 计数。
3. 面板收起后 `_human.jitter(1.5s)` 等相机跳完，再点 `_EMPTY_GROUND`。

**为什么只能挂劫掠者支路**：这一步的坐标与 `_EMPTY_GROUND` 是同一个点，语义**相反**
（那里是「点空地关面板」）。普通城寨这时详情面板已经开着，点下去等于把要等的面板关掉。

**风控**：点击走 `self._handle`（生产是 `JitteringHandleSource`），所以随机延迟
（`click_delay`，Beta(2,5) 形状、0.1–0.5s）与高斯坐标散布照常生效。用户要求「偏移范围
小一些」，故新增 `anchor_sigma.map_center = 4`（默认 σ=8，裁剪 ±3σ → 最大 ±12px）——
目标是地图正中的城寨图标，偏移大了会点到旁边空地。实机两轮落点 (966,540) / (959,528)，
都命中。

**单测**（`test_leader_sm.py` 新增 3 条，先红后绿）：
`test_raider_search_taps_center_when_panel_closes`（面板收起 → 点正中心，且
`search_outcome == "found"`）、`test_raider_search_does_not_tap_when_panel_stays_open`
（面板留着 → 一次都不点、记 `no_result`）、`test_normal_level_search_does_not_tap_center`
（普通等级**不许**点，否则关掉刚弹出的详情）。`test_leader_sm.py` 57 passed；
workers + infra + integration 子集 385 passed。

**实机验证**：`_probe_raider_fix.py` 直接调**生产** `_open_raider_detail()`（真 handle +
真识别器链），两轮都返回后 0.5s 内 `red_rally` conf 1.000 @(1400,742)。**只验到详情面板
出现为止，没点 red_rally**，所以没发车——完整一轮（红集结 → 蓝集结 → 预设 → 行军）
仍待实机。

**未做**：劫掠者页「搜不到」时的提示文案是否与 `toast_no_fortress` 一致（那一页没有
等级行，其余 UI 复用，推测一致）仍未验；`_recover_locked` 的「点空地关详情」在劫掠者
支路上是否同样成立（同一个坐标，语义相反但那时详情确实开着，方向应该对）也没单独验。

---

## 2026-10-11 「解压出来的文件夹运行过一次就删不掉」（用户缺陷反馈 2）——根因 + 修复

**用户报**：「打包解压开的文件夹，一旦运行一次后，退出了程序再删除这个文件夹都
删不掉。是有什么隐藏的后台运行程序吗」

**结论：有，是 adb 守护进程，不是我们的进程。**

### 根因

绿色包是解压即用、双击 exe 启动的，所以 **app 进程自己的 CWD 就是解压目录**。
`infra/subproc.py:run()` 从不设 `cwd`，子进程默认继承父进程的 CWD。而 adb 客户端
在本地没有 adb server 时会 fork 出一个**常驻**的
`adb -L tcp:5037 fork-server server` 守护进程——它连客户端的工作目录句柄一起继承
下去（PEB 里 `RTL_USER_PROCESS_PARAMETERS.CurrentDirectory` 是 `{DosPath, Handle}`
两半，句柄那一半是可继承的）。**Windows 不允许删除任何活进程还开着的目录**，于是
app 退出之后文件夹照样删不掉，报「另一个程序正在使用此文件，进程无法访问」。
任务管理器里找不到 `rok-assistant.exe`，所以看着像「隐藏的后台程序」。

触发条件：**adb server 之前没在跑**（MuMu 没起、或被 kill 过）时，app 的第一次
`adb connect` 就会 fork 出这个守护进程。MuMu 自己已经起过 adb server 的话不会。

### 排查过程（先排除，再定机制）

1. **扫全机进程的 CWD**（读 PEB，PowerShell + `NtQueryInformationProcess`）：
   没有任何进程的工作目录指向用户目录；`adb.exe` 有，但它的 CWD 是 `C:\Windows\`。
   ——**这一步一开始把我带偏了**：看 CWD 字符串会以为不是它，实际上钉住目录的是
   那个**继承来的目录句柄**，不是 CWD 路径本身。
2. **打包后的 app 自己会不会残留**（负对照）：把 `dist/rok-assistant` 整包复制成
   「解压目录」，按双击的方式（CWD = exe 目录）跑
   `rok-assistant.exe --selftest` → **10s 退出、rc=0、13/13 通过、零残留进程**，
   之后那个目录**当场可删**。⇒ app 自己退出干净，钉住目录的不是它。
3. **机制 A/B**（`_probe_cwdfix.py`）：忠实还原「app 的 CWD = 解压目录、起一次 adb、
   然后退出」，只改子进程的 CWD 从哪儿来——
   - A 继承 app 的 CWD → `删解压目录 → 失败：PermissionError: 另一个程序正在使用
     此文件，进程无法访问`；`adb -P 5039 kill-server` 之后**立刻可删**。
   - B 走 `subproc.run`（子进程 CWD = 系统临时目录）→ **当场可删**。
   两轮都用 5039 端口另起一套 adb，不碰在用的 5037。

### 修法

`infra/subproc.run` 加 `kwargs.setdefault("cwd", neutral_cwd())`，`neutral_cwd()`
返回系统临时目录（`tempfile.gettempdir()`，取不到就返回 `None` = 退回继承，不能因为
这一步失败把 adb 起不来）。

**为什么指临时目录**：那儿本来就是「用完就扔」的，钉住它没有副作用。实测守护进程钉着
`C:\Users\…\Temp` 时，Temp 里的**文件和子目录照常增删**（句柄钉的是 Temp 自己，不是
里面的东西）。**不能指 app 目录，子目录也不行**——子目录被钉住，父目录一样删不掉。

**改在 `subproc.run` 这一层而不是只改 adb**：这一层本来就是「所有 fork 外部程序的
地方都该走这里」的收口，而「别继承 app 的 CWD」对任何子进程都成立（将来再有 fork
守护进程的子进程也一并修掉）。改动前先实测了中性 CWD 下 `MuMuManager.exe info -v all`
（rc=0 / JSON 正常 / 0.13s）与 `adb devices` 都照常——MuMuManager 是 Qt 程序、在这条
路径上出过事（见同文件 docstring 第 1 条），所以不敢想当然。

### 验证

- `_probe_cwdfix.py`：A 被钉住 = True，B 被钉住 = False，退出码 0。
- `test_subproc.py` 新增 3 条（先红后绿）：`test_run_does_not_inherit_the_app_cwd`、
  `test_neutral_cwd_is_not_the_app_dir_or_below_it`（子目录也不行）、
  `test_real_child_really_lands_in_the_neutral_cwd`——最后这条**真起一个进程问它的
  `os.getcwd()`**：spy 只能证明我们**传了** `cwd`，证明不了 `CreateProcess` 照做了。
  `test_subproc.py` 12 passed；infra + `test_adb_handle_source.py` 252 passed。
- 真机走一遍改动后的 adb 热路径（`create_handle_source` → `capture`）：
  `shape=(1080,1920,3) mean=131.7`、`is_alive=True`。

**已经踩上的用户**（旧包）：任务管理器结束 `adb.exe`（或 `adb kill-server`）后即可
删除，不用重启；MuMu 会自己再把 adb 拉起来。

## 2026-10-11 首启默认配置改为「两台模拟器、每台一个角色」（用户优化建议）

**背景**：原来 `config.example.yaml` 只给一台模拟器 `mumu0`，里面塞了
`char_leader`（车头角色名）和 `char_member`（成员角色名）两个角色。用户要求
首启生成两份更贴近实际用法的默认：**两台模拟器，一台车头、一台填兵，每台只
一个角色**，角色名分别是「集结手」「填兵号」。

**改法**：`config.example.yaml` 的 `instances:` 重写为两条——
- `mumu0` / name `模拟器0` / `mumu_index: 0` / 角色「集结手」`role: leader`；
- `mumu1` / name `模拟器1` / `mumu_index: 1` / 角色「填兵号」`role: member`，
  `fill_target_leaders: [{instance: mumu0, name: "集结手"}]`。

跨实例填兵本来就是合法且已支持的路径（`RootConfig._cross_checks` 按
`(instance, name)` 查表），所以 `mumu1` 填 `mumu0` 的车头不需要任何代码改动。
首启拷贝逻辑 `app_paths.ensure_user_files()` 只认 `config.example.yaml`，无需改。

**同步的文档**：`docs/配置说明.md`（第 2 步的「第一次用就只有一台」+ `instances`
一节）、`docs/ACCEPTANCE.md` §2 要点列表。

**验证**：`.venv/Scripts/python.exe` 载入改后的 example →
`mumu0 车头 | 集结手 leader [7,6,5]` / `mumu1 填兵 | 填兵号 member [7] →
(mumu0, 集结手)`，`RootConfig` 校验通过。未改任何代码，无需跑测试子集。

## 2026-10-12 打包时可指定试用天数（默认 30）

**背景**：试用期天数原本写死在 `state.TRIAL_DAYS = 30`（spec §5.5 要求它是代码常量、
不进 `config.yaml`——配置是用户能直接改的文本文件）。需要能**在打包时**指定，
本次要打一个 2 天试用的包。

**改法**（保持「用户改不到」这条约束不变）：

- `state.py`：常量改为 `try: from ._trial_override import TRIAL_DAYS / except
  ImportError: TRIAL_DAYS = 30`。只吞 `ImportError`——生成物存在但坏了要照常抛，
  静默退回 30 会把试用期变**长**（反向失效）。
- `tools/build_package.py`：加 `--trial-days N`（默认 30，范围 1..3650）。构建时
  在 PyInstaller **之前**写 `src/rok_assistant/infra/licensing/_trial_override.py`，
  `finally` 里删掉（成败都删）。发现该文件**已存在**（上次残留）→ 构建直接失败，
  不用错值构建。`main()` 顺带接受 `argv` 便于单测。
- `rok-assistant.spec`：该模块只在构建时短暂存在，按文件存在与否补一条
  `hiddenimports`，确保 PyInstaller 收进去。
- `.gitignore`：忽略该生成物。

**为什么不用 `_internal/trial_days.txt` 这类资源文件**：那又是一个用户可编辑的
文本文件，等于把 §5.5 堵掉的口子从 `config.yaml` 挪个地方。编进 `.pyc` 的模块
与「公钥写死在 `pubkey.py`」同一档防护。

**验证**：`tests/unit/test_build_package_trial_days.py`（新增，写/删往返、残留拒绝、
`--trial-days` 越界拒绝、`--skip-build` 不写生成物）+ 既有 licensing 全套 + 既有
`test_trial_lasts_30_days`（覆盖「无覆盖文件 → 30」）→ 96 passed。

## 2026-10-12 实机缺陷：体力弹窗收不掉 + 寨子被占后卡死（/systematic-debugging）

**用户报的两条**：
1. 「体力不足后能自主加体力，但会卡在体力界面不再有后续动作 → 一直重试 → 最后失败退出程序」；
   追问确认症状是「弹窗压根关不掉，程序还在反复点」。
2. 「搜到的寨子被其他玩家集结后不弹蓝色集结框 → 一直卡在这座寨子上，直到它消失才重新发起」；
   要求「弹不出蓝色框就退回寨子搜索页搜下一座」。追问确认游戏会**自动跳到另一座没被集结的**寨子。

### Phase 1 根因（读日志 + 实机帧，全部有证据）

* **RC1/RC2（弹窗关没关没有独立证据）**：`_refill_ap()` 的返回值只是
  `_close_ap_dialog()` 的结果，而后者**点一次 X 就当弹窗没了**。`ap_refill` 的
  ROI 只有标题那条窄带（`[800,90,1300,170]`），模板一次失配调用方就以为关了，
  于是再也不点 X，转头去怪 `march_btn`。`_normalize_view` 里那次补体力**一行日志
  都没有**——实机复盘时看不见补了几口、弹窗到底关没关。
* **RC3/RC4（异常被同状态重放，最后停机）**：`WorkerRunner` 在 step 异常时
  **不重建 SM**（只有走到终态 + 冷却后才 `self.sm = self._sm_factory()`），
  异常只在**同一个状态**退避重试，`_max_error_streak = max_consecutive_failures*2 = 6`
  次后停机。于是「补 8 轮体力 → 异常 → 退避 → 再补 8 轮」循环，每次都把体力再补
  一遍，直到报「连续 6 次 step 异常…停止」。**日志实证**：
  `logs/rok_assistant_20260918_052316.log` 05:26:10→05:27:17 六次 march_btn/AP 异常
  → 停机，与用户 bug 1 逐字吻合；`logs/rok_assistant_20261004_094816.log`
  09:57:13→09:59:10 六次「归一化失败：卡在[未知]视图」→ 停机。
* **RC5（丢失点击结果 + 归因过窄）**：`_click_red_rally` 丢掉 `_click_retry` 的
  返回值；`_verify_unlocked` 把「10s 内没等到蓝色集结框」**一律**判成「被别人
  集结」——「按钮没点到」「有模态压着」「就是没弹出来」三种都被记成同一句。
* **RC6（恢复动作没有任何验证）**：`_recover_locked` 只点一下空地就走，不确认
  上一座寨子的详情**真的收掉了**、重搜出来的是**新目标**。而 `red_rally`
  (roi `[1200,660,1600,820]`) 与 `search_icon` (roi `[0,700,240,940]`) **不重叠**，
  `_normalize_view` 见到放大镜就直接返回——**NORMALIZE 永远不会替我们收详情面板**。
  这就是「一直卡在这座寨子上」的机制。

### 排除掉的（别再走一遍）

* **弹窗 X 坐标不是错的**：把 `(1638,120)` 画在失败帧上，十字正落在弹窗白色 X
  字形上（中心 ≈ (1645,124)）。
* **「体力不够」不是唯一解释**：失败帧里 AP 122/150、道具行可用（2,020 / 7,840 /
  261…）、「使用」按钮是亮态。为什么游戏仍拒绝，**未证**（见下）。
* **盘上的日志与帧全部早于 commit `fa4ccce`**，是比当前 HEAD 更旧的代码产出的，
  所以现役代码的确切文案在任何日志里都搜不到。

### Phase 4 改法（都是「把卡死改成本轮干净中止 + 补上验证」）

* `_close_ap_dialog()`：**连续两次** `_find` 都是 None 才判「已关闭」（一次失配
  不算），最多点 4 次 X，仍关不掉打明确 warning。返回值现在**真的**是「弹窗关没关」。
* `_refill_ap()`：记 `eaten`（吃了几口），结尾 `logger.info("补行动力：点第 1 行
  「领取/使用」1 次 + 第 2 行「使用」N 次（上限 3），弹窗已关闭/仍在场")`。
* 新增 `StateMachine._wait_for_gone()`（`_wait_for` 的对偶）。
* `_normalize_view` 的 AP 分支：补完仍关不掉 → 写 `fail_reason=ap_dialog_stuck`
  并干净返回（**不再假装关掉了继续往下走**）；新增 `NORMALIZE→END` 边（注册在
  `NORMALIZE→SEARCH_FORTRESS` **之前**，按注册顺序取第一条 guard 通过的转移）。
* `_launch`：两处 AP `raise RuntimeError` 改为干净放弃（`fail_reason=no_action_points`
  + LAUNCH→END 边）。重建 SM 后会重新走 NORMALIZE，由它收弹窗。
* `_click_red_rally`：保留点击结果到 `ctx["red_rally_clicked"]`，没落地打 warning
  （**这不等于城寨被占**）。`_verify_unlocked` 据它把原因分成 `click_missed` /
  其余；其余再走新的 `_diagnose_missing_popup()`，把原因细分为
  `detail_still_open` / `modal_<模板名>` / `no_popup`，日志与 `lock_cause` 都带原因。
* 新增 `_dismiss_detail()`：点空地 → `_wait_for_gone("red_rally")` **确认**收掉，
  两次不行再退到搜索页的返回键（`search_back`）再确认；都收不掉返回 False。
  收不掉 → `fail_reason=stale_fortress_target` + 新增 `VERIFY_UNLOCKED→END` 边
  （屏幕上那块 red_rally 是**上一座寨子的残留**，重搜也证明不了新目标，
  **绝不**再点它一次）。收掉了 → 走既有的 `VERIFY_UNLOCKED→NORMALIZE→SEARCH_FORTRESS`，
  即用户要的「退回搜索页搜下一座」。
* 新增 `_abort_round()`（不 raise 的干净中止，写 `failed` / `last_rally_event=None`）；
  `_recover_locked` 变成纯日志（收详情已在 `_verify_unlocked` 里做完并确认过）。
* `runner.py`：新增 `_ENV_FAIL_REASONS = {no_action_points, ap_dialog_stuck,
  stale_fortress_target}`——这些原因**下一轮会自愈**（重建 SM 后 NORMALIZE 再收一次
  弹窗、寨子随时间消失），所以**不计入连续失败**（否则一次弹窗卡顿 = 连续 3 轮失败
  = 收工，正是用户报的「最后失败退出程序」）。`no_action_points` 冷却用
  `_NO_AP_COOLDOWN = 300s`（体力要靠自然恢复），其余用正常冷却。

### 测试

`tests/unit/workers/test_leader_sm.py` 新增 11 条（都先红后绿），
`tests/unit/workers/test_runner.py` 新增 2 条：
`test_runner_keeps_running_after_ui_stuck_aborts`（连续 4 轮 UI 类中止也不收工）、
`test_runner_waits_long_when_out_of_action_points`（体力不足走 300s 长冷却且不计失败）。
其中 `test_stale_target_ends_round_instead_of_reclicking_the_same_fortress` 断言
`sm.history.count("CLICK_RED_RALLY") == 1`——钉住「不再反复点同一座寨子」。
另加一条**跨模块哨兵** `test_env_fail_reasons_cover_every_leader_abort_reason`：
runner 的 `_ENV_FAIL_REASONS` 与 leader_sm 的三个原因常量靠字符串字面量对齐，
任一侧改名都不会有编译期错误、只会安静地退回「计入连续失败」——
这条测试断言 leader_sm 的三个常量**都在**豁免名单里。
全量：`pytest tests/ -q` → **947 passed / 0 failed**（946 那次 5m00s，哨兵另跑）。

### 仍未解释的（留给下次实机取证）

* **为什么 AP 122/150、道具可用，游戏仍拒绝行军**。三种待验假设：点「使用」后有
  确认步骤；待发车的行军一直失败导致弹窗反复重现；**截图是冻结的**——09-18 那四张
  卡死帧在 67s 内**逐像素完全相同**（连 AP 条都是），而 09-48 的帧是真的在变。
* **09-48 的卡死是另一种未识别的游戏模式**（红色虚线行军线、城墙/旗帜结构、
  11公里、绿色上箭头、「多选」「快捷战斗」）：放大镜可见但 `search_icon` 不匹配，
  于是 NORMALIZE 永远抛「未知视图」。**本次未修**，是独立缺陷。
* 下次实机看新日志即可分辨：`补行动力：… 弹窗仍在场`、`蓝色集结框未出现（第 N/5 次，
  原因=…）`、`城寨详情弹窗收不掉（red_rally 仍在场）`。

### 2026-10-13 GUI 企业级界面重构（令牌层 + 四段式主窗口）

**由来**：界面已从「作者自用脚本」长成**随绿色包分发给非程序员**的工具（`docs/配置说明.md`
就是写给他们的），但视觉层从没立过规范——全仓库 `setStyleSheet` 只有 5 处且都是临时补丁：
`character_card.py` 的 `background:#500`、`main_window.py` 的 `color:#27ae60` / `#c0392b`、
`config_dialog.py` 的裸 `red`。同一件「错误」在三个文件里是三种红。用户要求按企业级 B 端
规范（对标 Ant Design 5 / 华为云控制台）重构。**两项决策由用户当场选定**：完整重构（含布局
结构）；文案统一中文。

**根因**：不是「配色不好看」，是**没有单一出处**。5 处散落的 `setStyleSheet` 各自跑偏，
因为每处都是「当场挑个颜色」。所以第一刀不是改颜色，是立令牌。

**新增**
- `gui/theme.py`——间距 4/8/12/16/24/32、圆角 2/4/6/8、字号 12/14/16/20、中性灰阶、
  品牌与功能色、状态标签五语义（`TAG_BG/TAG_FG/TAG_DOT` + `tag_style()` / `dot_style()`）、
  全局 `QSS`（`string.Template` + `$TOKEN`）、`apply_theme()`。
  色值落成**实色十六进制**而非令牌原文的 `rgba(0,0,0,0.88)`——Qt QSS 对 rgba 浮点 alpha
  的解析各版本不一致，实色是白底上的等价值、行为确定。
- `gui/flow_layout.py`——Qt 官方 `FlowLayout`（含 `hasHeightForWidth`）+ `clear_layout()`
  （**先 `hide()` 再 `setParent(None)`**：直接脱父会把可见控件变成独立顶层窗口，在事件循环
  处理 `deleteLater` 之前闪一下）。
- `tests/unit/gui/test_theme.py`（28 条）、
  `docs/superpowers/specs/2026-10-13-企业级界面重构-design.md`。

**改**
- `main_window.py`——四段式 `appHeader / appToolbar / content / QStatusBar`；卡片区由
  `QVBoxLayout` 纵向堆叠（2 实例×2 角色 = 1720px 长条、宽屏大片留白）改 `FlowLayout` 自适应
  网格；`QStackedWidget` 在「卡片网格 / `_EmptyState`」间切（空态**不放插画**，居中文案说清
  下一步）；`license_label` 由裸彩色文字改标准状态标签；顶栏文案统一中文。
- `character_card.py`——卡片 220×430 → **300×440**、白底 + 1px 弱描边 + 8px 圆角；状态标签
  的**圆点与文字分属两个控件**（圆点不拼进 `status_label.text()`，多条测试按精确串断言）；
  缩略图底色 `#222` → `#FAFAFA`（深灰在浅色界面里像个洞）；错误态由整块 `#500` 暗红填充改
  **1px 红描边 + 红色标签**。
- `config_dialog.py`——各页包进 `QScrollArea`（原 880×620 装不下全局页，小屏/高 DPI 下底部
  控件被裁掉够不着）；底部独立按钮栏（分割线 + 右对齐「取消」/ 主按钮「保存」）；左树
  `#configTree`、表格关网格线 / 表头 `#FAFAFA` / 行高 36；数字输入限宽 180（原被拉伸到 582px）；
  `ERR_STYLE` 的裸 `red` → `theme.ERROR`；新增 `_set_inst_status()` 按 `●/○` 前缀上色
  （**文本一字不改**，测试按子串断言）。窗口 1040×720，`CharacterEditDialog` 600×700
  （表单自然最小宽 ~562px，再窄就挤出横向滚动条）。
- `license_dialog.py`、`log_panel.py`（`objectName="logView"`，等宽与底色交全局 QSS）、
  `labels.py`（新增 `state_kind()`：只给语义不给色值，与 `theme.py` 职责分开）。

**Qt QSS 踩坑（写进 `theme.py` 注释，免得再踩）**
1. `::down-arrow` **只认 `image:`**——照抄 CSS 的「0 尺寸盒子 + 三边透明边框」三角画法渲染成
   一个**实心方块**；
2. 只给 `::drop-down` 描边 → 箭头**整个消失**（`QStyleSheetStyle` 一接管这个子控件就不再用
   基础样式的箭头图元）。最终一条 `::drop-down` / `::down-arrow` 都不给，接受 Fusion 那道
   淡分隔线；
3. **别碰 `QCheckBox::indicator`**——接管了不给 `image:`，未勾选的框会整个消失；
4. QSS **不支持 `box-shadow`**，规范本身也要求「优先用 1px 分割线分区」，故一律描边 + 留白；
5. `apply_theme` 里 `setStyle("Fusion")` 不能省——Windows 默认 `windowsvista` 会忽略
   QComboBox / QSpinBox 的大量 QSS 属性；且必须在**建控件之前**调用（QSS 在 polish 时读
   动态属性，`[primary="true"]` 才会生效）。

**测试**：新增 `tests/unit/gui/test_theme.py` 31 条。重点不是渲染效果而是**一致性约束**——
间距/圆角/字号单调递增、色值全是 `#RRGGBB`、五个语义的浅底+深字+点齐备、
**QSS 占位符与令牌表双向对账**（用了没定义 / 定义了没用都报名字）。
选 `Template.substitute()` 而不是 `safe_substitute()` 就是为这条：本次真踩到 `$sp_xs` /
`$sp_2xl` 用了却没进令牌表，`substitute` 当场 KeyError，`safe_substitute` 会静默留下字面量。
`test_apply_theme_switches_to_fusion` 里**先清样式表再读基础样式**——装了 QSS 后
`QApplication.style()` 返回的是 `QStyleSheetStyle` 代理（`objectName` 空、没有 `baseStyle()`），
读完再把样式表装回去（qapp 是全测试会话共用的）。
`test_gui_smoke.py` 同步：`windowTitle == "RoK 助手"`、`开始运行` / `停止`。

**验证**：GUI 相关子集 125 passed；离屏探针 `_probe_ui_theme.py` 导出四张 PNG 到 `_ui_shots/`
（**离屏环境零字体，中文渲染成豆腐块，属环境现象不是缺陷**——能看的是版式与几何；
用脚本打印控件几何做数值核对，比读图便宜）。全量 `pytest tests/ -q` →
**978 passed / 0 failed**（5m04s，基线 947 + 31）。

**重构自己带出来的一条缺陷（同日修）**：全局 QSS 的 `QWidget { font-family: … }` **盖掉了
控件自己的 `setFont()`**——样式表的字体属性优先于控件字体，`setFont` 静默失效不报错。
后果是激活对话框里机器码/激活码的**等宽字体被刷回雅黑**（等宽的意义就是让 `O/0`、`I/l`
分得开，机器码要用户手抄或截图转述）。发现方式很便宜：构造对话框后**打印
`widget.font().families()`**，不读图。修法 `theme.make_mono(widget)`：打
`objectName="monoText"`，由 QSS 用比 `QWidget` 更具体的 `#monoText` 选择器把族钉回去，
字号仍由 `setFont` 给。顺带把 `tools/license_tool.py`（发码工具，不进发行包）也接上同一套
令牌——同一个仓库里没必要两处等宽字体栈、两套配色各写各的。
测试 +3（`test_make_mono_pins_the_family_via_object_name` 只断言打了标记；
`test_mono_text_actually_renders_monospace` 走完整链路读回字体——**只断言标记是不够的，
选择器写错时那条照样绿**）。

**仍未做**：实机开窗看一眼。业务零改动，但**版式只在离屏验证过**。

## 2026-10-13 城寨等级扩到 1–15 · 两区间互斥（代码级；区间模板待采）

**由来**：11–15 级寨子上线，目标等级不再止于 10。更关键的是：搜索面板上 **1–10 与 11–15
不是一根连续滑条，而是两个互斥的区间**，由一个独立的区间控件切换——面板同一时刻只能停在
一个区间上。所以「同一次搜索里混选两个区间」在游戏里根本走不通：另一个区间的等级搜不到。

**四件事**（Task 1–5，均已提交评审）：

1. **等级范围扩到 1–15、两区间互斥**（`infra/config.py`）：`MIN_TARGET_LEVEL=1` /
   `MAX_TARGET_LEVEL=15` / `RANGE_BOUNDARY=10`，加 `level_range(lv) -> (low, high)`
   （1–10 → (1,10)；11–15 → (11,15)）把「区间」这个量给出一个名字，供三处复用（校验互斥、
   切面板区间、盲降降到底），不再三处各写一遍 `if lv > 10`。`_check_levels` 校验改成
   1–15，并新增**区间互斥**：按区间下界去重后还剩两种即拒绝（报错含
   「不能混选两个等级区间」）。`MAX_TARGET_LEVELS=3`（每角色等级数上限）不变；
   `RAIDER_TARGET`(0) 与等级仍互斥。

2. **GUI 改 15 个复选框、两区间视觉分隔**（`gui/config_dialog.py`）：15 个框，第 2 行留白
   放一条分割线，11–15 落到第 3 行。**选满 3 个时的锁定只作用于当前区间**——另一区间的未选框
   保持可点，因为「点它就是换区间」；锁掉等于不让人换区间。

3. **车头设等级前先切区间**（`workers/leader_sm.py`）：新增 `_switch_level_range(target)`，
   与 `tab_fortress`/`tab_raider` 同一套惯用法——**模板只裁未选中（灰）态，命中 ⇔ 当前不在该
   区间 ⇔ 点它**；已在目标区间就不命中、`_click` 自动跳过，故**不需要先读状态**（「面板当前停在
   哪个区间」本就不容易读准）。识别器 id 为 `level_range_low` / `level_range_high`。
   盲降（读不出等级时的回退）落到**目标区间的下界**：1–10 落 1、11–15 落 11；点击次数由
   `_blind_reset_clicks = (high - low) + 3` 给出——**1–10 仍是 (10-1)+3=12 点（与改动前逐字
   相同）**，11–15 是 7 点。

4. **跨区间缓存失步修复**：`_LEVEL_CACHE`（弱引用缓存上次面板等级，只服务盲降回退路径）里的
   等级若**与目标不在同一区间就作废**（`level_range(cached)[0] != low`）——否则面板切了区间后
   缓存还是另一个区间的旧值，盲降会按错误的起点点差量。`_verify_level` 同理：回读值与目标
   **跨区间**时不补点（从 8 点 + 到不了 13），判失败交给 `no_result` 计数兜住本轮。

**唯一外部依赖（本功能对真机尚未生效）**：区间控件的两张模板 PNG（`level_range_low` /
`level_range_high` 的**灰态**）**需要实机截图裁剪，目前还没有**。识别器缺失时的行为按区间分岔：

- **11–15 目标**：缺 `level_range_high` → `_switch_level_range` **抛 `RuntimeError`**（点不动
  区间控件就会在 1–10 区间里搜，等于「配置要 13、实际搜 8」——宁可按异常结束本轮，不静默）。
- **1–10 目标**：缺 `level_range_low` → **只 warning**，行为与改动前一致（旧模板包没有这个条目；
  若面板实际停在 11–15 区间会搜错等级，但回读值不在目标区间会被 `_verify_level` 判失败并留 warning，
  最终由 `no_result` 计数自然兜住本轮）。

**所以**：模板采到之前，**11–15 目标在真机上走不到**，本功能对真机**尚未生效**；1–10 区间行为
与改动前**逐字相同**。真机验收步骤见 `docs/PROGRESS.md` 待办（前置：先采区间控件模板 PNG）。
**未改模板图、未换 YOLO 权重**，故**不重跑** `tools/calibrate_yolo_threshold.py`。

**文档同步**：`config.example.yaml` 的 `target_levels` 注释、`docs/配置说明.md`（等级段与字段表）、
`docs/ACCEPTANCE.md`（§3.6 的「level=11 应被拒」改成 level=16——11 现在合法了）、
`docs/PROGRESS.md` 均已同步到 1–15 + 区间互斥。

## 2026-10-13 修正：删除区间切换机制（面板上没有区间控件）

**由来（用户实机确认，原话）**：

> 不需要切换。等级的区间上下限跟游戏账号所在的大地图有关系，完全由用户自己配置决定，
> 你只需要做好他们是配置互斥的就行

**证据**（`imgs/zhaizi/11ji.png`，1920×1080，数值判据非目测）：老截图（等级 9）滑条绿色
填充占轨道 81%、手柄在约 89% 处；今日等级 11 绿色填充**零像素**、手柄贴最左端，而面板布局
像素级未变（`+` 按钮两次都在 `(642, 554)`）——只有轨道区间自己变了。面板全部内容只有：
页签 / 说明框 / 等级滑条（**单手柄**） / 搜索按钮，**没有区间控件**。等级的区间上下限由
账号所在大地图决定，不需要、也无从「切换」。

**后果（本修正的唯一动机）**：同日上一节的 `_switch_level_range` 假设面板上有一个可点的
区间控件，靠 `level_range_high` / `level_range_low` 两张灰态模板切换。识别器永远不存在
（manifest 里没有、也不会有），于是**任何配了 11–15 的用户一跑就抛 `RuntimeError` 停机**
——正是用户要能用的那一段。故删。

**改了什么**：

1. `workers/leader_sm.py`：删掉 `_switch_level_range` 整个函数，以及 `_select_level` 里对
   它的调用和「必须先切区间再读等级」那行注释；顺序回到**点页签 → 读等级 → 点差量 → 回读
   校验**。`RANGE_BOUNDARY` 随函数失去唯一用途，从 import 块移除。
2. **保留**（仍然正确，不要顺手删）：`_blind_set_level` 的区间感知起点（`start = low`）与
   同区间缓存判断；`_blind_reset_clicks(target)`（1–10 算 12 点、11–15 算 7 点）；
   `_verify_level` 的跨区间回读守卫（现在是删掉切换机制后**唯一的兜底**——配置 13 而面板停在
   1–10 时干净判失败，交给 `no_result` 计数兜住本轮）；`_read_level` 的 1..15 校验。仅把两处
   注释里「切区间 / 区间没切过去」的措辞改成「配置的区间与账号所在大地图不符」。
3. 测试（`tests/unit/workers/test_leader_sm.py`）：删掉整个「等级区间切换」小节
   （`_add_range_recs` 助手 + 5 条用例），保留的区间感知用例（盲降落 11、跨区间缓存作废、
   同区间缓存复用、回读跨区间判失败）去掉 `_add_range_recs` 注入，并把点数断言里那次
   「切区间点击」减掉（`1+1+1+7+2` → `1+1+7+2` 等）。

**文档同步**：spec §4.2 加勘误（保留原文）；`docs/PROGRESS.md` 当前状态/待办去掉「先采模板
PNG」前置；`docs/PACKAGING.md` 删掉「区间控件模板未落地前不要发包」整节与 selftest 段的交叉
引用（门槛已不存在）；`config.example.yaml` 与 `docs/配置说明.md` 的注释/说明改成「区间由
账号所在大地图决定」；实现计划 `docs/superpowers/plans/2026-10-13-城寨等级1-15.md` 顶部加
作废横幅（Task 2 / Task 4 被推翻）。**未动** `templates/manifest.yaml`。

**「1–10 与 11–15 互斥」这条配置要求仍然成立**——用户明确要的正是它。11–15 的实机验收仍待做，
但不再有模板前置。

## 2026-10-13 多模式框架（寨多多/宝石/答题）

用户要求给软件加两个模式（**宝石模式**、**答题模式**，先做空白页待开发），并把当前模式命名为
**寨多多模式**。澄清过程中长成**信息架构级**改动：模式各有配置、主界面按模式分页、每模式各自一个
「开始运行」。本次交付的是**多模式框架 + 城寨等级扩展**（等级 1–15 见同日另一节），不是「加两个
下拉项」。设计见 `docs/superpowers/specs/2026-10-13-多模式框架与城寨等级扩展-design.md`。

**① 配置按模式分区、老配置硬报错不迁移。** `config.yaml` 顶层由「扁平 `instances:`」改成
`app:`（公共：屏幕/路径/模型/反检测/收工阈值）+ `zhaiduo:` / `gem:` / `quiz:`（各持 `instances`）。
`zhaiduo.instances` **必填且至少 1 台**（`ZhaiduoConfig.instances = Field(min_length=1)`），
`gem` / `quiz` 可空。原挂在 `RootConfig` 上的 `_cross_checks`（实例 id 不重 / 角色 id 不重 /
至少 1 个 leader-either / 填兵目标互相指向 / leader 不许配填兵目标）**整块搬到 `ZhaiduoConfig`**
——校验跟着数据走：宝石/答题现在没有角色，硬套「至少一个 leader」会让它们当场加载失败。
`find_level_collisions` 签名由收 `RootConfig` 改为收 `list[InstanceConfig]`。
老格式（顶层 `instances:`）**硬报错、不自动迁移**：`RootConfig` 的 `mode="before"` 校验器把
pydantic 那句光秃秃的 `zhaiduo / Field required` 换成可操作文案——逐字是
「配置格式已更新：instances 现在挂在 zhaiduo 模式下。请删除 config.yaml 后重启，程序会从
config.example.yaml 重新生成一份。」放在 `mode="before"` 而不是 `load_config()`：`GuiController`
自己走 `model_validate`，不经过 `load_config()`。**发布顺序硬约束**：`config.example.yaml`
必须与代码同批（本次已同步）。

**② 模式是界面概念，不是运行时概念。** `config.yaml` 里**没有 `mode` 键**——模式不落盘，
固定开在寨多多（早先设计过的 `save_app_mode` 逐行回写配置那套机制整个删掉）。
`RuntimeCoordinator` 只跑寨多多（只有它实现了），取实例走 `config.instances_for(AppMode.ZHAIDUO)`
（2 处）——**模式 → 配置段的映射收敛在 `instances_for()` 这一处**，协调器不直读 `.zhaiduo.instances`。
`AppMode(str, Enum)` = `zhaiduo` / `gem` / `quiz`，中文标签 `MODE_LABELS` 放 `infra/config.py`
（跟 `RAIDER_LABEL` 同一先例：GUI 与协调器跨层共用中文文案）。
`IMPLEMENTED_MODES = frozenset({AppMode.ZHAIDUO})` 是「某模式做完了」的唯一开关。
**模式进入运行时的唯一入口是 `GuiController.start(mode: AppMode = AppMode.ZHAIDUO) -> bool`**，
里面加一道边界检查：模式不在 `IMPLEMENTED_MODES` 就 `error_occurred.emit("…尚未开放，无法启动任务")`
并返回 `False`（五行的成本换掉「某个 setEnabled 漏了就直接跑起来」）。返回 `False` 时界面
**不切运行态**（否则会谎报运行中）。

**③ 主窗口改「应用头 + 左导航 + 每模式一页」，开始/停止下沉。** 顶部操作栏解散：
「开始运行 / 停止」**下沉**到各模式页（`gui/mode_page.py` 的 `ModePage`）的页头，
「刷新配置 / ⚙ 配置」**上提**到应用头。左侧是 `QListWidget` 导航（宽 160，每模式一项），
右侧 `QStackedWidget` 每模式一页。`ModePage` 内容用固定索引三态：`0=CARD` 卡片流式网格 /
`1=EMPTY` 空态 / `2=LOCKED`「该模式尚未开放」占位。**互斥不是靠三处 `if` 维护的**，
而是 `MainWindow._sync_ui_state()` 从**三个输入**推导全部控件状态：`_running_mode`（运行中的模式）/
`page.mode`（本页的模式）/ 有无角色。据此：开始按钮 = 未运行且本页已实现；停止按钮 = 运行中且
运行的就是这一页；导航 = 未运行时才可点（**运行中锁导航**）；内容区按「未实现 → 占位 /
有角色 → 卡片 / 无角色 → 空态」选页。窗口 1200×800 → **1280×820**（让出 160 导航宽）。

**④ 配置对话框左树重排。** 左树从「全局 / YAML / 各实例」变成
**公共配置** / **寨多多模式**（下挂「模拟器  <名字>」实例子项，默认展开）/ **宝石模式** /
**答题模式** / **YAML 源码（高级）**。`_stack` 固定索引 0=公共 1=寨多多 2=宝石 3=答题 4=YAML、
实例页从 5 起——**五个固定页必须先全部 addWidget 完，实例页才能开始加**，否则实例页插进固定页
中间会让 gem/quiz/yaml 整体下移、点一个进另一个（静默串页，不报错）。「检测全部模拟器」从公共页
移到寨多多模式页（它是实例级动作）。`config_dialog` 的裸 dict 编辑路径由 `("instances", …)`
改到 `("zhaiduo", "instances", …)`；`humanize_loc` 的报错路径因此多一层 `zhaiduo` 模式键。

**测试**：新增 `tests/unit/gui/test_mode_nav.py`（导航选中 / 页内按钮归属 / `_sync_ui_state()`
三输入推导）；`test_gui_smoke` 的 `w.start_btn` 改取 `w._pages[ZHAIDUO].start_btn`；
`RootConfig(instances=[…])` 直构改 `RootConfig(zhaiduo={"instances": [...]})`；
`find_level_collisions` 调用点改收 `cfg.zhaiduo.instances`；`ConfigDialog._stack` 索引契约改
0=公共 / 1=寨多多 / 2=宝石 / 3=答题 / 4=YAML。

**文档同步**（Task 4）：`docs/配置说明.md` 重写结构段与实例段（面向非程序员、随包分发）；
`docs/ACCEPTANCE.md` §2/§3 的 GUI 描述与「开始运行」位置；`docs/PROGRESS.md` 当前状态/已落地/待办
与全量回归计数；本节。**未改** `templates/manifest.yaml`、未换 YOLO 权重，故不重跑
`tools/calibrate_yolo_threshold.py`。

## 2026-10-15 日志复盘（run 12:07）——归一化卡住改干净中止 + 成员重试路径补清理

用户给了 `logs/rok_assistant_20261015_120747.log`（685 行，12:07:50–13:31:40，**5 ERROR / 12 WARNING**）
问「异常是不是 bug、怎么修」。逐条落到根因后修了三处，**并撤回了我自己提错的一条**。

### A. 4×「归一化失败：卡在[未知]/[战争列表]视图」——**是 bug，会停机级别**（已修）

mumu1 的成员在 13:05:26 / 13:06:18 / 13:07:06 / 13:07:54 连抛 4 次。失败帧（`recordings/`）显示
一个全屏「战争」面板，**标题栏被游戏 toast 横幅压住**：`alliance_btn` 0.23–0.29、`search_icon` 0.177，
两个地图锚点全灭。`war_title` 在 13:05:26 那帧只拿 0.313——它是**纯 YOLO 判据**（manifest 没写
`yolo_threshold`，走默认 0.5；模板腿在真实战争列表上只有 0.21–0.31，0.9 的阈值形同虚设），
四帧 YOLO 置信度 0.313 / 0.592 / 0.669 / 0.683 **跨着 0.5**，所以 `member_sm.py` 里唯一那条
「关战争面板」的分支时灵时不灵。

**真正的缺陷不是阈值，是失败方式**：`member_sm._normalize_view` / `leader_sm._normalize_view`
的兜底写的是 `raise RuntimeError`。`WorkerRunner` 收到 step 异常**不重建 SM**，只退避 10s
**重进同一个状态**，于是同一帧被反复判、连续 `max_consecutive_failures*2 = 6` 次异常就停机。
4/6 已经烧掉了——**再撞 2 次环境卡顿，那个 worker 就永久退出**。CLAUDE.md 明写「卡住了必须写成
干净中止本轮」，`leader_sm._abort_round`（2026-10-12）已经改过这个坑，这两处漏网。

**修法**：新增模块常量 `state_machine.NORMALIZE_STUCK_REASON = "normalize_stuck"`（两个 SM +
runner 三处必须同一个字符串，散写字面量改名时不会报错、只会安静地退回「计入连续失败」——
`test_env_fail_reasons_cover_every_abort_reason` 是那个缺口的哨兵）。两个 `_normalize_view`
改为写 `ctx["failed"]/ctx["fail_reason"]` 并返回，各自在 `_setup()` 里、**通往其他目标的边之前**
注册出口边（leader → `END`/`_abort_round`；member → `exit_state`/`_normalize_stuck`，波次模式
回 IDLE 并丢掉起波窗口残留的信号）。`runner._ENV_FAIL_REASONS` 收编该原因 → 不计连续失败、
冷却后重建 SM 重收一次残留面板。视图名照旧进 WARNING 日志，可归因。

### B. 48×「联盟旗帜不可见，重试 (N/10)」+ 4× 收波——**是 bug，结构性的**（已修）

算术先对上：4 波 × 11 + 4 = 48。

根因：`_join_missed`（加入未生效的重试）把状态送回 `OPEN_WAR`，而 **`OPEN_WAR` 子图里没有任何
一条边能回到 `NORMALIZE`**（唯一能到 NORMALIZE 的是 `_next_target`，而它要求 `joined=True`）。
所以**一次验证失败就永久失去残留清理**（队列侧栏、战争面板 ✕、`search_back`/`map_btn`），
只剩 `_open_war` 的「旗帜 → 列表」两步，而旗帜模板恰恰是失效的那一个。实机时序吻合：
三个成员 13:22:14 行军后**同时**验证失败 → 13:22:24/55/56 三连 `加入未生效` → 计数器交错
→ 13:24:23/38、13:25:02 收波，整波一个没填上。

**修法**：两条 `_join_missed` 边的 to_state 改 `NORMALIZE`。**第一次改错了**——`_normalize_view`
是「**进入** NORMALIZE 那条边」的动作（`SWITCH_TO_SELF → NORMALIZE`），把状态切回 NORMALIZE
**不会跑它**，新写的回归用例当场把这一点抓出来（断言里 `(1671,64)` 没出现在点击序列里）。
改成 `_join_missed` 里**显式调一次** `_normalize_view(ctx)`，to_state 保持 NORMALIZE 以便
清理不掉时走出口边。

### C. 17/17「本波填兵结束（已填 0 个：无）」——**日志 bug，功能是好的**（已修）

`filled` 只在 `_next_target` 里添加，而配置里只点名了一个填兵目标（`config.yaml`），
`_wave_has_more` 直接为假、`_next_target` 从不执行 → 一整波明明填成功了，日志却是「已填 0 个」。
`_wave_done` 收波时把当前 `target_name` 一并计入。（`_wave_has_more` 的 docstring 早就写明
`filled` 只在 `_next_target` 里填充——这次是它没覆盖到的收波路径。）

### D. 1× `screencap returned undecodable data`（12:30:37）——**环境性，但有代码缺口**（已补）

用户点 Stop 后 3 秒（模拟器正在收尾），预检 12:33:20 已通过。`capture()` 对「adb 退出码 0 但
字节解不出图」这条路**没有重试**（`_run_checked` 只管非零退出），一次抖动就让 step 抛异常、
白计一次连续失败。改成「解不出就强制重连重截一次，两次都解不出才抛」，异常文案带最后一次的
字节数。**另注**：这类失败存下来的截图是**陈旧的**（`last_image` 来自上一次成功捕获）——
12:30:37 那张显示的是城市视图（`map_btn` 0.997），与真实卡住原因无关，读图时别被带偏。

### E. 3×「worker 在 2.0s 内未停止」——**非 bug**（不改）

`_STOP_TIMEOUT = 2.0` 而单步 10–30s；`_stop_event` 只在步与步之间检查；残留线程仍被引用、
可再次 `stop`；快速重启会让新旧线程短暂重叠。属设计内表现。

### F. 13×「系统时间比记录锚点早 2246559 秒，按锚点计」——**非 bug，按设计**（不改）

`guard.py` 的 `effective_now = max(now, last_seen)`，规范 §5.4，INFO 级别。副作用记录在案：
有效时间取 `max`，所以到期按未来锚点算。

### G. 车头空转 14 分钟（无 ERROR/WARNING，代价最大）——**我的修复方案是错的，已撤回**

我一度判它卡在**城市视图**、`queue_verdict` 的清理清单缺 `map_btn` 点击。读了
`leader_sm.queue_verdict` 才发现它**早就有**城市视图出口（点硬编码 `(72,1034)`），而且注释里
明确写着「`map_btn` 模板是地图视图的『进入城市』城堡按钮 (92,985)，在城市视图不匹配、
且**语义相反**，不能用它出城」。随后一个决定性探针在车头失败帧上量到
**`map_btn` conf 0.997、中心 (92,995)**（= 地图视图的城堡按钮），`search_icon` 0.747 ——
**那一帧是地图视图**，不是城市视图。真正的问题是 `queue_verdict` 的地图视图证明要求
`alliance_btn` **或** `search_icon` 匹配，而该帧：简化模式隐藏了联盟旗帜（0.182）、
放大镜 0.747 < 0.9、`queue_badge` 0.339 —— 三个独立边缘判据同时落空 → fail-closed 14 分钟，
直到 30s 宽限把它放出去。**这需要一张真机在线帧才能定标，本次不动代码。**

顺带记一条**代码库里尚未解决的矛盾**（我刻意没改，免得写下第二个错误）：`queue_verdict` 的注释说
`map_btn` 是**地图**视图的城堡按钮（有本次测量支持），而 `leader_sm.py` / `member_sm.py` 的
`_normalize_view` 注释说它是**城市**视图的按钮（与测量矛盾）。定标那次一起裁定。

### 观测性

`_set_status` 对相同状态去重，所以第 2–6 次连续异常在状态流/GUI 里**完全看不见**（只留一个
`error` 值）。`runner` 的异常分支改成**先加计数再记日志**，日志带「连续 N/M 次，达上限即停机」——
复盘 12:07 那次 4 连抛时，日志里读不出「还剩几次就停机」。

### 未解（需要真机）

13:06:18 / 13:07:06 / 13:07:54 三帧上 `war_title` 是匹配的，✕ 也按真实战争列表的几何
（bbox (1654,46)-(1694,84)、面积 693，与 (1671,64) 逐字节吻合）点到了，**但面板一直开着**，
直到集结准备倒计时在 ~13:07:57 归零才消失。静态帧分不清是「tap 没送达」还是「游戏在集结
准备期拒绝关面板」。抖动可以排除（σ=8 裁剪 ±24px vs 40×38px 的 ✕ ≈ 2.5%）。

### 测试

全量 `pytest tests/ -q` → **1019 passed / 0 failed / 0 error**（4m20s）。本次新增 6 条
（`test_adb_handle_source` +2 捕获重试、`test_member_sm` +2 收波计数与重试路径清理、
`test_normalize_view` 3→5），另有 2 条既有用例改判据（原来断言抛 `RuntimeError`，
现在断言干净中止 + `fail_reason`）。新增 `_Clock`（推进式假时钟）——原文件的 `_NoSleepTime`
时间恒定，用在 `_wait_for` 超时路径上会死循环。

## 2026-10-16 车头集结「被静默拒绝」是**误判**：queue_badge 模板混进地图背景（/systematic-debugging）

### 用户报的现象

12:19 那轮（`dist/rok-assistant/logs/rok_assistant_20261016_121842.log`）：

```
[12:19:49] worker mumu0/char_leader[阑珊寨子号] -> FORM_TROOP
[12:20:07] [车头] 行军点击后队列徽标未出现：集结被游戏静默拒绝（同目标已有集结），本轮放弃
[12:20:09] [车头] 本轮放弃：rally_rejected，冷却后自动重试
[12:20:11] worker ... 第 1 轮失败结束：rally_rejected（连续失败 1/3）
```

用户明确说明：**「但车头的集结已经真实发起」**——集结真发出去了，判据却说被拒。

### 根因：模板图里有背景，不是状态机的问题

`leader_sm._launch` 点完行军的发射验证是 `_wait_for("queue_badge", timeout=10.0)`，
10s 内 `_find("queue_badge")` 一直返回 None 才判 `rally_rejected`。所以问题在
**queue_badge 认不认**。

`templates/queue_badge.png` 是 46x46 的紧裁剪，但按钮体只占 x 4..44 / y 5..45，
**四个角是地图背景**（实测 BGR `[94,114,50] [74,84,94] [114,106,54] [51,51,30]`）。
`TM_CCOEFF_NORMED` 是整窗归一化相关、**没有掩膜**（`recognizers/template_match.py`），
于是「按钮背后站什么景物」直接决定这一帧的分数。逐像素复核（`_probe_qscore.py`）：
同一块按钮，四个实机帧上**内部区域与模板逐像素一致**，整窗分数却是

| 帧 | 旧模板整窗分 | 内部区域差异 |
|---|---|---|
| `_q_16384` | **0.786**（< 0.85 → 漏检） | ≈0 |
| `_q_16416` | 0.883 | ≈0 |
| `_q_16448` | 0.883 | ≈0 |
| `_q_16480` | 0.977 | ≈0 |

阈值 0.85 正好卡在这个摆幅中间——**真发出了却判没发**。连锁后果：整轮作废、
计入连续失败（3 次就收工），且 `mark_troops_out` / `mark_rally_launched`
**没写进账本**（写点在这条 return 之后），账本继续声称「部队在家」，把同一个
模板喂给集结门槛，弱化的是判据本身。

### 修法（只改模板这一个变量）

与另外几个队列图标同源（manifest 里 `queue_gather_icon` 等的注释「纯圆重裁
（去头像背景角落）」）：**内缩 8px 重裁 46x46 → 30x30**，按钮体内零背景像素。

| 量 | 旧 46x46 | 新 30x30 |
|---|---|---|
| 徽标可见帧 | 0.786 / 0.883 / 0.958 | 1.000 / 1.000 / 1.000 |
| 徽标不可见帧（493 张 `recordings/failure_*` + 1 张实机帧，**全部 1920x1080**） | ≤0.358 | ≤0.489 |

**阈值 0.85 有意不动**：去掉背景后它在两边各留 0.36 余量，本次只改模板。
（旧 manifest 注释写「正 1.000/0.907，负 ≤0.710」——那是 4 个点的量法，看不见
背景摆幅，正是它把这次漏检放过去的。）

- 模板图 `templates/queue_badge.png`（**该目录 `*.png` 不入 git**，旧图备份在
  `_bak_queue_badge_46x46_20261016.png`），`dist/rok-assistant/_internal/templates/`
  同步更新；manifest 注释重写为新的实测表。
- 新增锚点测试 `tests/unit/core/test_queue_badge_anchor.py`（8 条）：**先写、先在旧
  模板上红**（`visible_a` 分 0.786 断言 matched → AssertionError，复现的就是那一轮），
  改模板后全绿。fixture 是真实帧裁下的**队列列 ROI**（220x150，约 40KB/张；整帧
  2MB 不进 git），测试里贴回 1920x1080 画布再喂识别器。裁片脚本 `_probe_mkfix.py`。

### 验证

- 生产装配（dist manifest + dist 权重 + dist 模板）跑 `_probe_qscore.py`：
  `_q_16384` → **1.000 matched @ (1754,204)-(1784,234)**；无徽标帧 0.436 不命中。
- `pytest tests/unit/core tests/unit/workers -q` → **387 passed**；全量另跑。

### 两条**没做**的事（留档，别当成已实现）

1. **本轮失败没有截图**：`runner._save_failure_screenshot()` 只在 `except` 分支调用，
   干净中止（`fail_reason` 走 END）不留帧——所以「那 10 秒里徽标到底在不在」只能
   用事后帧（12:25 抓的，部队还在行军、徽标在场）反推，拿不到失败瞬间的原帧。
   这正是「判据由一帧得出、帧却没留下」的观测性缺口，值得单独改。
2. **发射验证仍只认 `queue_badge` 一条腿**（防御纵深：任一队列图标命中即可算发射
   成功）。这会改变门槛语义，需与用户确认后再动，本次不夹带。

## 2026-10-16 · 统计条 + 文字/图文模式 + 启停异步化（GUI 观感与手感）

用户一条需求拆成三件事：卡片区上方加统计条、加文字/图文显示模式开关、修「点开始/结束卡好几秒」。
按 `enterprise-ui-optimizer` + `test-driven-development` 走，每件都先红后绿。

### 卡顿的三个来源（先量再改）

| 位置 | 原来 | 现在 |
|---|---|---|
| `MainWindow._on_start` | 主线程同步跑 `controller.start()`：adb 预检 + 载 ONNX，真机几秒 | 丢后台线程，点击当场返回，相位切「启动中」 |
| `MainWindow._on_stop` | 主线程串行 `join` 每个 worker，每个最多 2s，号越多越久 | 同上 |
| `_on_refresh`（2s 定时） | 每个角色走一趟：协调器全帧 JPEG 编码 → 卡片解码 → 平滑缩放 | 空闲不取 / 文字模式不取 / 字节没变不重画；编码前先缩到 480×270 |

第三项最容易被忽略：画面绝大多数时候没变，而 1920×1080 按面积计价，号越多越贵。

### 相位状态机

`_running_mode: AppMode | None`（两态）换成 `_phase ∈ {IDLE, STARTING, RUNNING, STOPPING}` +
`_run_mode`（相位所属模式）。**`_set_phase()` 是唯一变更入口**，`_sync_ui_state()` 从它推导
全部按钮 enable 与文案（「启动中…」/「停止中…」）——spec §5.4「一个状态源推导」的原样延续。

- 启动中两个按钮都不可点：既防重复启动，也不能「停一个还没起来的东西」。
- `_on_run_finished`（自然收工）只在 `RUNNING` 时复位相位：收工与手动停止撞车时，
  收尾归 `_on_stop_done`——否则 worker 还没 join 完，按钮就先亮了「可再启动」。
- `closeEvent` 等后台任务收尾：QThread 不是守护线程，窗口先销毁就是
  「QThread: Destroyed while thread is still running」→ abort。

### 既有测试的时序假设要跟着改（6 处）

启停从同步变异步，`test_mode_nav` / `test_gui_smoke` / `test_gui_license` 里
「点完立刻断言」的 6 条必须改成转事件循环等结果（新增 `wait_until` 夹具，见 `tests/conftest.py`）。
其中一条是**静默变空测**：`test_stopping_unlocks_everything` 直接戳 `w._running_mode`，
改名后那只是个没人读的新属性、断言恰好都成立——已改成 `_set_phase`。

### 显示模式：为什么是「单键行内改写」而不是 `yaml.safe_dump`

`config.yaml` 里有 7 行注释在解释权重选型理由，而 `ConfigDialog` 早就在用 `yaml.safe_dump`
把它们全抹掉。显示模式要落盘，但**不该再制造一处**。`infra/config.set_card_view()` 因此
只认行：定位顶层 `app:` 段 → 替换/插入 `card_view` 那一行 → **回读校验通过才写盘**。
解析不了、找不到 `app:` 段、回读不符 → 返回 False **且不碰文件**。

两个已知边界（有意为之，非缺陷）：行内空映射 `app: {}` 形态拒绝改写；`app:` 段里缩进更深的
同名键不认（那属于嵌套段，改它等于改错地方）。两者都走「返回 False + 状态栏提示本次未保存」。

### 统计口径

`RuntimeCoordinator.stats()` → `{ok, failed, env, rounds, fills, target}`。

- 轮次按结局分开计数：以前只有一个 `rounds_done`，三种结局混在一起，当「完成个数」显示会虚高。
  三者之和恒等于 `rounds_done`（有测试钉住）。
- `target` = `max_rounds × 在跑角色数`；没有 runner 时给 0 而不是 `max_rounds`——
  界面此时该显示 `0/0`，不是一份假目标。
- 填兵次数落在 `ActionLedger.fill_count`（进程级）：SM 的 `ctx` 随每轮重建清零，
  答不出「一共填了几次」。`total_fills()` 刻意**只读已存在的条目**、不走 `_get()`——
  后者会给未知 char_id 建空条目，把 `has_record()` 顶成真，而它是集结门槛的 L0 准入判据：
  为了显示一个数字去撬门槛是拿安全换好看。
- 停止时先留存读数再丢 coordinator：用户点停止正是为了看这一轮的战绩。

### 逐文件

- `gui/theme.py`：`stat_value_style(kind)`（未知语义回落 default，不抛）、`make_segment(btn)`
  （顺带 `setCheckable(True)`——不可勾选的话 `:checked` 永远不成立且不报错）、
  `#statsBar` / `#statsValue` / `#statsName` / `QPushButton[segment="true"]` 四组 QSS。
  分段开关的 `:checked` 必须盖过 `:hover`，否则选中项被鼠标划过就退回未选中样式。
- `gui/mode_page.py`：统计条 + 分段开关（`view_mode_changed` 只在**用户点击**时发，
  `set_view_mode` 不发——启动读配置那条路再发一次就成了「读配置→发信号→写配置」的空转）。
- `gui/main_window.py`：相位机、`_run_async`、`_apply_view_mode`、`_on_refresh` 三道减法。
- `gui/character_card.py`：`set_view_mode`、文字模式高度 `_CARD_H - _THUMB_H - SP_MD = 278`。
- `coordination/runtime.py`：`_shrink_for_thumbnail()`（`INTER_AREA`，只缩不放，返回新数组
  ——**不动原帧**，识别链还在读它，尺寸一变所有 ROI 坐标全错位）。
- `gui/controller.py`：`card_view()` / `set_card_view()`（控制器是配置的唯一门面）。

### 验证

- 新增测试：`test_theme`(+5) / `test_mode_page_stats`(10) / `test_run_phase`(7) /
  `test_refresh`(8) / `test_view_mode`(8) / `test_runtime_snapshot`(5) / `test_controller`(+4)。
- 全套 **1098 passed**（5 分 28 秒）。收尾那一跑先红了一条，见下。
- 离屏探针 `_probe_ui_theme.py`：统计条 48px、卡片 440→278px、日志仍 160px 不裁切；
  文字模式与图文模式各出一张 `_ui_shots/*.png`。顺带修了探针里多模式重构后就失效的
  `_content_stack` 引用（现在跑必崩）。
- **实机复验未做**：统计条版式、分段开关手感、点开始/停止到底还卡不卡，都要开窗看。

### 收尾跑出的一条假回归：`test_runner_counts_rounds_by_outcome`

首跑 1097 passed + **1 failed**，单跑该文件、单跑 `tests/unit/workers` 全绿——
典型的「只在全套负载下红」。根因不在被测代码，在**我自己写的用例**：

`_run_env_rounds` 的等待循环是「`rounds_done >= n` 就 `stop()`」，而 `_EnvAbortSM`
每轮只花 ~10ms，主线程 `sleep(0.02)` 醒来时 runner 早跑到第 4、5 轮了。计数
**不是钉住的，是调度撞出来的**：空载偶尔冲过头，机器一忙必然冲。
`_probe_runner_counts.py` 加 4 条烧 CPU 的线程后 20 次里中 7 次（空载 20 次里 0 次）。

改法：`max_rounds=n_rounds`，让 runner **自己**在第 n 轮收工，等的是
`stopped_reason is not None`（`_check_stop_conditions` 命中后主循环立刻 break，
不再有下一轮），于是 `rounds_done == n` 是确定的。同文件里
`test_runner_stops_after_consecutive_failures` 等三条本来就是这么写的，只有这条
是新写的、漏了。

**教训**：并发用例里「等条件成立再叫停」只适合断言 `>=`；一旦断言写死某个
精确值，就必须让**被测对象自己**停在那个值上，不能靠主线程抢在它前面。

变异验证：注掉 `rounds_failed += 1` → 该用例红；还原 → 绿。断言非空。

## 2026-10-24 上下文经济性大清理（剔除无用资源）

**触发**：用户要求「剔除无用的资源，避免占据过多的上下文资源，造成 token 的浪费」。
**原则**：只删「文档已裁定可删」+「无引用且可重生」的；`CLAUDE.md` 的
「千万不要把在用的清理掉」逐项核过引用（src/tools/tests/docs 全 grep）。

### 删了什么（约 -6.6GB，根目录条目 ~130→62）

| 对象 | 体积 | 理由 |
|---|---|---|
| `rok_assistant/datasets/` | 5.2GB | ultralytics 按 CWD 误落地的 COCO 下载；真实数据集在 `dataset/`（1.2GB 完好），互不相干 |
| `logs/review/` 除 3 张 `_relabel_*.png` | ~421MB | `ingest_raw_imgs.py` 的覆盖图产出，`raw_imgs/`（310MB）还在，可重生 |
| `recordings/` 9 月失败帧（463 张，留 1 张负样本） | ~850MB | 问题均已在 9 月修复/冻结；`recordings/diag/`（30MB）同删 |
| `logs/_cap_raider/` | 84MB | 劫掠者抓帧；`templates/tab_raider.png` 已裁，探针还在 |
| `logs/annotate/` | 22MB | `annotate_live.py --save` 生成物（09-21 清过一次，又长出来的） |
| 根目录 38 个一次性探针 + 12 张 ROI 截图 | ~5MB | geom/tabs/text/tmpl/old/x/lvl/pred/perframe/panel/review/mktpl/runner_counts/roundtiming 系，无引用 |
| `.pytest_tmp/` + 根 `__pycache__/` | — | 前者是已知问题 7 的毒化源 |

### 保留了什么（在用的）

- **验证件**：`_probe_tabchain/march/nav/noon/raider_search/raider_fix/cwdfix/cwdlocks/1015_fail/
  mkfix/gem_*/gate_*/search_*/live_q/qscore/ui_theme/quiz_frames`——换权重/换页签/
  未决项 16/17 定标还要重跑；`_probe_mkfix.py` 被 `test_queue_badge_anchor.py` 点名。
- **文档点名的证据帧**：`_q_16*.png`（10-16 queue_badge 重裁根因表）、`_t_*.png`
  （未决项 17 静态帧）、`logs/_probe_gate_live_mumu0.png`（未决项 16 的帧）、
  `failure_mumu1_char_jy_20260915_001019.png`（`audit_empty_frames.py` docstring 负样本）。
- **文本证据**：`_calib_v11/v12.txt`、`_cmp_v8_v9/v11_v12.txt`、`_boxcheck/`、
  `rok_assistant_20261015_120747.log`、`_train_v*.log`（09-21 裁定保留）。
- **源数据**：`raw_imgs/`（310MB 待入库素材）、`dati/`（题库与验收素材来源）、
  `recordings/gem_probe/`（欠账 ③ 联络表）、10 月失败帧（46 张）。

### 验证

- `src/tools/tests` 全 grep：无任何代码引用被删文件。
- `pytest tests/integration/test_config_dialog.py -q` → **82 passed**（含答题模式界面化新增 12 条）。
- `QT_QPA_PLATFORM=offscreen pytest tests/ -q` → **1321 passed**（全套含答题界面化改动，无回归）。
- 体积：logs 546MB→49MB，recordings 928MB→182MB。

### 答题入口倒计时门禁（2026-10-24）

用户截图 + MuMu 录屏（17s，地图→事件面板→国士无双→前往→答题页）实证：初试/终试
没到开始时间时，活动页显示「距开始还有 01:13:43」（OCR 为两块：标签 + 时间），
「进入」按钮置灰，点了不生效。旧逻辑会把这个置灰按钮当入口反复点，4 拍导航步数
耗光后 `quiz_entry_missing` 中止。

**用户拍板：无限等待到开始**（倒计时可能以小时计）。

- `core/quiz/screen.py` 新增 `entry_countdown_active(blocks)`：匹配
  `距[离开]?开?始还有`（含「距离开始还有」变体与标签时间合并块）；「距结束还有」
  （活动已开、即将结束）不挡；「开始时间：13:00」常态文案不误判。
- `workers/quiz_sm.py` `_open_quiz_step` 加门禁：倒计时期间不点进入、**不消耗
  导航步数**（耗光 4 拍就打不进去了），按 `_COUNTDOWN_POLL = 20s` 经
  `_not_before` 非阻塞轮询（Stop 随时响应），倒计时结束继续原导航逻辑；
  日志只记一次（`_countdown_logged`）。
- 不新增 fail_reason：等待不是失败，`runner.py` 的 `_ENV_FAIL_REASONS` 不用动。
- 测试：`test_quiz_screen.py` 5 条（fixture 用用户截图的真实 OCR 坐标，1920×1080）
  + `test_quiz_sm.py` 2 条（倒计时期间零点击/时钟冻结无动作/6 帧倒计时不耗步数）。
- `QT_QPA_PLATFORM=offscreen pytest tests/ -q` → **1328 passed**。
  注意：全套测试在**后台 shell** 里跑会全量报 collection error（环境问题），
  必须前台跑。

### 国士无双实机首测：0 分事故与补点修复（2026-10-24 晚间）

用户预约 19:00 初试，截图 + MuMu 录屏定位入口后实机连打（mumu0「如愿」，
127.0.0.1:16384）。流程全部走通：等倒计时 → 点「入场确认」→ 初试等待页 →
开考 → 10 题（每题约 21s，OCR/翻页/状态机全链路正常）。**但最终分数 0，
一题未中。**

复盘（截图序列像素对比 + 逐题 OCR）：
- 题库 10 题命中 6 题且答案全对（氮气/湿婆/巴黎/父子/尼摩船长/1570万年）
  ——机器人知道正确答案；
- Q7 两帧对比：巴黎选项 99% 像素变绿发生在**倒计时归零的自动结算**，
  非点击触发；B/C/D 零变化；
- 选项条真实范围 x[431,1060] y[444,572]，OCR bbox 中心 (535,509) **在条内**
  ——坐标没错；
- 地图实验：input tap 点空地正常弹面板——adb 点击链路没问题。

**根因**：每题只在 READ→ANSWER 点一次，且点击常发生在**题目飞入动画期间**
（OCR 读到文字 ≠ 按钮可点击），游戏吞掉动画中的点击；机器人没有补点，
只能等倒计时归零自动结算，10 题全部「未作答」。

**修复（TDD）**：`quiz_sm.py` VERIFY 没看到绿色 → 回 ANSWER 原地补点
（同一坐标，`_CLICK_RETRIES=2`，间隔 `_RETRY_DELAY=0.8s`），仍不绿才按
原逻辑走（不学这题、等自动翻页，始终不翻才判 `answer_not_accepted`）。
新增 2 条测试；全套 `QT_QPA_PLATFORM=offscreen pytest tests/ -q` → **1330 passed**。

顺带发现（驱动层，非产品 bug）：`sm.step({})` 每次传**新 dict** 会令所有
`fail_reason`/`round_over` 信号下一步即丢、中止边全部失效（状态机空转）。
`step()` 不传参时用内部 `self._ctx`，**外部驱动必须复用同一 ctx 或不传参**。

### 三种场次规则落地：初试 10 题 / 终试 20 题 / 日常不限时（2026-10-24 夜间）

用户补充国士无双的活动结构（此前代码只有「一轮 N 题」的单一模型）：

| 场次 | 时间 | 题量 | 单题时限 |
|---|---|---|---|
| 日常答题（周一至周五） | 任意时间 | 不固定，跑到活动结束 | 无 |
| 初试（周六） | 固定 13:00/19:00 入场 | 10 题 | 有（实机约 20s） |
| 终试（周日） | 固定 13:00/19:00 入场 | 20 题 | 有 |

- `core/quiz/screen.py` 新增 `detect_exam_type(blocks)`：题目帧上识别
  「初试」「终试」，认不出返回 None；`EXAM_QUESTION_LIMITS = {prelim: 10,
  final: 20}`。**检测点只在题目帧**——入场弹窗（「本场初试开始后将无法
  再……终试」）和活动主页（初试历史卡 + 终试明天卡并存）会同时出现两个
  考试名，那种画面返回 None，调用方保持原状。OCR 把标题和考试名粘成
  一块（实机失败弹窗的「国初试无双」）也能认。
- `workers/quiz_sm.py`：READ 的题目帧上识别考试类型（一轮内 sticky，
  `_reset_nav` 清零重认）；单轮题量上限动态化（`_exam_question_cap`：
  考试按真实题量，日常/识别失败用 `max_questions_per_round` 兜底）；
  补点预算自适应（`_click_retry_budget`：考试限时从紧 2 次 ×0.8s，
  日常无时限从宽 4 次 ×1.0s）。
- 测试 +11 条：screen 5 条（fixture 用实机截图真实坐标）+ SM 6 条
  （初试答满 10 题收轮的行为驱动、终试 20、日常配置兜底、sticky/清零、
  并存帧不覆盖、补点预算两态）。
- `QT_QPA_PLATFORM=offscreen pytest tests/ -q` → **1341 passed**（前台跑）。
- config.example.yaml / 配置说明.md（三种场次表）/ GUI 标签同步。
