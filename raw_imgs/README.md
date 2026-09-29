# raw_imgs/ — 手工补图落盘目录

这里放**手工截的游戏整屏截图**，供 `tools/ingest_raw_imgs.py` 入库标注、训练新权重。

目录**不入 git**（`.gitignore` 已忽略，同 `recordings/`、`dataset/`），截图丢失需重拍。

---

## 一、怎么截（硬性规范，务必遵守）

| 要求 | 说明 |
|---|---|
| **必须整屏 1920×1080** | MuMu 原生分辨率（`adb exec-out screencap -p`）。 |
| **不要裁剪 / 缩放** | manifest 里所有模板 ROI 都是 1920×1080 的**绝对像素**，尺寸一变 ROI 全错。现有数据集里 50 张非 1080p 的裁剪帧是已知尺度污染源（719p 帧推理 conf 明显偏低）。 |
| **不要截窗口带标题栏** | 要游戏画面本身，不是模拟器窗口。 |
| **不要带检测 overlay** | 别截 `annotate_live.py` 弹窗里带框的画面——那些框会被当成画面内容学进去。 |
| **追求状态多样性，别重复刷屏** | 同一画面截 100 张没有增益。要的是：等级 1~10 各档、有无城寨提示、队列五种状态、预设各选中态、有无弹窗。 |

文件名随意（建议保留 MuMu 原始名），**文件夹决定场景**。

## 二、丢哪个文件夹

按**你截图时游戏停在哪个页面**选目录，不用管画面里具体有几个目标：

| 目录 | 游戏页面 |
|---|---|
| `01_zhaizi_search/` | 野蛮人/城寨**搜索页**（有「等级: N」滑条、搜索/返回按钮、野人城寨页签） |
| `02_warlist/` | **战争列表**（集结列表，含排序下拉） |
| `03_queue_panel/` | **队列栏**（右侧 `*/5` 队列头像那一条，含五种状态图标） |
| `04_march_preset/` | **行军编队预设页**（预设 1~6、兵种勾选、「创建部队」弹窗） |
| `05_char_settings/` | **设置 / 角色管理**（头像、切换确认弹窗） |
| `06_home_map/` | **主界面 / 地图 / 联盟** |
| `07_ap_refill/` | **行动力补充**弹窗 |
| `99_unsorted/` | 拿不准就丢这，我入库时归位 |

## 三、优先级（按实测实例数排序，越少越缺）

现在 63 个类里最缺样本的，**优先补这些**：

| 类 | 中文 | 现有实例 | v7 AP50 | 在哪个目录 |
|---|---|---|---|---|
| `selected_preset_5` | 选中预设5 | **0** | — | `04_march_preset` |
| `zhaizi_level_text` | 寨子等级文本 | **12** | **0.199** | `01_zhaizi_search` |
| `click_to_enter` | 点击进入 | 1 | — | `05_char_settings` |
| `selected_preset_2/4/6` | 选中预设2/4/6 | 1 各 | — | `04_march_preset` |
| `tab_fortress` | 野人城寨页签 | 2 | — | `01_zhaizi_search` |
| `switch_confirm_yes` | 切换确认-是 | 2 | — | `05_char_settings` |
| `queue_fight_icon` | 队列交战图标 | 5 | **0** | `03_queue_panel` |
| `sort_selector` | 排序选择器 | 18 | 0.421 | `02_warlist` |
| `queue_battle_icon` | 队列战斗图标 | 25 | 0.462 | `03_queue_panel` |

> `zhaizi_level_text` 检不出，就是**寨子等级 OCR 读不出数字**的直接原因——OCR 只在 YOLO 框出等级文本框后才跑。补这个目录收益最直接。

## 四、入库

图丢好后跑：

```bash
.venv/Scripts/python.exe tools/ingest_raw_imgs.py --dry-run   # 先看覆盖报告
.venv/Scripts/python.exe tools/ingest_raw_imgs.py             # 正式入库
```

工具会：校验尺寸 → 模板匹配 + 位置先验 + OCR 三层预标注 → 硬链接进 `dataset/images/`
→ 写 `dataset/labels/` → **增量合并** `train.txt`/`val.txt`（不截断、保留既有手工帧）
→ 渲染复核 overlay 到 `logs/review/` → 打印每场景覆盖报告。

之后我逐帧复核 overlay 修正标注，再训 v8。
