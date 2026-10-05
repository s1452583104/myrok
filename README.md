# rok-assistant

Rise of Kingdoms rally automation. See `docs/superpowers/specs/2026-07-15-rok-assistant-design.md` for the full design.

## Quick start

```bash
pip install -e ".[dev]"
rok-assistant
```

推理后端是 **onnxruntime**（CPU），不依赖 torch。`torch` / `ultralytics` 只在
训练和导出权重时需要：

```bash
pip install -e ".[train]"   # ultralytics / onnx / onnxslim
pip install -e ".[build]"   # pyinstaller
```

## Test

```bash
pytest tests/unit -v
```

## Configure

Copy `config.example.yaml` to `config.yaml` and edit.

## Package（发给别人用的绿色包）

```bash
.venv/Scripts/python.exe -X utf8 tools/build_package.py   # -> dist/rok-assistant-v0.1.0-win64.zip
./dist/rok-assistant/rok-assistant.exe --selftest          # 验证这一包能不能用
```

解压即用，目标机不需要装 Python。换检测权重前先跑 `tools/export_onnx.py`。
详见 [`docs/PACKAGING.md`](docs/PACKAGING.md)。
