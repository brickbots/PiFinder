"""Tests for PiFinder.lazy_import."""

import importlib.util
import sys
import types

import pytest

from PiFinder.lazy_import import lazy_function, lazy_module, preload

FAKE_NAME = "_pifinder_lazy_fake"


@pytest.fixture
def fake_module(monkeypatch):
    """A module that records when it loads, found through sys.meta_path."""
    loads = []

    class _Finder:
        def find_spec(self, name, path=None, target=None):
            if name != FAKE_NAME:
                return None
            return importlib.util.spec_from_loader(name, _Loader())

    class _Loader:
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            loads.append(module.__name__)
            module.value = 42
            module.double = lambda x: 2 * x

    monkeypatch.setattr(sys, "meta_path", [_Finder(), *sys.meta_path])
    monkeypatch.delitem(sys.modules, FAKE_NAME, raising=False)
    yield loads
    sys.modules.pop(FAKE_NAME, None)


@pytest.mark.unit
def test_lazy_module_loads_on_first_attribute_access(fake_module):
    mod = lazy_module(FAKE_NAME)
    assert isinstance(mod, types.ModuleType)
    assert fake_module == []
    assert mod.value == 42
    assert fake_module == [FAKE_NAME]
    assert mod.double(3) == 6
    assert fake_module == [FAKE_NAME]


@pytest.mark.unit
def test_lazy_module_setattr_reaches_the_real_module(fake_module, monkeypatch):
    mod = lazy_module(FAKE_NAME)
    monkeypatch.setattr(mod, "value", 7)
    assert sys.modules[FAKE_NAME].value == 7
    assert mod.value == 7
    monkeypatch.undo()
    assert sys.modules[FAKE_NAME].value == 42


@pytest.mark.unit
def test_lazy_function_loads_when_called(fake_module):
    double = lazy_function(FAKE_NAME, "double")
    assert fake_module == []
    assert double(5) == 10
    assert fake_module == [FAKE_NAME]


@pytest.mark.unit
def test_preload_loads_in_background_and_survives_a_bad_name(fake_module):
    thread = preload(["_pifinder_no_such_module", FAKE_NAME])
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert fake_module == [FAKE_NAME]
