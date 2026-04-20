# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with code in this repository.

## Project Overview

This is **ROK Assistant** - a computer vision-based automation tool for the game "Rise of Kingdoms" (万国觉醒). It uses YOLO object detection to identify game UI elements and automate tasks like gem collection.

## Common Development Commands

### Environment Setup
```bash
cd rok_assistant
pip install -r requirements.txt
```

### Running Tests
```bash
# Core module tests (pytest)
python -m pytest test_core.py -v

# Integration tests (custom script)
python test_integration.py

# Run all tests together
python -m pytest test_core.py -v && python test_integration.py
```

### Running the Application
```bash
# GUI mode (default)
python main.py

# No-GUI mode (headless, log only)
python main.py --no-gui

# Basic functionality test mode
python main.py --test

# With custom config file
python main.py config.yaml
```

### Debugging / Diagnostics
```bash
# Step-by-step debug
python step_debug.py

# Debug launch issues
python debug_launch.py

# Launch with fixed config
python launch_fixed.py

# Diagnose capture issues
python diagnose_capture.py

# Test background input
python test_background_input.py

# Test specific game (Yuanbao)
python test_yuanbao.py
```

## Architecture

The project uses a **five-layer architecture**:

```
rok_assistant/
├── main.py              # Entry point (CLI args: --no-gui, --test)
├── config.yaml          # Configuration file
│
├── core/                # Core capability layer
│   ├── window_capture.py  # Windows window capture via Win32 API
│   ├── yolo_detector.py   # YOLO object detection wrapper
│   └── background_input.py # Background input simulation
│
├── business/            # Business logic layer
│   ├── game_controller.py # Game interaction (safe clicks, navigation)
│   └── config_manager.py  # Config loading + hot-reload via watchdog
│
├── coordination/        # Coordination layer
│   ├── event_bus.py       # Pub/sub event system
│   └── task_scheduler.py  # Task scheduling (interval/cron/manual triggers)
│
├── plugins/             # Automation plugins
│   └── gem_collect/
│       └── task.py        # Gem collection workflow
│
├── gui/                 # Presentation layer (PyQt6)
│   └── main_window.py     # Main window with live preview
│
├── models/              # Data models
│   ├── config.py          # Pydantic config models
│   └── detection.py       # Detection result models
│
└── infrastructure/      # Infrastructure layer
    ├── logger.py            # Logging setup
    └── exception_handler.py # Custom exceptions
```

### Key Flows

**Application Startup** (`main.py`):
1. Parse CLI args (--no-gui, --test, config path)
2. `create_application()` initializes: EventBus → ConfigManager → WindowCapture → YOLODetector → GameController → TaskScheduler
3. Route to GUI mode, no-GUI mode, or test mode

**Event-Driven Communication**:
- Modules communicate via `EventBus` (pub/sub pattern)
- Key events: `EngineStartedEvent`, `EngineStoppedEvent`, `TaskCompletedEvent`, `TaskFailedEvent`, `DetectionCompletedEvent`, `WindowFoundEvent`, `WindowLostEvent`, `ConfigChangedEvent`

**Gem Collection Workflow** (`plugins/gem_collect/task.py`):
1. Find game window → capture screenshot
2. YOLO detects gem mines
3. Check mine level against config threshold
4. Click mine → detect "gather" button → click it
5. Select army → confirm → wait for completion
6. Publish `TaskCompletedEvent` or `TaskFailedEvent`

### Configuration

- Main config: `config.yaml` in project root
- Config models: `models/config.py` (Pydantic)
- Hot-reload: `ConfigManager` watches file changes via `watchdog`
- Key sections: `window`, `model`, `safety`, `automation`, `interaction`, `logging`, `plugins`

### Testing Approach

- `test_core.py` - Tests individual modules (logger, config, event bus, models, safety controller)
- `test_integration.py` - Tests end-to-end flows (detection, game controller, gem collect, scheduler, events)
- Tests are run via pytest or directly as scripts
- No `tests/` directory convention - test files are at project root

### Dependencies

Core: PyQt6, torch, ultralytics, opencv-python, pyautogui, pywin32, PyYAML, watchdog, numpy, pillow

Testing: pytest, pytest-mock
