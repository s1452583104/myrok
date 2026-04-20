#!/usr/bin/env python3
"""采集统计模块.

记录和统计宝石采集的各项数据.
"""

import time
from dataclasses import asdict, dataclass
from typing import Dict

from infrastructure.logger import get_logger


@dataclass
class TeamStats:
    """队列统计.
    
    Attributes:
        team_id: 队列ID
        dispatch_count: 派遣次数
        recall_count: 召回次数
        garrison_count: 驻扎次数
        collected_gems: 采集宝石数量
    """
    
    team_id: int
    dispatch_count: int = 0
    recall_count: int = 0
    garrison_count: int = 0
    collected_gems: int = 0
    
    def to_dict(self) -> dict:
        """转换为字典.
        
        Returns:
            统计字典
        """
        return {
            "team_id": self.team_id,
            "dispatch_count": self.dispatch_count,
            "recall_count": self.recall_count,
            "garrison_count": self.garrison_count,
            "collected_gems": self.collected_gems,
        }


class CollectionStatistics:
    """采集统计.
    
    记录宝石采集的各项统计数据，包括总采集量、
    派遣次数、召回次数、驻扎次数等。
    """
    
    def __init__(self):
        self._total_gems = 0
        self._total_dispatches = 0
        self._total_recalls = 0
        self._total_garrisons = 0
        self._team_stats: Dict[int, TeamStats] = {}
        self._start_time = time.time()
        self._logger = get_logger(self.__class__.__name__)
    
    def team_dispatched(self, team_id: int):
        """记录部队派遣.
        
        Args:
            team_id: 队列ID
        """
        self._total_dispatches += 1
        if team_id not in self._team_stats:
            self._team_stats[team_id] = TeamStats(team_id)
        self._team_stats[team_id].dispatch_count += 1
    
    def team_recalled(self, team_id: int):
        """记录部队召回.
        
        Args:
            team_id: 队列ID
        """
        self._total_recalls += 1
        if team_id in self._team_stats:
            self._team_stats[team_id].recall_count += 1
    
    def team_garrisoned(self, team_id: int):
        """记录部队驻扎.
        
        Args:
            team_id: 队列ID
        """
        self._total_garrisons += 1
        if team_id in self._team_stats:
            self._team_stats[team_id].garrison_count += 1
    
    def add_gems(self, team_id: int, gems: int):
        """添加宝石收益.
        
        Args:
            team_id: 队列ID
            gems: 宝石数量
        """
        self._total_gems += gems
        if team_id in self._team_stats:
            self._team_stats[team_id].collected_gems += gems
    
    @property
    def total_gems(self) -> int:
        """总宝石收益.
        
        Returns:
            总宝石数量
        """
        return self._total_gems
    
    @property
    def gems_per_hour(self) -> float:
        """每小时宝石收益.
        
        Returns:
            每小时宝石数量
        """
        elapsed = time.time() - self._start_time
        if elapsed < 3600:
            return self._total_gems
        return self._total_gems / (elapsed / 3600)
    
    @property
    def running_time(self) -> float:
        """运行时间（秒）.
        
        Returns:
            运行时间
        """
        return time.time() - self._start_time
    
    def get_report(self) -> dict:
        """获取统计报告.
        
        Returns:
            统计报告字典
        """
        return {
            "total_gems": self._total_gems,
            "gems_per_hour": self.gems_per_hour,
            "total_dispatches": self._total_dispatches,
            "total_recalls": self._total_recalls,
            "total_garrisons": self._total_garrisons,
            "team_stats": {
                tid: stats.to_dict() 
                for tid, stats in self._team_stats.items()
            },
            "running_time": self.running_time,
        }
    
    def reset(self):
        """重置统计数据."""
        self._total_gems = 0
        self._total_dispatches = 0
        self._total_recalls = 0
        self._total_garrisons = 0
        self._team_stats.clear()
        self._start_time = time.time()
        self._logger.info("Statistics reset")
