# -*- coding: utf-8 -*-
"""
云盘适配器模块
支持多网盘的统一接口（当前仅夸克 / 天翼）
"""

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter
from app.extensions.adapters.quark_adapter import QuarkAdapter
from app.extensions.adapters.cloud189_adapter import Cloud189Adapter
from app.extensions.adapters.adapter_factory import AdapterFactory, AccountManager

__all__ = [
    "BaseCloudDriveAdapter",
    "QuarkAdapter",
    "Cloud189Adapter",
    "AdapterFactory",
    "AccountManager",
]

__version__ = "1.2.0"
