import os
import time
import subprocess
from typing import Optional
from infrastructure import get_logger


class GameLauncher:
    """游戏启动器"""
    
    def __init__(self, game_path: str, process_name: str = 'RiseofKingdoms.exe', startup_timeout: int = 120):
        """
        Args:
            game_path: 游戏可执行文件路径
            process_name: 进程名称
            startup_timeout: 启动超时时间（秒）
        """
        self._game_path = game_path
        self._process_name = process_name
        self._startup_timeout = startup_timeout
        self._logger = get_logger(self.__class__.__name__)
        self._process: Optional[subprocess.Popen] = None
    
    def is_game_running(self) -> bool:
        """检查游戏是否已运行"""
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and self._process_name.lower() in proc.info['name'].lower():
                    self._logger.info(f"Game process found: {proc.info['name']}")
                    return True
            
            # 备用方案：使用 tasklist
            result = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {self._process_name}'], 
                                   capture_output=True, text=True)
            if self._process_name.lower() in result.stdout.lower():
                self._logger.info(f"Game process found via tasklist")
                return True
            
            return False
        except Exception as e:
            self._logger.error(f"Failed to check game process: {e}")
            return False
    
    def launch_game(self) -> bool:
        """启动游戏"""
        try:
            if not os.path.exists(self._game_path):
                self._logger.error(f"Game path not found: {self._game_path}")
                return False
            
            self._logger.info(f"Launching game: {self._game_path}")
            self._process = subprocess.Popen(
                [self._game_path],
                cwd=os.path.dirname(self._game_path)
            )
            
            self._logger.info(f"Game process started with PID: {self._process.pid}")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to launch game: {e}")
            return False
    
    def wait_for_game_ready(self, check_interval: float = 2.0) -> bool:
        """等待游戏加载完成"""
        self._logger.info(f"Waiting for game to be ready (timeout: {self._startup_timeout}s)...")
        start_time = time.time()
        
        while time.time() - start_time < self._startup_timeout:
            if self.is_game_running():
                self._logger.info("Game process detected, waiting for window...")
                # 进程启动后等待一段时间让窗口创建
                time.sleep(5)
                return True
            
            time.sleep(check_interval)
        
        self._logger.error(f"Game startup timeout after {self._startup_timeout}s")
        return False
    
    def launch_and_wait(self) -> bool:
        """启动游戏并等待加载完成"""
        if self.is_game_running():
            self._logger.info("Game is already running")
            return True
        
        if not self.launch_game():
            return False
        
        return self.wait_for_game_ready()
