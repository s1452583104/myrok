import json
import os
from typing import Dict, Any, Optional
from .logger import get_logger


class StateManager:
    """状态管理器"""
    
    def __init__(self, state_file: str = 'state.json'):
        """
        Args:
            state_file: 状态文件路径
        """
        self._state_file = state_file
        self._logger = get_logger(self.__class__.__name__)
    
    def save_state(self, state: Dict[str, Any]) -> bool:
        """保存状态
        
        Args:
            state: 状态字典
            
        Returns:
            bool: 是否保存成功
        """
        try:
            # 确保目录存在
            state_dir = os.path.dirname(self._state_file)
            if state_dir and not os.path.exists(state_dir):
                os.makedirs(state_dir, exist_ok=True)
            
            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            
            self._logger.info(f"State saved to {self._state_file}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to save state: {e}")
            return False
    
    def load_state(self) -> Optional[Dict[str, Any]]:
        """加载状态
        
        Returns:
            Optional[Dict[str, Any]]: 状态字典，失败返回None
        """
        try:
            if not os.path.exists(self._state_file):
                self._logger.info(f"State file not found: {self._state_file}")
                return None
            
            with open(self._state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            self._logger.info(f"State loaded from {self._state_file}")
            return state
        except Exception as e:
            self._logger.error(f"Failed to load state: {e}")
            return None
    
    def clear_state(self) -> bool:
        """清除状态
        
        Returns:
            bool: 是否清除成功
        """
        try:
            if os.path.exists(self._state_file):
                os.remove(self._state_file)
                self._logger.info(f"State file cleared: {self._state_file}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to clear state: {e}")
            return False