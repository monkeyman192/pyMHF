from concurrent.futures import ThreadPoolExecutor

# TODO: Move somewhere else? Not sure where but this doesn't really fit here...
executor: ThreadPoolExecutor = None  # type: ignore
