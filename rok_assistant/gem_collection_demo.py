#!/usr/bin/env python3
"""宝石采集功能集成示例.

演示如何使用游戏启动管理器和宝石采集管理器.
"""

import os
import time
from core import (
    BackgroundInputController,
    CollectionStatistics,
    GameLauncherManager,
    GemCollectionManager,
    WindowCapture,
    YOLODetector,
)
from coordination.event_bus import EventBus
from business.config_manager import ConfigManager
from infrastructure.logger import get_logger, LoggerFactory
from models.config import AppConfig


def main():
    """主函数."""
    LoggerFactory.setup()
    logger = get_logger("gem_collection_demo")
    
    logger.info("=== 宝石采集功能集成示例 ===")
    logger.info("正在加载配置...")
    
    try:
        logger.info("1. 加载配置文件")
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        event_bus = EventBus()
        config_manager = ConfigManager(config_path, event_bus)
        config = config_manager.load()
        logger.info(f"配置加载成功: {config_path}")
        
        logger.info("2. 初始化窗口捕获")
        window_capture = WindowCapture(config.window.title)
        if not window_capture.find_window():
            logger.warning("游戏窗口未找到")
            logger.info("模拟测试模式启动")
        else:
            logger.info(f"游戏窗口找到: HWND={window_capture.hwnd}")
        
        logger.info("3. 初始化YOLO检测器")
        yolo_detector = YOLODetector(
            config.model.path,
            config.model.confidence,
            config.model.iou_threshold,
            config.model.device,
        )
        logger.info("YOLO检测器初始化成功")
        
        logger.info("4. 初始化后台输入控制器")
        if window_capture.hwnd:
            input_controller = BackgroundInputController(window_capture.hwnd)
            logger.info("后台输入控制器初始化成功")
        else:
            input_controller = None
            logger.warning("后台输入控制器未初始化 (窗口未找到)")
        
        logger.info("5. 初始化游戏启动管理器")
        game_launcher = GameLauncherManager(config.game_launcher)
        logger.info("游戏启动管理器初始化成功")
        
        logger.info("6. 检查游戏运行状态")
        if not game_launcher.check_game_running():
            logger.info("游戏未运行，准备启动...")
            if game_launcher.start_game():
                logger.info("游戏启动成功")
                
                if game_launcher.wait_for_game_ready():
                    logger.info("游戏准备就绪")
                    
                    game_launcher.auto_login(window_capture, None)
                else:
                    logger.warning("游戏加载失败")
            else:
                logger.warning("游戏启动失败")
        else:
            logger.info("游戏已经在运行")
        
        logger.info("7. 检查宝石采集配置")
        logger.info(f"宝石采集状态: {'已启用' if config.automation.gem_collection.enabled else '未启用'}")
        logger.info(f"采集模式: {config.automation.gem_collection.mode}")
        logger.info(f"矿点数量: {len(config.automation.gem_collection.mine_coords)}")
        logger.info(f"队列数量: {len(config.automation.gem_collection.teams)}")
        
        if config.automation.gem_collection.enabled and window_capture.hwnd and input_controller:
            logger.info("8. 启动宝石采集")
            
            gem_manager = GemCollectionManager(
                config.automation.gem_collection,
                window_capture,
                yolo_detector,
                input_controller,
            )
            
            gem_manager.start()
            
            try:
                logger.info("宝石采集已启动，按Ctrl+C停止")
                time.sleep(5)  # 模拟运行5秒
                
                stats = gem_manager.get_statistics()
                logger.info("=== 采集统计 ===")
                logger.info(f"总宝石: {stats['total_gems']}")
                logger.info(f"每小时宝石: {stats['gems_per_hour']:.1f}")
                logger.info(f"派遣次数: {stats['total_dispatches']}")
                logger.info(f"召回次数: {stats['total_recalls']}")
                logger.info(f"驻扎次数: {stats['total_garrisons']}")
                logger.info(f"运行时间: {stats['running_time']:.0f}秒")
                
            except KeyboardInterrupt:
                logger.info("正在停止宝石采集...")
                gem_manager.stop()
                
                final_stats = gem_manager.get_statistics()
                logger.info("=== 最终统计 ===")
                logger.info(f"总宝石: {final_stats['total_gems']}")
                logger.info(f"每小时宝石: {final_stats['gems_per_hour']:.1f}")
                logger.info(f"派遣次数: {final_stats['total_dispatches']}")
                logger.info(f"召回次数: {final_stats['total_recalls']}")
                logger.info(f"驻扎次数: {final_stats['total_garrisons']}")
                logger.info(f"运行时间: {final_stats['running_time']:.0f}秒")
        else:
            if not config.automation.gem_collection.enabled:
                logger.info("宝石采集未启用，请在config.yaml中设置 automation.gem_collection.enabled: true")
            if not window_capture.hwnd:
                logger.info("游戏窗口未找到，无法启动宝石采集")
            if not input_controller:
                logger.info("输入控制器未初始化，无法启动宝石采集")
        
        logger.info("=== 演示完成 ===")
        
    except Exception as e:
        logger.error(f"主函数错误: {e}", exc_info=True)
        logger.info("=== 演示完成 (错误) ===")


if __name__ == "__main__":
    main()
