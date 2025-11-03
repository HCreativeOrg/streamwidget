import flask
import websockets
import abc
import asyncio
import json
import inspect
import textwrap
from dataclasses import dataclass
from typing import Dict, Any, Optional, Callable, Awaitable, TypedDict

@dataclass
class Event:
    name: str
    data: Dict[str, Any]

class Builtin(abc.ABC):
    def __init__(self, server):
        self.server = server

    def c2s(self, event_name):
        def decorator(func):
            if not hasattr(self.server, '_pending_c2s'):
                self.server._pending_c2s = []
            self.server._pending_c2s.append((event_name, func))
            return func
        return decorator

    def s2c(self, event_name):
        def decorator(func):
            self.server.s2c_listeners[event_name] = func
            return func
        return decorator

    @abc.abstractmethod
    def register(self, server):
        pass

class Attributes(dict):
    def _add_style(self, css):
        if 'style' not in self:
            self['style'] = ''
        self['style'] += css + '; '
    
    def mime(self, value):
        self['type'] = value
        return self
    
    def bg(self, value):
        self._add_style(f'background: {value}')
        return self
    
    def fg(self, value):
        self._add_style(f'color: {value}')
        return self
    
    def font(self, value):
        self._add_style(f'font-family: {value}')
        return self
    
    def font_size(self, value):
        self._add_style(f'font-size: {value}px')
        return self
    
    def font_weight(self, value):
        self._add_style(f'font-weight: {value}')
        return self
    
    def border(self, value):
        self._add_style(f'border: {value["width"]} {value["style"]} {value["color"]}')
        return self
    
    def padding(self, value):
        self._add_style(f'padding: {value}px')
        return self
    
    def margin(self, value):
        self._add_style(f'margin: {value}px')
        return self
    
    def corners(self, value):
        self._add_style(f'border-radius: {value}px')
        return self
    
    def shadow(self, value):
        self._add_style(f'box-shadow: {value["offset"][0]} {value["offset"][1]} {value["blur"]} {value["color"]}')
        return self
    
    def flex(self, value):
        if value == "center":
            self._add_style('display: flex; justify-content: center; align-items: center')
        else:
            self._add_style('display: flex')
        return self
    
    def fg_shadow(self, value):
        self._add_style(f'text-shadow: {value["offset"][0]} {value["offset"][1]} {value["blur"]} {value["color"]}')
        return self
    
    def text(self, value):
        self._add_style(f'text-align: {value}')
        return self
    
    def dims(self, value):
        self._add_style(f'width: {value["width"]}px; height: {value["height"]}px')
        return self
    
    def pos(self, value):
        self._add_style(f'position: absolute; top: {value["top"]}px; left: {value["left"]}px')
        return self
    
    def custom(self, key, value):
        if key == 'style':
            self._add_style(value.rstrip(';'))
        else:
            self[key] = value
        return self

class Widget(abc.ABC):
    attrs: Attributes | None = None

    def __init__(self, root_tag='div', server=None):
        self.attrs = Attributes()
        self.element = Element(root_tag)
        self.name = None
        if server is not None:
            self.server = server

    def c2s(self, event_name):
        def decorator(func):
            if not hasattr(self.server, '_pending_c2s'):
                self.server._pending_c2s = []
            self.server._pending_c2s.append((event_name, func))
            return func
        return decorator

    def s2c(self, event_name):
        def decorator(func):
            self.server.s2c_listeners[event_name] = func
            return func
        return decorator

    @abc.abstractmethod
    def build(self):
        return self.element

    def render(self):
        root = self.build()
        root.attrs.custom('id', self.name)
        html = root.render()
        event_js = f"""
        <script>
        let ws;
        let pingInterval;
        let reconnectTimeout;

        function connect() {{
            ws = new WebSocket('ws://{self.server.host}:{self.server.port + 1}');
            ws.onopen = function() {{
                clearTimeout(reconnectTimeout);
                pingInterval = setInterval(() => {{
                    sendEvent('ping', {{}});
                }}, 30000);
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
                    // Live update handlers
                    if (eventName === 'update' && eventData.widget === 'counter') {{
                        const counterDiv = document.getElementById('counter');
                        if (counterDiv) {{
                            counterDiv.textContent = `Count: ${{eventData.count}}`;
                        }}
                    }}
                    if (eventName === 'chat_message') {{
                        const chatDiv = document.getElementById('chat-messages');
                        if (chatDiv) {{
                            const msgDiv = document.createElement('div');
                            msgDiv.textContent = `${{eventData.user}}: ${{eventData.message}}`;
                            msgDiv.style.opacity = '0';
                            msgDiv.style.transform = 'translateY(20px)';
                            chatDiv.appendChild(msgDiv);
                            setTimeout(() => {{
                                msgDiv.style.transition = 'all 0.5s';
                                msgDiv.style.opacity = '1';
                                msgDiv.style.transform = 'translateY(0)';
                            }}, 10);
                            if (chatDiv.children.length > 50) {{
                                chatDiv.removeChild(chatDiv.firstChild);
                            }}
                        }}
                    }}
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
            }}
        }};
        </script>
        """
        client_code = []
        if hasattr(self, '__class__'):
            for name in dir(self.__class__):
                attr = getattr(self.__class__, name)
                if hasattr(attr, '__client_event__'):
                    event = attr.__client_event__
                    source = inspect.getsource(attr)
                    lines = source.split('\n')

                    def_idx = next((i for i, line in enumerate(lines) if line.strip().startswith('def ')), 0)

                    code_lines = lines[def_idx:]

                    code = textwrap.dedent('\n'.join(code_lines))
                    client_code.append(f"""
from browser import *
from browser import window
{code}
window.server.on('{event}', {attr.__name__})
""")
        for name in dir(self):
            attr = getattr(self, name)
            if hasattr(attr, '__client_event__'):
                event = attr.__client_event__
                source = inspect.getsource(attr)
                lines = source.split('\n')

                def_idx = next((i for i, line in enumerate(lines) if line.strip().startswith('def ')), 0)

                code_lines = lines[def_idx:]

                code = textwrap.dedent('\n'.join(code_lines))
                client_code.append(f"""
from browser import *
from browser import window
{code}
window.server.on('{event}', {attr.__name__})
""")
        if client_code:
            python_script = f'<script type="text/python">{"".join(client_code)}</script>'
        else:
            python_script = ''
        return html + event_js + python_script

def client(event_name):
    def decorator(func):
        func.__client_event__ = event_name
        return func
    return decorator

class Element:
    def __init__(self, tag, content=None, attrs=None):
        self.tag = tag
        self.content = content or []
        self.attrs = attrs or Attributes()
    
    def render(self):
        if isinstance(self.content, str):
            inner = self.content
        elif isinstance(self.content, list):
            inner = ''.join([c.render() if hasattr(c, 'render') else str(c) for c in self.content])
        else:
            inner = str(self.content)
        attr_str = ' '.join([f'{key}="{value}"' for key, value in self.attrs.items()])
        return f'<{self.tag} {attr_str}>{inner}</{self.tag}>'

def element(tag: str) -> Callable[..., Element]:
    def element_function(content=None, attrs=None) -> Element:
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
a = element('a')

class Server:
    def __init__(self, host='127.0.0.1', port=5001):
        self.host = host
        self.port = port
        self.s2c_events = {}
        self.c2s_listeners = {}
        self.c2s_events = {}
        self.s2c_listeners = {}
        self._pending_c2s = []
        self.widgets = {}
        self.connected_clients = set()
        self.trigger_event = self.dispatch_s2c
        self.loop = None
    
    def c2s(self, event_name):
        def decorator(func):
            if not hasattr(self, '_pending_c2s'):
                self._pending_c2s = []
            self._pending_c2s.append((event_name, func))
            return func
        return decorator

    def s2c(self, event_name):
        def decorator(func):
            self.s2c_listeners[event_name] = func
            return func
        return decorator

    def widget(self, widget_name, root_tag='div'):
        def decorator(cls):
            def __init__(self, *args, **kwargs):
                Widget.__init__(self, root_tag, self)
                self.initialize()
            cls.__init__ = __init__
            instance = cls()
            instance.name = widget_name
            instance.server = self
            self.widgets[widget_name] = instance
            # bind pending c2s
            for event_name, func in getattr(self, '_pending_c2s', []):
                bound_func = getattr(instance, func.__name__, None)
                if bound_func:
                    self.c2s_listeners[event_name] = bound_func
            if hasattr(self, '_pending_c2s'):
                self._pending_c2s.clear()
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
            # bind pending c2s
            for event_name, func in getattr(self, '_pending_c2s', []):
                bound_func = getattr(instance, func.__name__, None)
                if bound_func:
                    self.c2s_listeners[event_name] = bound_func
            if hasattr(self, '_pending_c2s'):
                self._pending_c2s.clear()
            return cls
        else:
            raise TypeError("builtin takes at most 1 argument")
    
    async def ws_handler(self, websocket):
        self.connected_clients.add(websocket)
        try:
            async for message in websocket:
                data = json.loads(message)
                event_name = data.get('event')
                event_data = data.get('data', {})
                if event_name == 'ping':
                    await websocket.send(json.dumps({'event': 'pong'}))
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
    
    def send_event(self, event_name: str, data: Dict[str, Any]) -> None:
        event = {'event': event_name, 'data': data}
        message = json.dumps(event)
        for client in self.connected_clients.copy():
            if self.loop:
                self.loop.call_soon_threadsafe(lambda c=client, m=message: asyncio.create_task(c.send(m)))
            else:
                asyncio.create_task(client.send(message))
    
    def dispatch_s2c(self, event_name: str, data: Dict[str, Any]) -> None:
        if event_name in self.s2c_listeners:
            result = self.s2c_listeners[event_name](data)
            if result is not None:
                data = result
        self.send_event(event_name, data)
    
    def dispatch_c2s(self, event_name: str, data: Dict[str, Any]) -> None:
        if event_name in self.c2s_listeners:
            coro = self.c2s_listeners[event_name](data, None)
            if self.loop:
                self.loop.call_soon_threadsafe(lambda: asyncio.create_task(coro))
            else:
                asyncio.create_task(coro)
    
    def generate_event_js(self):
        js = f"""
        <script>
        let ws;
        let pingInterval;
        let reconnectTimeout;

        function connect() {{
            ws = new WebSocket('ws://{self.host}:{self.port + 1}');
            ws.onopen = function() {{
                clearTimeout(reconnectTimeout);
                pingInterval = setInterval(() => {{
                    sendEvent('ping', {{}});
                }}, 30000);
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
        """
        return js
    
    def run(self):
        import asyncio
        import threading
        
        app = flask.Flask(__name__)

        @app.route('/widget/<widget_name>')
        def widget_route(widget_name):
            widget = self.widgets.get(widget_name)
            if widget:
                return widget.render()
            return "Widget not found", 404

        @app.route('/events')
        def events_page():
            return self.generate_event_js()

        def run_flask():
            app.run(host=self.host, port=self.port, debug=False)

        def run_ws():
            async def _run():
                self.loop = asyncio.get_running_loop()
                server = await websockets.serve(self.ws_handler, self.host, self.port + 1)
                await server.serve_forever()
            asyncio.run(_run())

        threading.Thread(target=run_flask, daemon=True).start()
        threading.Thread(target=run_ws, daemon=True).start()

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