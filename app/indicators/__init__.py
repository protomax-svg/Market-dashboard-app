"""
Plugin-based indicator system: discover modules from indicators/ and custom_indicators/.
Supports hot reload: re-scan and reload already-imported plugin modules.
"""
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from app.indicators.base import IndicatorBase

logger = logging.getLogger(__name__)

# In-package indicators (never reloaded)
from app.indicators.base import IndicatorBase
from app.indicators.perm_entropy import PermutationEntropy
from app.indicators.vol_of_vol import VolOfVol

BUILTIN_INDICATORS: List[type["IndicatorBase"]] = [
    VolOfVol,
    PermutationEntropy,
]

# Path -> module for plugin files (so we can reload them)
_plugin_module_by_path: Dict[str, Any] = {}


def _load_module_from_file(path: str, module_name: str, reload: bool) -> Optional[Any]:
    """Load or reload a Python module from path. Returns module or None on error."""
    path = os.path.normpath(path)
    if reload and path in _plugin_module_by_path:
        try:
            mod = _plugin_module_by_path[path]
            importlib.reload(mod)
            return mod
        except Exception:
            # Reload failed; remove and fall through to full load
            _plugin_module_by_path.pop(path, None)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        _plugin_module_by_path[path] = mod
        return mod
    except Exception:
        raise


def _find_indicator_class_in_module(mod: Any) -> Optional[type["IndicatorBase"]]:
    """Return the single IndicatorBase subclass from module, or None."""
    found: Optional[type["IndicatorBase"]] = None
    for attr in dir(mod):
        try:
            cls = getattr(mod, attr)
            if (
                isinstance(cls, type)
                and issubclass(cls, IndicatorBase)
                and cls is not IndicatorBase
            ):
                if found is not None:
                    return None  # multiple classes, ambiguous
                found = cls
        except (TypeError, AttributeError):
            continue
    return found


def _validate_indicator(cls: type["IndicatorBase"]) -> bool:
    """Check required fields and compute method exist."""
    if not getattr(cls, "id", None) or not getattr(cls, "display_name", None):
        return False
    if not hasattr(cls, "required_inputs") or not hasattr(cls, "parameters"):
        return False
    if not hasattr(cls, "compute") or not callable(getattr(cls, "compute")):
        return False
    return True


def _discover_from_dir(
    dir_path: str,
    prefix: str,
    reload_plugins: bool,
    errors: List[str],
) -> List[type["IndicatorBase"]]:
    result: List[type["IndicatorBase"]] = []
    if not dir_path or not os.path.isdir(dir_path):
        return result
    for name in sorted(os.listdir(dir_path)):
        if name.startswith("_") or not name.endswith(".py"):
            continue
        path = os.path.join(dir_path, name)
        if not os.path.isfile(path):
            continue
        mod_name = prefix + name[:-3].replace(".", "_")
        try:
            mod = _load_module_from_file(path, mod_name, reload_plugins)
            if mod is None:
                continue
            cls = _find_indicator_class_in_module(mod)
            if cls is None:
                errors.append(f"{path}: no single IndicatorBase subclass found")
                continue
            if not _validate_indicator(cls):
                errors.append(f"{path}: invalid contract (id, display_name, required_inputs, parameters, compute)")
                continue
            result.append(cls)
        except Exception as e:
            msg = f"{path}: {e}"
            errors.append(msg)
            logger.exception("Failed to load indicator %s", path)
    return result


def discover_indicators(
    indicators_dir: Optional[str] = None,
    custom_indicators_dir: Optional[str] = None,
    composite_indicators_dir: Optional[str] = None,
    reload_plugins: bool = False,
) -> Tuple[List[type["IndicatorBase"]], List[str]]:
    """
    Discover indicator classes from built-ins + project indicators/ + composite/ + custom_indicators/.
    - indicators_dir: <project_root>/indicators/
    - custom_indicators_dir: <storage_path>/custom_indicators/
    - composite_indicators_dir: <project_root>/indicators/composite/ (indicators that use only other indicators' data)
    - reload_plugins: if True, use importlib.reload() for previously loaded plugin modules.
    Returns (list of indicator classes, list of error messages).
    """
    errors: List[str] = []
    result: List[type["IndicatorBase"]] = list(BUILTIN_INDICATORS)

    # Project indicators (unique module names to avoid clashes with custom)
    project = _discover_from_dir(
        indicators_dir,
        "indicator_project_",
        reload_plugins,
        errors,
    )
    result.extend(project)

    # Composite indicators (use data from other indicators only; no candles)
    composite = _discover_from_dir(
        composite_indicators_dir,
        "indicator_composite_",
        reload_plugins,
        errors,
    )
    result.extend(composite)

    # Custom indicators
    custom = _discover_from_dir(
        custom_indicators_dir,
        "indicator_custom_",
        reload_plugins,
        errors,
    )
    result.extend(custom)

    return (result, errors)
