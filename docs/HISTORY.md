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
`runner` 的冷却/返城检测间隔、`member_sm` 的集结响应、`either_sm` 透传、`runtime`/`factory` 的
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
的调用点，节奏与改动前逐位相同**，既有测试不改一行也是绿的。

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

