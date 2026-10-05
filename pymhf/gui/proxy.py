from logging import getLogger

logger = getLogger(__name__)


class _GUIProxy:
    """Proxy GUI class so that if the GUI isn't loaded calling methods or attributes on it does nothing."""

    def __call__(self, *args, **kwargs):
        logger.warning(f"No GUI - Method called with {args} and {kwargs}")
        return _GUIProxy()

    def __getattr__(self, name: str):
        logger.warning(f"No GUI - attribute called {name}")
        return _GUIProxy()
