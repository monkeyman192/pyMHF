import asyncio
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from logging import getLogger
from typing import Any, Callable, Literal, NamedTuple, Optional, Protocol, Type

import uvicorn
from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html

try:
    pymhf_version = version("pymhf")
except PackageNotFoundError:
    pymhf_version = "unknown"


logger = getLogger(__name__)


# Have a mapping of the names of the endpoint function and the actual function.
# We need to do this to circumvent the serialization that happens when uvicorn creates websockets.
# I think it tries to pickle the entire object which the method is bound to, which will fail because we are
# liberally using ctypes pointers which are un-pickleable.
websocket_endpoints = {}
# Router mapping. This will be used so that we can clear the router and refresh it when we reload a mod.
router_mapping: dict[str, "CleanableAPIRouter"] = {}


class EndpointData(NamedTuple):
    route: str
    method: Optional[Literal["GET", "PUT", "WEBSOCKET"]]
    dont_extend: bool


class APIEndpointProtocol(Protocol):
    """Protocol for API Endpoint objects"""

    _api_endpoint: EndpointData

    @property
    def __self__(self) -> Type: ...

    @property
    def __name__(self) -> str: ...

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


def create_app() -> FastAPI:
    app = FastAPI(version=pymhf_version, title="pyMHF API")

    # Allow CORS for all requests.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # must be False when allow_origins is "*"
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=app.title,
        )

    return app


# Create the api app.
api_app = create_app()


async def websocket_wrapper(websocket: WebSocket, func_name: str):
    await websocket.accept()
    try:
        while True:
            # Add a small sleep so that we aren't calling this literally as often as possible.
            await asyncio.sleep(0.001)
            try:
                if (callable := websocket_endpoints.get(func_name)) is not None:
                    await websocket.send_text(f"{func_name} -> {callable()}")
                else:
                    await websocket.send_text(f"Unable to find {func_name}")
            except Exception:
                # Can't keep calling the function...
                logger.exception(f"There was an error calling the function {func_name}")
                break
    except WebSocketDisconnect:
        # 4. Handle client disconnection cleanly
        logger.info("Client disconnected from stream.")


def endpoint(
    route: Optional[str] = None,
    method: Optional[Literal["GET", "PUT", "WEBSOCKET"]] = None,
    dont_extend: bool = False,
):
    """Create a HTTP endpoint for the decorated method or property.

    Parameters
    ----------
    route:
        The name of the path to serve the endpoint on.
        This will always be relative to the name of the mod this method or property belongs to.
        If not provided, it will fallback to the name of the function.
    method:
        The type of HTTP request this will be bound to.
        Note that if this is specified as "WEBSOCKET", this function will be called repeatedly, so make sure
        nothing which blocks or takes a long time to retrieve is called.
    dont_extend:
        By default, if this decorator is applied to a property, if that property also has a setter, then a
        PUT endpoint will also be generated for it. To disable this set this to True.
    """
    if method and method not in ("GET", "PUT", "WEBSOCKET"):
        raise ValueError

    def inner(func: Callable[..., Any]):
        # Set the route to be the function name if not provided and strip a leading /
        _route = route
        if _route is None:
            _route = func.__name__
        # Strip any leading `/` character and then add it back to ensure the path is valid.
        _route = f"/{_route.lstrip('/')}"
        setattr(func, "_api_endpoint", EndpointData(_route, method, dont_extend))
        return func

    return inner


class ThreadedServer:
    """Loosely wrapped version of the uvicorn Server object to facilitate running it in a thread."""

    def __init__(self, app: FastAPI, host: str, port: int):
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            log_config=None,
            use_colors=False,
        )

        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def shutdown(self):
        self.server.should_exit = True


class CleanableAPIRouter(APIRouter):
    # Thin wrapper around the APIRouter class which will have a method to remove any endpoints which may have
    # changed and re-bind them to endpoints.
    def __init__(self, mod_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Names of the subsocket function names which are associated with this router.
        # This allows us to remove them from the global lookup so they can be re-added on reload.
        self._websocket_funcnames = []
        self.mod_name = mod_name

    def clear(self):
        """Remove all existing routes."""
        _original_route_count = len(self.routes)
        self.routes = []
        # Get the names of all the websockets we have defined and delete them from the lookup.
        _original_websocket_count = len(self._websocket_funcnames)
        for ws_name in self._websocket_funcnames:
            websocket_endpoints.pop(ws_name, None)
        self._websocket_funcnames = []
        if _original_route_count > 0 or _original_websocket_count > 0:
            logger.info(
                f"Removed {_original_route_count} endpoints and {_original_websocket_count} websockets for "
                f"the mod {self.mod_name}"
            )
        # self._mark_routes_changed()

    def load_routes(self, routes: dict[str, list[APIEndpointProtocol]]):
        """Load all the routes for a mod."""
        # First clear so that we start with a blank slate.
        self.clear()
        # Then loop through each of the route types and add them to this router.
        for get_ep in routes["GET"]:
            self.add_api_route(get_ep._api_endpoint.route, get_ep)
            logger.debug(f"Registered the function {get_ep} to the endpoint {get_ep._api_endpoint.route}")
        for put_ep in routes["PUT"]:
            self.add_api_route(put_ep._api_endpoint.route, put_ep, methods=["PUT"])
            logger.debug(f"Registered the function {put_ep} to the endpoint {put_ep._api_endpoint.route}")
        for ws_ep in routes["WEBSOCKET"]:
            self.add_api_websocket_route(
                ws_ep._api_endpoint.route,
                partial(websocket_wrapper, func_name=ws_ep.__qualname__),
            )
            # Add the bound funtion to the lookup. See the documentation above this variable for the why.
            websocket_endpoints[ws_ep.__qualname__] = ws_ep
            self._websocket_funcnames.append(ws_ep.__qualname__)
        self._mark_routes_changed()
