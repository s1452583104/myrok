#!/usr/bin/env python3
"""游戏启动管理模块.

负责游戏进程检测、自动启动、自动登录和进程监控.
"""

import os
import subprocess
import threading
import time
from typing import Optional

import psutil

from core.background_input import BackgroundInputController
from core.window_capture import WindowCapture
from infrastructure.logger import get_logger
from models.config import GameLauncherConfig


class GameLauncherManager:
    """游戏启动管理器
    
    职责:
    - 检测游戏进程状态
    - 自动启动游戏
    - 等待游戏加载
    - 自动登录
    - 进程监控和异常重启
    
    线程安全: 是
    """
    
    def __init__(self, config: GameLauncherConfig):
        """
        Args:
            config: 游戏启动配置
        """
        self._config = config
        self._process: Optional[subprocess.Popen] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._logger = get_logger(self.__class__.__name__)
    
    def check_game_running(self) -> bool:
        """
        检查游戏是否已运行
        
        Returns:
            bool: 游戏是否运行中
        """
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == self._config.process_name:
                    self._logger.info(f"Game process found: PID={proc.info['pid']}")
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False
    
    def start_game(self) -> bool:
        """
        启动游戏
        
        Returns:
            bool: 是否启动成功
        """
        try:
            if not os.path.exists(self._config.game_path):
                self._logger.error(f"Game exe not found: {self._config.game_path}")
                return False
            
            self._logger.info(f"Starting game: {self._config.game_path}")
            self._process = subprocess.Popen(
                [self._config.game_path] + self._config.launch_args,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
            self._logger.info(f"Game started: PID={self._process.pid}")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to start game: {e}")
            return False
    
    def wait_for_game_ready(self, timeout: int = 60) -> bool:
        """
        等待游戏加载完成
        
        Args:
            timeout: 超时时间(秒)
            
        Returns:
            bool: 是否准备就绪
        """
        start_time = time.time()
        window_capture = WindowCapture(self._config.window_title)
        
        while time.time() - start_time < timeout:
            if window_capture.find_window():
                self._logger.info("Game window found")
                return True
            time.sleep(1)
        
        self._logger.error(f"Game not ready within {timeout} seconds")
        return False
    
    def auto_login(self, window_capture: WindowCapture, ocr_engine) -> bool:
        """
        自动登录
        
        Args:
            window_capture: 窗口捕获实例
            ocr_engine: OCR引擎
            
        Returns:
            bool: 是否登录成功
        """
        if not self._config.auto_login.enabled:
            return True
        
        time.sleep(self._config.login_check_delay)
        
        for attempt in range(self._config.auto_login.max_retries):
            try:
                screenshot = window_capture.capture_background()
                if screenshot is None:
                    self._logger.warning("Screenshot failed, retrying...")
                    time.sleep(self._config.auto_login.retry_interval)
                    continue
                
                login_detected = self._detect_login_button(screenshot, ocr_engine)
                
                if login_detected:
                    self._logger.info("Login button detected, clicking...")
                    btn_pos = self._config.auto_login.login_button_position
                    center_x = btn_pos["x"] + btn_pos["w"] // 2
                    center_y = btn_pos["y"] + btn_pos["h"] // 2
                    
                    input_controller = BackgroundInputController(window_capture.hwnd)
                    input_controller.click(center_x, center_y)
                    
                    self._logger.info("Login button clicked")
                    return True
                
                self._logger.info(f"No login button detected, attempt {attempt + 1}")
                time.sleep(self._config.auto_login.retry_interval)
                
            except Exception as e:
                self._logger.error(f"Auto login attempt failed: {e}")
                time.sleep(self._config.auto_login.retry_interval)
        
        self._logger.error("Auto login failed after max retries")
        return False
    
    def _detect_login_button(self, image, ocr_engine) -> bool:
        """
        检测登录按钮
        
        Args:
            image: 截图
            ocr_engine: OCR引擎
            
        Returns:
            bool: 是否检测到登录按钮
        """
        if ocr_engine is None:
            return False
        
        region = self._config.auto_login.login_button_position
        text = ocr_engine.recognize_region(image, region)
        
        for keyword in self._config.auto_login.ocr_keywords:
            if keyword.lower() in text.lower():
                self._logger.info(f"Login keyword detected: {keyword}")
                return True
        
        return False
    
    def start_monitoring(self):
        """启动进程监控"""
        if not self._config.auto_restart.enabled:
            return
        
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self._monitor_thread.start()
        self._logger.info("Game process monitoring started")
    
    def stop_monitoring(self):
        """停止进程监控"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        self._logger.info("Game process monitoring stopped")
    
    def _monitor_loop(self):
        """进程监控循环"""
        while self._running:
            if not self.check_game_running():
                self._logger.warning("Game process not found, restarting...")
                if self.start_game():
                    self.wait_for_game_ready()
            time.sleep(self._config.auto_restart.check_interval)
    
    def initialize(self, window_capture: WindowCapture, ocr_engine=None) -> bool:
        """
        初始化游戏（检查、启动、登录）
        
        Args:
            window_capture: 窗口捕获实例
            ocr_engine: OCR引擎（可选）
            
        Returns:
            bool: 是否初始化成功
        """
        if self.check_game_running():
            self._logger.info("Game is already running")
            return True
        
        if not self.start_game():
            self._logger.error("Failed to start game")
            return False
        
        if not self.wait_for_game_ready():
            self._logger.error("Game not ready")
            return False
        
        if not self.auto_login(window_capture, ocr_engine):
            self._logger.warning("Auto login failed, manual login required")
        
        return True
