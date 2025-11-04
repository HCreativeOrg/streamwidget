import flask
import websockets
import abc
import asyncio
import json
import inspect
import textwrap
import threading
import re
import ast
from dataclasses import dataclass
from typing import Dict, Any, Optional, Callable, Awaitable, Union, List, Set, Tuple

@dataclass
class Event:
    name: str
    data: Dict[str, Any]

class Builtin(abc.ABC):
    def __init__(self, server: 'Server') -> None:
        self.server = server

    def c2s(self, event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if not hasattr(self.server, '_pending_c2s'):
                self.server._pending_c2s = []
            self.server._pending_c2s.append((event_name, func))
            return func
        return decorator

    def s2c(self, event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.server.s2c_listeners[event_name] = func
            return func
        return decorator

    @abc.abstractmethod
    def register(self, server: 'Server') -> None:
        pass

class Attributes(dict):
    def _add_style(self, css: str) -> None:
        if 'style' not in self:
            self['style'] = ''
        self['style'] += css + '; '
    
    def mime(self, value: str) -> 'Attributes':
        self['type'] = value
        return self
    
    def bg(self, value: str) -> 'Attributes':
        self._add_style(f'background: {value}')
        return self
    
    def fg(self, value: str) -> 'Attributes':
        self._add_style(f'color: {value}')
        return self
    
    def font(self, value: str) -> 'Attributes':
        self._add_style(f'font-family: {value}')
        return self
    
    def font_size(self, value: int) -> 'Attributes':
        self._add_style(f'font-size: {value}px')
        return self
    
    def font_weight(self, value: str) -> 'Attributes':
        self._add_style(f'font-weight: {value}')
        return self
    
    def border(self, value: Dict[str, str]) -> 'Attributes':
        self._add_style(f'border: {value["width"]} {value["style"]} {value["color"]}')
        return self
    
    def padding(self, value: int) -> 'Attributes':
        self._add_style(f'padding: {value}px')
        return self
    
    def margin(self, value: int) -> 'Attributes':
        self._add_style(f'margin: {value}px')
        return self
    
    def corners(self, value: Dict[str, Any]) -> 'Attributes':
        self._add_style('border-radius: ' + (f"{value['top'][0]} {value['top'][1]} {value['bottom'][0]} {value['bottom'][1]}" if not value.get("all") else value["all"]))
        return self
    
    def shadow(self, value: Dict[str, Any]) -> 'Attributes':
        self._add_style(f'box-shadow: {value["offset"][0]} {value["offset"][1]} {value["blur"]} {value["color"]}')
        return self
    
    def flex(self, value: str) -> 'Attributes':
        if value == "center":
            self._add_style('display: flex; justify-content: center; align-items: center')
        else:
            self._add_style('display: flex')
        return self
    
    def fg_shadow(self, value: Dict[str, Any]) -> 'Attributes':
        self._add_style(f'text-shadow: {value["offset"][0]} {value["offset"][1]} {value["blur"]} {value["color"]}')
        return self
    
    def text(self, value: str) -> 'Attributes':
        self._add_style(f'text-align: {value}')
        return self
    
    def dims(self, value: Dict[str, int]) -> 'Attributes':
        self._add_style(f'width: {value["width"]}px; height: {value["height"]}px')
        return self
    
    def pos(self, value: Dict[str, int]) -> 'Attributes':
        self._add_style(f'position: absolute; top: {value["top"]}px; left: {value["left"]}px')
        return self

    def on_click(self, event_name: str) -> 'Attributes':
        """Register a client-side click event"""
        self['data-on-click'] = event_name
        return self

    def on_mouseover(self, event_name: str) -> 'Attributes':
        """Register a client-side mouseover event"""
        self['data-on-mouseover'] = event_name
        return self

    def on_mouseout(self, event_name: str) -> 'Attributes':
        """Register a client-side mouseout event"""
        self['data-on-mouseout'] = event_name
        return self

    def on_dblclick(self, event_name: str) -> 'Attributes':
        """Register a client-side double-click event"""
        self['data-on-dblclick'] = event_name
        return self

    def on_input(self, event_name: str) -> 'Attributes':
        """Register a client-side input event"""
        self['data-on-input'] = event_name
        return self

    def custom(self, key: str, value: Any) -> 'Attributes':
        if key == 'style':
            self._add_style(value.rstrip(';'))
        else:
            self[key] = value
        return self

class Widget(abc.ABC):
    attrs: Attributes = Attributes()

    def __init__(self, root_tag: str = 'div', server: Optional['Server'] = None) -> None:
        self.attrs = Attributes()
        self.element = Element(root_tag)
        self.name: Optional[str] = None
        if server is not None:
            self.server = server

    def c2s(self, event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            setattr(func, '__c2s_event__', event_name)
            return func
        return decorator

    def s2c(self, event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.server.s2c_listeners[event_name] = func
            return func
        return decorator

    @abc.abstractmethod
    def build(self) -> 'Element':
        return self.element

    def render(self) -> str:
        root = self.build()
        root.attrs.custom('id', self.name)
        html = root.render()
        event_js = f"""
        <script>
        let ws;
        let pingInterval;
        let reconnectTimeout;
        let wsListeners = [];

        window.on_ws_open = function(listener) {{
            wsListeners.push(listener);
        }};

        function connect() {{
            ws = new WebSocket('ws://{self.server.client_host}:{self.server.ws_port}');
            ws.onopen = function() {{
                clearTimeout(reconnectTimeout);
                pingInterval = setInterval(() => {{
                    sendEvent('ping', {{}});
                }}, 30000);

                wsListeners.forEach(listener => listener());
            }};
            ws.onmessage = function(event) {{
                const data = JSON.parse(event.data);
                const eventName = data.event;
                const eventData = data.data;
                const id = data.id;
                if (id) {{
                    const req = pendingRequests[id];
                    if (req) {{
                        clearTimeout(req.timeout);
                        delete pendingRequests[id];
                        req.resolve(eventData);
                    }}
                }} else {{
                    window.dispatchEvent(new CustomEvent(eventName, {{ detail: eventData }}));
                }}
            }};
            ws.onclose = function() {{
                clearInterval(pingInterval);
                reconnectTimeout = setTimeout(connect, 1000);
            }};
            ws.onerror = function() {{
                ws.close();
            }};
        }}

        connect();

        const pendingRequests = {{}};
        let requestId = 0;
        function sendEvent(eventName, data) {{
            if (ws.readyState === WebSocket.OPEN) {{
                const id = ++requestId;
                return new Promise((resolve, reject) => {{
                    const timeout = setTimeout(() => {{
                        delete pendingRequests[id];
                        reject(new Error('Request timeout'));
                    }}, 5000);
                    pendingRequests[id] = {{ resolve, reject, timeout }};
                    ws.send(JSON.stringify({{ event: eventName, data: data, id: id }}));
                }});
            }} else {{
                return Promise.reject(new Error('WebSocket not connected'));
            }}
        }}
        </script>
        <script src="https://cdn.jsdelivr.net/npm/brython@latest/brython.min.js"></script>
        <script>
        brython();
        window.server = {{
            send: sendEvent,
            on: function(event, callback) {{
                window.addEventListener(event, (e) => callback(e.detail));
            }},
            emit: function(event, data) {{
                return sendEvent(event, data || {{}});
            }},
            listeners: {{}},
            widget: {{
                onElementEvent: function(elemId, eventType, handler) {{
                    const elem = document.getElementById(elemId);
                    if (elem) {{
                        const eventMap = {{
                            'click': 'data-on-click',
                            'mouseover': 'data-on-mouseover',
                            'mouseout': 'data-on-mouseout',
                            'dblclick': 'data-on-dblclick',
                            'input': 'data-on-input'
                        }};
                        const attrName = eventMap[eventType];
                        if (attrName) {{
                            elem.addEventListener(eventType, async (e) => {{
                                const eventName = elem.getAttribute(attrName);
                                if (eventName) {{
                                    try {{
                                        const response = await sendEvent(eventName, {{
                                            elementId: elemId,
                                            value: e.target.value || null,
                                            type: eventType,
                                            clientX: e.clientX,
                                            clientY: e.clientY
                                        }});
                                        if (handler) {{
                                            handler(response);
                                        }}
                                    }} catch (err) {{
                                        console.error('Event handler error:', err);
                                    }}
                                }}
                            }});
                        }}
                    }}
                }},
                attachHandlers: function(widgetId) {{
                    const widget = document.getElementById(widgetId);
                    if (widget) {{
                        const eventTypes = ['click', 'mouseover', 'mouseout', 'dblclick', 'input'];
                        const elements = [widget, ...widget.querySelectorAll('[data-on-click], [data-on-mouseover], [data-on-mouseout], [data-on-dblclick], [data-on-input]')];
                        elements.forEach(elem => {{
                            eventTypes.forEach(eventType => {{
                                if (elem.hasAttribute('data-on-' + eventType)) {{
                                    elem.addEventListener(eventType, async (e) => {{
                                        const eventName = elem.getAttribute('data-on-' + eventType);
                                        try {{
                                            const response = await sendEvent(eventName, {{
                                                elementId: elem.id || widgetId,
                                                value: e.target.value || null,
                                                type: eventType,
                                                clientX: e.clientX,
                                                clientY: e.clientY
                                            }});
                                            window.dispatchEvent(new CustomEvent(eventName + '_response', {{ detail: response }}));
                                        }} catch (err) {{
                                            console.error('Event error:', err);
                                        }}
                                    }});
                                }}
                            }});
                        }});
                    }}
                }}
            }}
        }};
        window.server.widget.attachHandlers('{self.name}');
        const observer = new MutationObserver((mutations) => {{
            mutations.forEach((mutation) => {{
                mutation.addedNodes.forEach((node) => {{
                    if (node.nodeType === Node.ELEMENT_NODE) {{
                        const elements = [node, ...node.querySelectorAll('[data-on-click], [data-on-mouseover], [data-on-mouseout], [data-on-dblclick], [data-on-input]')];
                        elements.forEach(elem => {{
                            if (elem.hasAttribute && (elem.hasAttribute('data-on-click') || elem.hasAttribute('data-on-mouseover') || elem.hasAttribute('data-on-mouseout') || elem.hasAttribute('data-on-dblclick') || elem.hasAttribute('data-on-input'))) {{
                                const eventTypes = ['click', 'mouseover', 'mouseout', 'dblclick', 'input'];
                                eventTypes.forEach(eventType => {{
                                    if (elem.hasAttribute('data-on-' + eventType)) {{
                                        elem.addEventListener(eventType, async (e) => {{
                                            const eventName = elem.getAttribute('data-on-' + eventType);
                                            try {{
                                                const response = await sendEvent(eventName, {{
                                                    elementId: elem.id || '{self.name}',
                                                    value: e.target.value || null,
                                                    type: eventType,
                                                    clientX: e.clientX,
                                                    clientY: e.clientY
                                                }});
                                                window.dispatchEvent(new CustomEvent(eventName + '_response', {{ detail: response }}));
                                            }} catch (err) {{
                                                console.error('Event error:', err);
                                            }}
                                        }});
                                    }}
                                }});
                            }}
                        }});
                    }}
                }});
            }});
        }});
        observer.observe(document.body, {{ childList: true, subtree: true }});
        </script>
        """
        client_code = []
        for name in dir(self):
            attr = getattr(self, name)
            if hasattr(attr, '__client_event__'):
                event = attr.__client_event__
                source = inspect.getsource(attr)
                lines = source.split('\n')
                def_idx = next((i for i, line in enumerate(lines) if line.strip().startswith('def ')), 0)
                func_source = textwrap.dedent('\n'.join(lines[def_idx:]))
                func = ast.parse(func_source)
                func_def = func.body[0]
                if isinstance(func_def, ast.FunctionDef):
                    func_def.args.args = [arg for arg in func_def.args.args if arg.arg not in ('self', 'browser', 'document', 'window')]
                    func_def.body.insert(0, ast.parse("data = dict(data)").body[0])
                code = ast.unparse(func)
                client_code.append(f"""
import browser
from browser import *
from browser import window

async def send_event(event_name, data):
    return await window.server.send(event_name, data)

{code}
window.server.on('{event}', {attr.__name__})
""")
        if client_code:
            python_script = f'<script type="text/python">{"".join(client_code)}</script>'
        else:
            python_script = ''
        return html + event_js + python_script

def client(event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, '__client_event__', event_name)
        return func
    return decorator

def c2s(event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, '__c2s_event__', event_name)
        return func
    return decorator

class Element:
    def __init__(self, tag: str, content: Optional[Union[str, List[Union[str, 'Element']]]] = None, attrs: Optional[Attributes] = None) -> None:
        self.tag = tag
        self.content = content or []
        if attrs is not None and not isinstance(attrs, dict):
            if isinstance(self.content, list):
                self.content.append(attrs)
            else:
                self.content = [self.content, attrs]
            attrs = None
        self.attrs = attrs or Attributes()
    
    def render(self) -> str:
        if isinstance(self.content, str):
            inner = self.content
        elif isinstance(self.content, list):
            inner = ''.join(c.render() if isinstance(c, Element) else str(c) for c in self.content)
        else:
            inner = str(self.content)
        attr_str = ' '.join(f'{key}="{value}"' for key, value in self.attrs.items())
        return f'<{self.tag} {attr_str}>{inner}</{self.tag}>'

def element(tag: str) -> Callable[..., Element]:
    def element_function(*args, **kwargs) -> Element:
        content = None
        attrs = None
        if args:
            if len(args) == 1:
                if isinstance(args[0], Attributes):
                    attrs = args[0]
                else:
                    content = args[0]
            elif len(args) == 2:
                content = args[0]
                attrs = args[1]
            else:
                content = list(args)
        if 'attrs' in kwargs:
            attrs = kwargs['attrs']
        return Element(tag, content, attrs)
    return element_function

h1 = element('h1')
h2 = element('h2')
h3 = element('h3')
h4 = element('h4')
h5 = element('h5')
h6 = element('h6')
div = element('div')
p = element('p')
span = element('span')
i = element('i')
b = element('b')
img = element('img')
button = element('button')
form = element('form')
input = element('input')
nav = element('nav')
ul = element('ul')
ol = element('ol')
li = element('li')
style = element('style')
script = element('script')
table = element('table')
thead = element('thead')
tbody = element('tbody')
tr = element('tr')
td = element('td')
th = element('th')
select = element('select')
option = element('option')
a = element('a')
def python(script: str) -> Element:
    return Element('script', script, Attributes().custom('type', 'text/python'))

class Server:
    def __init__(self, host: str = '127.0.0.1', port: int = 5001) -> None:
        self.host = host
        self.port = port
        self.ws_port = port + 1
        self.client_host = '127.0.0.1'
        self.s2c_events: Dict[str, Any] = {}
        self.c2s_listeners: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self.c2s_events: Dict[str, Any] = {}
        self.s2c_listeners: Dict[str, Callable[..., Any]] = {}
        self._pending_c2s: List[Any] = []
        self.widgets: Dict[str, Widget] = {}
        self.connected_clients: Set[Any] = set()
        self.trigger_event = self.to_client
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.event_handlers: Dict[str, List[Callable[..., Any]]] = {}  # { event_name: [handler1, handler2, ...] }
        self._s2c_queue: List[Tuple[str, Dict[str, Any]]] = []
        self.recent_events: List[Tuple[str, Dict[str, Any]]] = []
    
    def on(self, event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator to register a server event handler"""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if event_name not in self.event_handlers:
                self.event_handlers[event_name] = []
            self.event_handlers[event_name].append(func)
            return func
        return decorator
    
    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """Emit a server event to all registered handlers"""
        if event_name in self.event_handlers:
            for handler in self.event_handlers[event_name]:
                if asyncio.iscoroutinefunction(handler):
                    if self.loop:
                        asyncio.run_coroutine_threadsafe(handler(*args, **kwargs), self.loop)
                    else:
                        asyncio.create_task(handler(*args, **kwargs))
                else:
                    handler(*args, **kwargs)
    
    def c2s(self, event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if not hasattr(self, '_pending_c2s'):
                self._pending_c2s = []
            self._pending_c2s.append((event_name, func))
            return func
        return decorator

    def s2c(self, event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.s2c_listeners[event_name] = func
            return func
        return decorator

    def widget(self, widget_name: str, root_tag: str = 'div') -> Callable[[type], type]:
        def decorator(cls: type) -> type:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                Widget.__init__(self, root_tag, self)
                self.initialize()
            cls.__init__ = __init__
            instance = cls()
            instance.name = widget_name
            instance.server = self
            self.widgets[widget_name] = instance
            # Bind c2s events
            for name in dir(instance.__class__):
                attr = getattr(instance.__class__, name)
                if hasattr(attr, '__c2s_event__'):
                    event_name = attr.__c2s_event__
                    bound_method = attr.__get__(instance, instance.__class__)
                    self.c2s_listeners[event_name] = bound_method
            return cls
        return decorator
    
    def builtin(self, *args):
        if len(args) == 0:
            def decorator(cls):
                instance = cls(self)
                instance.register(self)
                for event_name, func in getattr(self, '_pending_c2s', []):
                    bound_func = getattr(instance, func.__name__, None)
                    if bound_func:
                        self.c2s_listeners[event_name] = bound_func
                if hasattr(self, '_pending_c2s'):
                    self._pending_c2s.clear()
                return cls
            return decorator
        elif len(args) == 1:
            cls = args[0]
            instance = cls(self)
            instance.register(self)
            # Bind pending c2s
            for event_name, func in getattr(self, '_pending_c2s', []):
                bound_func = getattr(instance, func.__name__, None)
                if bound_func:
                    self.c2s_listeners[event_name] = bound_func
            if hasattr(self, '_pending_c2s'):
                self._pending_c2s.clear()
            return cls
        else:
            raise TypeError("builtin takes at most 1 argument")
    
    async def ws_handler(self, websocket: Any) -> None:
        print(f"WebSocket client connected: {websocket}")
        self.connected_clients.add(websocket)
        # Send recent events to the new client
        for event_name, data in self.recent_events:
            event = {'event': event_name, 'data': data}
            message = json.dumps(event)
            await websocket.send(message)
        try:
            async for message in websocket:
                data = json.loads(message)
                event_name = data.get('event')
                event_data = data.get('data', {})
                if event_name == 'ping':
                    response = {}
                    response_event = {'event': f'{event_name}_response', 'data': response}
                    if 'id' in data:
                        response_event['id'] = data['id']
                    await websocket.send(json.dumps(response_event))
                elif event_name in self.c2s_listeners:
                    response = await self.c2s_listeners[event_name](event_data, websocket)
                    if response is not None:
                        response_event = {'event': f'{event_name}_response', 'data': response}
                        if 'id' in data:
                            response_event['id'] = data['id']
                        await websocket.send(json.dumps(response_event))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connected_clients.remove(websocket)
    
    async def send_event(self, event_name: str, data: Dict[str, Any]) -> None:
        event = {'event': event_name, 'data': data}
        message = json.dumps(event)
        for client in self.connected_clients.copy():
            asyncio.create_task(client.send(message))

    def to_client(self, event_name: str, data: Dict[str, Any], recent: bool = True) -> None:
        if recent:
            self.recent_events.append((event_name, data))
            if len(self.recent_events) > 100:
                self.recent_events.pop(0)
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.send_event(event_name, data), self.loop)
        else:
            asyncio.create_task(self.send_event(event_name, data))

    def to_server(self, event_name: str, data: Dict[str, Any]) -> None:
        if event_name in self.c2s_listeners:
            coro = self.c2s_listeners[event_name](data, None)
            if self.loop:
                asyncio.run_coroutine_threadsafe(coro, self.loop)  # type: ignore
            else:
                asyncio.create_task(coro)  # type: ignore
    
    def generate_event_js(self):
        js = f"""
        <script>
        let ws;
        let pingInterval;
        let reconnectTimeout;

        function connect() {{
            console.log('WebSocket connecting to ws://{self.client_host}:{self.ws_port}');
            ws = new WebSocket('ws://{self.client_host}:{self.ws_port}');
            ws.onopen = function() {{
                console.log('WebSocket connected');
                clearTimeout(reconnectTimeout);
                pingInterval = setInterval(() => {{
                    sendEvent('ping', {{}});
                }}, 30000);
            }};
            ws.onmessage = function(event) {{
                console.log('WebSocket message received:', event.data);
                const data = JSON.parse(event.data);
                const eventName = data.event;
                const eventData = data.data;
                const id = data.id;
                if (id) {{
                    const req = pendingRequests[id];
                    if (req) {{
                        clearTimeout(req.timeout);
                        delete pendingRequests[id];
                        req.resolve(eventData);
                    }}
                }} else {{
                    window.dispatchEvent(new CustomEvent(eventName, {{ detail: eventData }}));
                }}
            }};
            ws.onclose = function() {{
                console.log('WebSocket closed');
                clearInterval(pingInterval);
                reconnectTimeout = setTimeout(connect, 1000);
            }};
            ws.onerror = function(error) {{
                console.error('WebSocket error:', error);
                ws.close();
            }};
        }}

        connect();

        const pendingRequests = {{}};
        let requestId = 0;
        function sendEvent(eventName, data) {{
            if (ws.readyState === WebSocket.OPEN) {{
                const id = ++requestId;
                return new Promise((resolve, reject) => {{
                    const timeout = setTimeout(() => {{
                        delete pendingRequests[id];
                        reject(new Error('Request timeout'));
                    }}, 5000);
                    pendingRequests[id] = {{ resolve, reject, timeout }};
                    ws.send(JSON.stringify({{ event: eventName, data: data, id: id }}));
                }});
            }} else {{
                return Promise.reject(new Error('WebSocket not connected'));
            }}
        }}
        </script>
        """
        return js
    
    async def run(self):
        import asyncio
        
        app = flask.Flask(__name__)

        @app.route('/widget/<widget_name>')
        def widget_route(widget_name: str) -> Union[str, Tuple[str, int]]:
            widget = self.widgets.get(widget_name)
            if widget:
                return widget.render()
            return "Widget not found", 404

        @app.route('/events')
        def events_page() -> str:
            return self.generate_event_js()

        def run_flask() -> None:
            print(f"Starting Flask server on {self.host}:{self.port}")
            app.run(host=self.host, port=self.port, debug=False, threaded=True)

        async def run_ws() -> None:
            self.loop = asyncio.get_running_loop()
            for event_name, data in self._s2c_queue:
                self.to_client(event_name, data)
            self._s2c_queue.clear()
            print(f"Starting WebSocket server on {self.host}:{self.ws_port}")
            server = await websockets.serve(self.ws_handler, self.host, self.ws_port)
            await server.serve_forever()

        threading.Thread(target=run_flask, daemon=True).start()

        await run_ws()

    @staticmethod
    def thread_wait() -> None:
        asyncio.run(asyncio.sleep(float('inf')))

def test_attributes():
    attrs = Attributes()
    attrs.bg('#000000')
    attrs.fg('#FFFFFF')
    attrs.font('Arial')
    attrs.font_size(14)
    attrs.border({'width': '2px', 'style': 'solid', 'color': '#FF0000'})
    attrs.flex("center")
    assert 'background: #000000' in attrs['style']
    assert 'color: #FFFFFF' in attrs['style']
    assert 'font-family: Arial' in attrs['style']
    assert 'font-size: 14px' in attrs['style']
    assert 'border: 2px solid #FF0000' in attrs['style']
    assert 'display: flex' in attrs['style']
    assert 'justify-content: center' in attrs['style']
    assert 'align-items: center' in attrs['style']

def test_server():
    server = Server()

    @server.widget('test_widget')
    class TestWidget(Widget):
        def build(self):
            return Element('div', 'Test Widget')

def test_element_recursive():
    child = Element('span', 'Hello')
    parent = Element('div', [child, ' World'])
    html = parent.render()
    assert '<div ><span >Hello</span> World</div>' == html