# Type stubs for cyminhook

class MinHook:
    def __init__(self, *, signature=None, target=None, detour=None):
        ...

    def close(self):
        """Close the hook. Removing it."""

    def enable(self):
        """Enable the hook."""

    def disable(self):
        """Disable the hook."""

def queue_enable(hook: MinHook) -> None:
    """Queue to enable an already created hook."""

def queue_disable(hook: MinHook) -> None:
    """Queue to disable an already created hook."""

def apply_queued() -> None:
    """Apply all queued changes in one go."""
