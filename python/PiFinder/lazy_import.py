"""
Keep heavy modules off the startup path.

``lazy_module()`` gives a module that loads on its first attribute access.
``lazy_function()`` gives a process target that loads its module in the
child, so the parent never loads it. ``preload()`` loads modules in a
background thread, so they are ready before the user needs them.

Start ``preload()`` only after the last ``multiprocessing`` fork. A fork while
a thread holds an import lock can deadlock the child.
"""

import importlib
import logging
import threading
import time
import types
from typing import Any, Callable, Iterable

logger = logging.getLogger("LazyImport")


class _LazyModule(types.ModuleType):
    """A module that loads on its first attribute access."""

    def _load(self) -> types.ModuleType:
        return importlib.import_module(self.__name__)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._load(), attr)

    def __setattr__(self, attr: str, value: Any) -> None:
        setattr(self._load(), attr, value)

    def __delattr__(self, attr: str) -> None:
        delattr(self._load(), attr)


def lazy_module(name: str) -> Any:
    """Return a stand-in for module ``name`` that loads on first use."""
    return _LazyModule(name)


def lazy_function(module_name: str, func_name: str) -> Callable[..., Any]:
    """Return a function that loads ``module_name`` and calls ``func_name``."""

    def _call(*args: Any, **kwargs: Any) -> Any:
        module = importlib.import_module(module_name)
        return getattr(module, func_name)(*args, **kwargs)

    _call.__name__ = func_name
    _call.__qualname__ = f"{module_name}.{func_name}"
    return _call


def preload(names: Iterable[str]) -> threading.Thread:
    """Load the modules ``names`` in a background thread."""
    names = list(names)

    def _run() -> None:
        for name in names:
            start = time.monotonic()
            try:
                importlib.import_module(name)
            except Exception:
                logger.exception("Preload of %s failed", name)
                continue
            logger.info("Preloaded %s in %.2fs", name, time.monotonic() - start)

    thread = threading.Thread(target=_run, name="Preload", daemon=True)
    thread.start()
    return thread
