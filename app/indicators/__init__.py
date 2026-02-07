"""
Plugin-based indicator system: discover modules from indicators/ and expose id, display_name, compute(), etc.
"""
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.indicators.base import IndicatorBase

logger = logging.getLogger(__name__)

# In-package indicators (no need to scan filesystem for default set)
from app.indicators.base import IndicatorBase
from app.indicators.vol_of_vol import VolOfVol

BUILTIN_INDICATORS: List[type["IndicatorBase"]] = [
    VolOfVol,
]


def discover_indicators(indicators_dir: Optional[str] = None) -> List[type["IndicatorBase"]]:
    """
    Return list of indicator classes: built-in + any from indicators_dir that implement IndicatorBase.
    """
    result: List[type["IndicatorBase"]] = list(BUILTIN_INDICATORS)
    if not indicators_dir or not os.path.isdir(indicators_dir):
        return result
    for name in os.listdir(indicators_dir):
        if name.startswith("_") or not name.endswith(".py"):
            continue
        path = os.path.join(indicators_dir, name)
        if not os.path.isfile(path):
            continue
        mod_name = name[:-3]
        try:
            spec = importlib.util.spec_from_file_location(f"indicator_{mod_name}", path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for attr in dir(mod):
                cls = getattr(mod, attr)
                if (
                    isinstance(cls, type)
                    and issubclass(cls, IndicatorBase)
                    and cls is not IndicatorBase
                ):
                    result.append(cls)
                    break
        except Exception as e:
            logger.warning("Failed to load indicator %s: %s", path, e)
    return result
