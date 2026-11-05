"""Stand-ins for the ``requests`` module in the datasheet download tests."""
from types import SimpleNamespace


class _FakeSession:
    def __init__(self, get):
        self.get = get

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


def fake_requests(get, **attrs):
    """A ``requests`` stand-in whose module-level ``get`` and every ``Session().get`` call
    ``get(url, **kwargs)``."""
    return SimpleNamespace(get=get, Session=lambda: _FakeSession(get), **attrs)
