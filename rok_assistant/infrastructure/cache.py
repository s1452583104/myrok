import time
from typing import Dict, Any, Optional


class CacheSystem:
    """内存缓存系统"""
    
    def __init__(self, default_ttl: int = 300):
        """
        Args:
            default_ttl: 默认过期时间（秒）
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = default_ttl
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key not in self._cache:
            return None
        
        item = self._cache[key]
        if time.time() > item['expires']:
            del self._cache[key]
            return None
        
        return item['value']
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存值"""
        ttl = ttl or self._default_ttl
        self._cache[key] = {
            'value': value,
            'expires': time.time() + ttl
        }
    
    def delete(self, key: str) -> None:
        """删除缓存值"""
        if key in self._cache:
            del self._cache[key]
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
    
    def size(self) -> int:
        """获取缓存大小"""
        # 清理过期项
        self._clean_expired()
        return len(self._cache)
    
    def _clean_expired(self) -> None:
        """清理过期项"""
        expired_keys = []
        for key, item in self._cache.items():
            if time.time() > item['expires']:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]


# 全局缓存实例
cache = CacheSystem()