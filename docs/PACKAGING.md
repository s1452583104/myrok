# 打包成绿色 zip 发行包

面向「发给别人用」的场景：**解压即用，目标机器不需要装 Python**。

产物：`dist/rok-assistant-v<版本>-win64.zip`（约 150 MB），解压后双击
`rok-assistant.exe`。

> **训练数据不进包**：`dataset/`、`runs/`、`imgs/`、`raw_imgs/`、`logs/`、
> `recordings/`、`tools/`、`tests/` 全部排除，构建脚本会逐项断言。

## 一键打包

```bash
.venv/Scripts/python.exe -X utf8 tools/build_package.py
```

跑完拿到 zip。构建脚本会依次做四件事，**任何一步不过就退出、不出包**：

1. **前置检查** —— `models/detect.onnx` 在不在、`templates/manifest.yaml` 引用的
   每张模板图在不在、onnxruntime / pyinstaller 能不能导入
2. **PyInstaller** —— 按 `rok-assistant.spec`（onedir），约 50 秒
3. **产物断言** —— 必需资源齐全（模板清单、示例配置、检测模型、OCR 模型、
   `README-用户.txt`）；顶层没有混进训练数据 / torch / 源码；总体积不超红线
4. **打 zip**

常用参数：

```bash
# 只校验已有产物（改完 spec 想快速复检，或验证别人给的一包）
.venv/Scripts/python.exe -X utf8 tools/build_package.py --skip-build

# 只构建不打 zip（本地试跑）
.venv/Scripts/python.exe -X utf8 tools/build_package.py --no-zip
```

### 换权重之后

`models/detect.onnx` 是从 `runs/*/weights/best.pt` 导出的，**不在 git 里**
（`.gitignore` 忽略 `models/*.onnx`）。所以新克隆的仓库第一次打包前要先导出：

```bash
.venv/Scripts/python.exe -X utf8 tools/export_onnx.py
```

导出后**必须重跑** `.venv/Scripts/python.exe -X utf8 tools/calibrate_yolo_threshold.py`
复核阈值（manifest 的 `yolo_threshold` 与 `DEFAULT_YOLO_THRESHOLD` 都建立在
当前这份权重的分数分布上）。

## 验证这一包能不能用

绿色包最坑的失败模式是「在开发机上好好的，解压到别人机器上缺东西」——
因为开发机 `import cv2` 走的是 venv，掩盖了打包遗漏。

所以程序带一个自检：

```bash
cd dist/rok-assistant
./rok-assistant.exe --selftest
```

它**不开窗口**，跑一遍真实的识别链路（读模板 → 装 59 个识别器 → 拿一帧喂
ONNX 模型 → 跑 OCR），逐项打印 PASS/FAIL，并把结果写进
`logs/selftest.log`。退出码 0 = 全过。

**把 zip 发给别人之前，至少在一台干净机器上跑一次这个。**

当前基线（本机，2026-10-05）：

```
[PASS] 目录解析：resource_dir=…\_internal  user_dir=…  frozen=True
[PASS] cv2 导入 + 图像解码：cv2 4.10.0，解码往返 OK
[PASS] onnxruntime 导入 + provider：1.30.0 ['AzureExecutionProvider', 'CPUExecutionProvider']
[PASS] 检测模型加载 + 一帧推理：64 类，全黑帧检出 0 框，耗时 30ms
[PASS] 模板清单加载 + 识别器装配：59 个识别器
[PASS] rapidocr 导入 + 模型就位：…\rapidocr_onnxruntime\models 下 3 个模型
[PASS] PyQt6 导入：Qt 6.11.0
[PASS] 首启配置文件：…\config.yaml 通过校验
[PASS] 写权限：…\logs 可写
```

单帧 CPU 推理 26~30ms（目标 < 100ms），对轮询节奏绰绰有余。

## 授权与密钥（**不要打包 secrets/**）

发行包只带**公钥**（`src/rok_assistant/infra/licensing/pubkey.py`，已入库），
不带私钥。

- `secrets/license_private.key` 是发码的唯一凭据，**绝不进发行包**；
  `tools/build_package.py` 的产物断言里有一条硬失败专门盯它。
- 打包机上如果存在 `secrets/` 目录，**先确认它不在 `dist/` 里**再分发 zip。
- 首启行为不变：解压即用，默认 30 天试用，无需任何操作。

## 目标机器要求

- **Windows 64 位**（打包用的是 Python 3.14 + win_amd64）
- **MuMu 模拟器已安装**（绿色包不含模拟器）
- 游戏分辨率 **1920×1080**、界面语言**中文**（模板与检测模型都是按这个采集的）
- 不需要：Python、CUDA、任何 pip 包

## 首启行为

第一次双击 exe 时，`infra/app_paths.py` 的 `ensure_user_files()` 会：

1. 从包内 `config.example.yaml` 复制一份 `config.yaml` 到 **exe 同级目录**
2. 调 `infra/mumu.py` 的 `detect_mumu_paths()` 扫描常见安装位置，把
   `mumu_manager_path` / `adb_path` 填进去

**已存在的 `config.yaml` 绝不改动**——用户可能手改过。回填走逐行文本替换
（不是 YAML 往返），所以示例文件里的注释会保留下来。

探测没命中时（装在非常规目录），在「⚙ 配置」页点**「自动检测 MuMu/adb 路径」**
重试，或手动指定 `MuMuManager.exe` / `adb.exe`。

### 目录布局

```
rok-assistant/
  rok-assistant.exe      ← 入口（packaging/launcher.py）
  _internal/             ← 只读资源 = sys._MEIPASS = resource_dir()
    templates/           模板清单 + 53 张模板 PNG
    models/detect.onnx   检测权重
    rapidocr_onnxruntime/models/  OCR 模型
    config.example.yaml  首启种子
    README-用户.txt
  config.yaml            ← 首启生成（= user_dir()）
  logs/                  ← 日志、startup_crash.log、selftest.log
  recordings/            ← 失败截图
```

**两种根目录必须分开**（`infra/app_paths.py`）：

- `resource_dir()` —— 只读，冻结时是 `_internal`，源码运行时是仓库根
- `user_dir()` —— 可写，exe 同级。用户要能看到并编辑 `config.yaml`

不要 `os.chdir` 到 exe 目录：onedir 模式下 `datas` 落在 `_internal/`，
chdir 过去照样找不到 `templates/`。

## 体积构成

打包后约 326 MB，zip 约 150 MB。大头：

| 项 | 大小 | 说明 |
|---|---|---|
| `cv2/cv2.pyd` | 90 MB | OpenCV 本体 |
| `PyQt6/Qt6/bin/*` | ~50 MB | GUI 框架 |
| `onnxruntime/capi/*` | 37 MB | 推理后端 |
| `numpy.libs/*openblas*` | 20 MB | numpy 的 BLAS |
| `models/detect.onnx` | 12 MB | 检测权重 |
| `rapidocr_onnxruntime/models/` | ~15 MB | OCR 模型 |

`rok-assistant.spec` 里剔掉了这些确定用不到的大件：

- **cv2 的两个 ffmpeg 解码器 DLL（55 MB）** —— 只做 `imread/imdecode/imwrite/
  imencode` 和模板匹配，从不读视频。这两个是 delay-load，删掉不影响
  `import cv2`（已由 `--selftest` 的「cv2 导入 + 图像解码」项验证）。
  **注意**：它们是 PyInstaller 自带的 `hook-cv2` 在 `Analysis` 里加的，
  所以必须在 `Analysis` **之后**过滤 `a.binaries`，在 spec 顶部拦不住。
- `onnxruntime/tools`、`onnxruntime/datasets`、`shapely/tests` —— 第三方包
  自带的转换脚本 / 示例模型 / 测试

**torch 不在包里**：`excludes` 挡掉了 `torch`/`torchvision`/`ultralytics`
（venv 里光 torch 就 4 GB）。生产推理走 `core/recognizers/onnx_detect.py` 的
onnxruntime 后端，`YoloClassAdapter` 和 `template_registry` 一行都没改——
换的只是 `SharedYoloDetector._model()` 返回的对象（鸭子类型契约不变）。

## 排错

**构建报「缺少 models/detect.onnx」** → 先跑 `tools/export_onnx.py`。

**构建报「N 张模板文件缺失」** → `templates/` 里少了 manifest 引用的 PNG。
模板图被 `.gitignore` 忽略（只提交 `manifest.yaml` 和 `.gitkeep`），
新克隆的仓库没有它们。

**构建报体积超红线（500 MB）** → 大概率 torch 溜进来了，看 `excludes`。

**产物校验报「混进了开发工具脚本：_internal\onnxruntime\tools」** →
误报。顶层扫描只查 app 目录和 `_internal` 的第一层，第三方包内部的同名
子目录是正常的；出现这个说明扫描逻辑被改坏了。

**exe 双击没反应** → 看 `logs/startup_crash.log`（`console=False`，
traceback 只写这里）。

**解压到中文路径** → 模板加载走 `imread_unicode()`（`np.fromfile` +
`cv2.imdecode`），因为 Windows 上 `cv2.imread` 遇到非 ASCII 路径会**静默
返回 None**。但 adb / 模拟器那边不一定能处理，所以还是建议解压到英文路径。

**自检某一项 FAIL** → `logs/selftest.log` 里有异常类型和消息。

## 相关文件

| 文件 | 作用 |
|---|---|
| `rok-assistant.spec` | PyInstaller 配置（**入库**） |
| `packaging/launcher.py` | 入口脚本（`main_window.py` 用相对导入，不能直接当入口） |
| `packaging/README-用户.txt` | 随包分发的用户说明 |
| `tools/build_package.py` | 构建 + 断言 + 打 zip |
| `tools/export_onnx.py` | `.pt` → `.onnx` 导出与 parity 比对 |
| `src/rok_assistant/infra/app_paths.py` | 冻结/源码两种根目录解析 |
| `src/rok_assistant/infra/selftest.py` | `--selftest` 的实现 |
| `src/rok_assistant/infra/mumu.py` | `detect_mumu_paths()` 安装位置探测 |
