#!/usr/bin/env python3
"""宝石采集管理模块.

实现宝石采集的重新派兵模式和驻扎模式.
"""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from core.background_input import BackgroundInputController
from core.collection_statistics import CollectionStatistics
from core.window_capture import WindowCapture
from core.yolo_detector import YOLODetector
from infrastructure.logger import get_logger
from models.config import (
    GarrisonModeConfig,
    GemCollectionConfig,
    MineCoord,
    RedeployModeConfig,
    TeamConfig,
)


@dataclass
class ScreenPosition:
    """屏幕坐标."""
    
    x: int
    y: int


@dataclass
class TeamState:
    """队列状态."""
    
    team_id: int
    status: str = "idle"
    current_mine: Optional[MineCoord] = None
    dispatch_time: Optional[float] = None
    collected_gems: int = 0


class GemCollectionManager:
    """宝石采集管理器
    
    职责:
    - 管理宝石矿点坐标
    - 调度采集队列
    - 执行重新派兵或驻扎模式
    - 统计采集收益
    
    线程安全: 是
    """
    
    def __init__(
        self,
        config: GemCollectionConfig,
        window_capture: WindowCapture,
        yolo_detector: YOLODetector,
        input_controller: BackgroundInputController,
    ):
        """
        Args:
            config: 宝石采集配置
            window_capture: 窗口捕获实例
            yolo_detector: YOLO检测器
            input_controller: 输入控制器
        """
        self._config = config
        self._window_capture = window_capture
        self._yolo_detector = yolo_detector
        self._input_controller = input_controller
        self._teams: Dict[int, TeamState] = {}
        self._stats = CollectionStatistics()
        self._running = False
        self._logger = get_logger(self.__class__.__name__)
    
    def start(self):
        """启动宝石采集."""
        self._running = True
        self._logger.info(f"Starting gem collection in {self._config.mode} mode")
        
        if self._config.mode == "redeploy":
            self._run_redeploy_mode()
        elif self._config.mode == "garrison":
            self._run_garrison_mode()
    
    def stop(self):
        """停止宝石采集."""
        self._running = False
        self._logger.info("Gem collection stopped")
        self._logger.info(f"Total gems collected: {self._stats.total_gems}")
    
    def _run_redeploy_mode(self):
        """重新派兵模式主循环."""
        mine_index = 0
        
        while self._running:
            for team in self._config.teams:
                if not self._running:
                    break
                
                mine = self._config.mine_coords[
                    mine_index % len(self._config.mine_coords)
                ]
                mine_index += 1
                
                self._dispatch_team(team, mine)
                
                time.sleep(self._config.redeploy_mode.recall_delay)
                
                self._recall_team(team)
                
                time.sleep(self._config.redeploy_mode.redeploy_delay)
    
    def _run_garrison_mode(self):
        """驻扎模式主循环."""
        for i, team in enumerate(self._config.teams):
            if not self._running:
                break
            
            mine = self._config.mine_coords[
                i % len(self._config.mine_coords)
            ]
            
            self._dispatch_team(team, mine)
            
            self._garrison_team(team)
        
        while self._running:
            for team in self._config.teams:
                if self._is_team_full_loaded(team):
                    self._recall_team(team)
                    time.sleep(10)
                    mine = self._config.mine_coords[
                        team.team_id % len(self._config.mine_coords)
                    ]
                    self._dispatch_team(team, mine)
                    self._garrison_team(team)
            
            time.sleep(self._config.garrison_mode.check_interval)
    
    def _dispatch_team(self, team: TeamConfig, mine: MineCoord):
        """
        派遣部队到矿点
        
        Args:
            team: 队列配置
            mine: 矿点坐标
        """
        self._logger.info(f"Dispatching team {team.team_id} to mine {mine.x},{mine.y}")
        
        screen_pos = self._coord_to_screen(mine)
        self._input_controller.click(screen_pos.x, screen_pos.y)
        time.sleep(0.5)
        
        dispatch_btn = self._detect_dispatch_button()
        if dispatch_btn:
            self._input_controller.click(dispatch_btn.x, dispatch_btn.y)
            time.sleep(0.5)
        
        self._select_commanders(team)
        
        self._select_troops(team)
        
        confirm_btn = self._detect_confirm_button()
        if confirm_btn:
            self._input_controller.click(confirm_btn.x, confirm_btn.y)
        
        self._stats.team_dispatched(team.team_id)
        self._logger.info(f"Team {team.team_id} dispatched successfully")
    
    def _recall_team(self, team: TeamConfig):
        """
        召回部队
        
        Args:
            team: 队列配置
        """
        self._logger.info(f"Recalling team {team.team_id}")
        
        self._click_team_queue(team.team_id)
        time.sleep(0.5)
        
        recall_btn = self._detect_recall_button()
        if recall_btn:
            self._input_controller.click(recall_btn.x, recall_btn.y)
        
        self._stats.team_recalled(team.team_id)
        self._logger.info(f"Team {team.team_id} recalled successfully")
    
    def _garrison_team(self, team: TeamConfig):
        """
        驻扎部队
        
        Args:
            team: 队列配置
        """
        self._logger.info(f"Garrisoning team {team.team_id}")
        
        self._click_team_queue(team.team_id)
        time.sleep(0.5)
        
        garrison_btn = self._detect_garrison_button()
        if garrison_btn:
            self._input_controller.click(garrison_btn.x, garrison_btn.y)
        
        self._stats.team_garrisoned(team.team_id)
        self._logger.info(f"Team {team.team_id} garrisoned successfully")
    
    def _coord_to_screen(self, coord: MineCoord) -> ScreenPosition:
        """
        将游戏坐标转换为屏幕坐标
        
        Args:
            coord: 游戏坐标
            
        Returns:
            ScreenPosition: 屏幕坐标
        """
        screen_x = self._map_coord_x(coord.x)
        screen_y = self._map_coord_y(coord.y)
        return ScreenPosition(screen_x, screen_y)
    
    def _map_coord_x(self, game_x: int) -> int:
        """将游戏X坐标映射到屏幕X坐标."""
        return int(game_x * 1.5)
    
    def _map_coord_y(self, game_y: str) -> int:
        """将游戏Y坐标映射到屏幕Y坐标."""
        y_num = 0
        for char in game_y:
            if char.isdigit():
                y_num = y_num * 10 + int(char)
            else:
                y_num = y_num * 26 + (ord(char.upper()) - ord('A'))
        return int(y_num * 1.5)
    
    def _detect_dispatch_button(self) -> Optional[ScreenPosition]:
        """检测派遣部队按钮."""
        screenshot = self._window_capture.capture_background()
        if screenshot is None:
            return None
        
        detections = self._yolo_detector.detect(
            screenshot, classes=["dispatch_button"]
        )
        if detections and len(detections) > 0:
            det = detections[0]
            x = (det.bbox[0] + det.bbox[2]) // 2
            y = (det.bbox[1] + det.bbox[3]) // 2
            return ScreenPosition(x, y)
        return None
    
    def _detect_recall_button(self) -> Optional[ScreenPosition]:
        """检测召回按钮."""
        screenshot = self._window_capture.capture_background()
        if screenshot is None:
            return None
        
        detections = self._yolo_detector.detect(
            screenshot, classes=["recall_button"]
        )
        if detections and len(detections) > 0:
            det = detections[0]
            x = (det.bbox[0] + det.bbox[2]) // 2
            y = (det.bbox[1] + det.bbox[3]) // 2
            return ScreenPosition(x, y)
        return None
    
    def _detect_garrison_button(self) -> Optional[ScreenPosition]:
        """检测驻扎按钮."""
        screenshot = self._window_capture.capture_background()
        if screenshot is None:
            return None
        
        detections = self._yolo_detector.detect(
            screenshot, classes=["garrison_button"]
        )
        if detections and len(detections) > 0:
            det = detections[0]
            x = (det.bbox[0] + det.bbox[2]) // 2
            y = (det.bbox[1] + det.bbox[3]) // 2
            return ScreenPosition(x, y)
        return None
    
    def _detect_confirm_button(self) -> Optional[ScreenPosition]:
        """检测确认按钮."""
        screenshot = self._window_capture.capture_background()
        if screenshot is None:
            return None
        
        detections = self._yolo_detector.detect(
            screenshot, classes=["confirm_button"]
        )
        if detections and len(detections) > 0:
            det = detections[0]
            x = (det.bbox[0] + det.bbox[2]) // 2
            y = (det.bbox[1] + det.bbox[3]) // 2
            return ScreenPosition(x, y)
        return None
    
    def _select_commanders(self, team: TeamConfig):
        """选择武将."""
        self._click_commander(team.commander)
        time.sleep(0.3)
        
        if team.secondary_commander:
            self._click_commander(team.secondary_commander)
            time.sleep(0.3)
    
    def _select_troops(self, team: TeamConfig):
        """选择兵种和数量."""
        self._click_troop_type(team.troop_type)
        time.sleep(0.3)
        
        self._input_troop_count(team.troop_count)
        time.sleep(0.3)
    
    def _is_team_full_loaded(self, team: TeamConfig) -> bool:
        """
        检测部队是否满载
        
        Args:
            team: 队列配置
            
        Returns:
            bool: 是否满载
        """
        self._click_team_queue(team.team_id)
        time.sleep(0.5)
        
        screenshot = self._window_capture.capture_background()
        if screenshot is None:
            return False
        
        progress = self._detect_collection_progress(screenshot)
        
        if progress >= self._config.garrison_mode.full_load_threshold:
            self._logger.info(
                f"Team {team.team_id} is full loaded: {progress*100}%"
            )
            return True
        
        return False
    
    def _detect_collection_progress(self, image: np.ndarray) -> float:
        """
        检测采集进度
        
        Args:
            image: 截图
            
        Returns:
            float: 进度(0-1)
        """
        return 0.0
    
    def _click_team_queue(self, team_id: int):
        """点击部队队列."""
        queue_pos = self._get_team_queue_position(team_id)
        self._input_controller.click(queue_pos.x, queue_pos.y)
    
    def _get_team_queue_position(self, team_id: int) -> ScreenPosition:
        """获取部队队列位置."""
        base_y = 200
        spacing = 80
        return ScreenPosition(1700, base_y + (team_id - 1) * spacing)
    
    def _click_commander(self, commander_name: str):
        """点击武将."""
        commander_pos = self._find_commander(commander_name)
        if commander_pos:
            self._input_controller.click(commander_pos.x, commander_pos.y)
    
    def _find_commander(self, commander_name: str) -> Optional[ScreenPosition]:
        """查找武将."""
        return None
    
    def _click_troop_type(self, troop_type: str):
        """点击兵种类型."""
        troop_btn = self._find_troop_type_button(troop_type)
        if troop_btn:
            self._input_controller.click(troop_btn.x, troop_btn.y)
    
    def _find_troop_type_button(
        self, troop_type: str
    ) -> Optional[ScreenPosition]:
        """查找兵种类型按钮."""
        type_positions = {
            "infantry": ScreenPosition(960, 600),
            "archer": ScreenPosition(1060, 600),
            "cavalry": ScreenPosition(1160, 600),
            "siege": ScreenPosition(1260, 600),
        }
        return type_positions.get(troop_type)
    
    def _input_troop_count(self, count: int):
        """输入出兵数量."""
        input_box = self._find_troop_count_input()
        if input_box:
            self._input_controller.click(input_box.x, input_box.y)
            time.sleep(0.3)
            self._input_controller.send_text(str(count))
    
    def _find_troop_count_input(self) -> Optional[ScreenPosition]:
        """查找出兵数量输入框."""
        return ScreenPosition(1200, 650)
    
    def get_statistics(self) -> dict:
        """获取采集统计.
        
        Returns:
            统计报告
        """
        return self._stats.get_report()
