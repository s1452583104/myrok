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
