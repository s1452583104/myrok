import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from infrastructure import setup_logger, get_logger
from coordination import EventBus, TaskScheduler, PluginManager
from business import ConfigManager, DetectionService, GameController, AutomationEngine
from gui import MainWindow


class DummyDetectionService:
    """当游戏未运行时使用的模拟检测服务"""
    def __init__(self):
        self._window_capture = None

    def initialize(self, window_title):
        logger = get_logger('DummyDetectionService')
        logger.warning("Using dummy detection service - game window not found")
        return True

    def detect(self):
        return None

    def get_last_detection(self):
        return None

    def find_element(self, class_name):
        return None

    def get_element_position(self, class_name):
        return None

    def is_element_visible(self, class_name):
        return False

    def get_window_capture(self):
        return self._window_capture

    def shutdown(self):
        pass


class DummyGameController:
    """当游戏未运行时使用的模拟游戏控制器"""
    def __init__(self):
        pass

    def initialize(self, window_capture):
        return True

    def click(self, x, y, button="left"):
        return False

    def click_element(self, element_position, button="left"):
        return False

    def move(self, x, y):
        return False

    def press_key(self, key):
        return False

    def release_key(self, key):
        return False

    def press_and_release(self, key, duration=0.1):
        return False

    def wait(self, min_seconds=0.5, max_seconds=1.5):
        pass

    def get_window_capture(self):
        return None

    def shutdown(self):
        pass


def main():
    """主函数"""
    # 初始化日志
    setup_logger('rok_assistant', 'logs/rok_assistant.log')
    logger = get_logger('main')
    logger.info("Starting ROK Assistant...")

    try:
        # 创建事件总线
        event_bus = EventBus()

        # 加载配置
        config_manager = ConfigManager('config.yaml', event_bus)
        if not config_manager.load_config():
            logger.error("Failed to load config")
            return 1

        # 验证配置
        if not config_manager.validate_config():
            logger.error("Invalid config")
            return 1

        # 加载插件
        plugin_manager = PluginManager(
            event_bus,
            search_paths=config_manager.get('plugins.search_paths', ['plugins'])
        )
        plugin_manager.load_plugins()

        # 初始化检测服务（使用模拟服务作为后备）
        detection_service = DetectionService(config_manager)
        window_title = config_manager.get('window.title', '万国觉醒')
        if not detection_service.initialize(window_title):
            logger.warning("Failed to initialize detection service, using dummy service")
            detection_service = DummyDetectionService()

        # 初始化游戏控制器（使用模拟控制器作为后备）
        game_controller = GameController(config_manager)
        window_capture = detection_service.get_window_capture()
        if window_capture is None or not game_controller.initialize(window_capture):
            logger.warning("Failed to initialize game controller, using dummy controller")
            game_controller = DummyGameController()

        # 初始化自动化引擎
        automation_engine = AutomationEngine(
            game_controller=game_controller,
            detection_service=detection_service,
            event_bus=event_bus
        )

        # 注册插件策略
        for plugin in plugin_manager.get_all_plugins():
            if hasattr(plugin, 'get_strategy'):
                strategy = plugin.get_strategy()
                if strategy:
                    automation_engine.register_strategy(plugin.name, strategy)

        # 初始化任务调度器
        task_scheduler = TaskScheduler(event_bus)

        # 创建Qt应用
        app = QApplication(sys.argv)

        # 创建主窗口
        main_window = MainWindow(
            config_manager=config_manager,
            event_bus=event_bus,
            detection_service=detection_service,
            game_controller=game_controller,
            automation_engine=automation_engine,
            task_scheduler=task_scheduler,
            plugin_manager=plugin_manager
        )

        # 更新插件列表
        main_window.update_plugins_list()

        # 显示主窗口
        main_window.show()

        # 运行应用
        logger.info("ROK Assistant started successfully")
        return app.exec()

    except Exception as e:
        logger.error(f"Failed to start ROK Assistant: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1
    finally:
        logger.info("ROK Assistant stopped")


if __name__ == '__main__':
    sys.exit(main())