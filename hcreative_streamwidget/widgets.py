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
    @abc.abstractmethod
    def register(self, server):
        pass

class Widget(abc.ABC):
    def __init__(self):
        self.element = Element('div')
        self.name = None

    @abc.abstractmethod
    def build(self):
        """Return the root Element of the widget"""
        pass

    def render(self):
        root = self.build()
        root.attrs.custom('id', self.name)
        html = root.render()
        event_js = f"""
        <script>
        const ws = new WebSocket('ws://{self.server.host}:{self.server.port + 1}');
        const pendingRequests = {{}};
        let requestId = 0;
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
        function sendEvent(eventName, data) {{
            const id = ++requestId;
            return new Promise((resolve, reject) => {{
                const timeout = setTimeout(() => {{
                    delete pendingRequests[id];
                    reject(new Error('Request timeout'));
                }}, 5000);
                pendingRequests[id] = {{ resolve, reject, timeout }};
                ws.send(JSON.stringify({{ event: eventName, data: data, id: id }}));
            }});
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
        if hasattr(self, 'client_python'):
            client_code.append(self.client_python())
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

class Attributes(dict):
    def mime(self, value):
        self['type'] = value
        return self
    
    def bg(self, value):
        self['background'] = value
        return self
    
    def fg(self, value):
        self['color'] = value
        return self
    
    def font(self, value):
        self['font-family'] = value
        return self
    
    def font_size(self, value):
        self['font-size'] = f'{value}px'
        return self
    
    def font_weight(self, value):
        self['font-weight'] = value
        return self
    
    def border(self, value):
        self['border'] = f'{value["width"]} {value["style"]} {value["color"]}'
        return self
    
    def padding(self, value):
        self['padding'] = f'{value}px'
        return self
    
    def margin(self, value):
        self['margin'] = f'{value}px'
        return self
    
    def corners(self, value):
        self['border-radius'] = f'{value}px'
        return self
    
    def shadow(self, value):
        self['box-shadow'] = f'{value["offset"][0]} {value["offset"][1]} {value["blur"]} {value["color"]}'
        return self
    
    def flex(self, value):
        if value == "center":
            self['display'] = 'flex'
            self['justify-content'] = 'center'
            self['align-items'] = 'center'
        else:
            self['display'] = 'flex'
        return self
    
    def fg_shadow(self, value):
        self['text-shadow'] = f'{value["offset"][0]} {value["offset"][1]} {value["blur"]} {value["color"]}'
        return self
    
    def text(self, value):
        self['text-align'] = value
        return self
    
    def dims(self, value):
        self['width'] = f'{value["width"]}px'
        self['height'] = f'{value["height"]}px'
        return self
    
    def pos(self, value):
        self['position'] = 'absolute'
        self['top'] = f'{value["top"]}px'
        self['left'] = f'{value["left"]}px'
        return self
    
    def custom(self, key, value):
        self[key] = value
        return self

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
    def __init__(self, host='localhost', port=8080):
        self.host = host
        self.port = port
        self.s2c_events = {}
        self.c2s_listeners = {}
        self.c2s_events = {}
        self.s2c_listeners = {}
        self.widgets = {}
        self.connected_clients = set()
        self.trigger_event = self.dispatch_s2c
    
    def c2s(self, event_name):
        def decorator(func):
            self.c2s_listeners[event_name] = func
            return func
        return decorator

    def s2c(self, event_name):
        def decorator(func):
            self.s2c_listeners[event_name] = func
            return func
        return decorator

    def widget(self, widget_name, root_tag='div'):
        def decorator(cls):
            instance = cls()
            def __init__hook(self=instance):
                Widget.__init__(self, root_tag)
                self.initialize()
            setattr(instance, '__init__', __init__hook)
            instance.name = widget_name
            instance.server = self
            self.widgets[widget_name] = instance
            return cls
        return decorator
    
    def builtin(self, *args):
        if len(args) == 0:
            def decorator(cls):
                instance = cls()
                instance.register(self)
                return cls
            return decorator
        elif len(args) == 1:
            cls = args[0]
            instance = cls()
            instance.register(self)
            return cls
        else:
            raise TypeError("builtin takes at most 1 argument")
    
    async def ws_handler(self, websocket, path):
        self.connected_clients.add(websocket)
        try:
            async for message in websocket:
                data = json.loads(message)
                event_name = data.get('event')
                event_data = data.get('data', {})
                if event_name in self.c2s_listeners:
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
            asyncio.create_task(client.send(message))
    
    def dispatch_s2c(self, event_name: str, data: Dict[str, Any]) -> None:
        if event_name in self.s2c_listeners:
            result = self.s2c_listeners[event_name](data)
            if result is not None:
                data = result
        self.send_event(event_name, data)
    
    def dispatch_c2s(self, event_name: str, data: Dict[str, Any]) -> None:
        if event_name in self.c2s_listeners:
            import asyncio
            asyncio.create_task(self.c2s_listeners[event_name](data, None))
    
    def generate_event_js(self):
        js = f"""
        <script>
        const ws = new WebSocket('ws://{self.host}:{self.port + 1}');
        const pendingRequests = {{}};
        let requestId = 0;
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
        function sendEvent(eventName, data) {{
            const id = ++requestId;
            return new Promise((resolve, reject) => {{
                const timeout = setTimeout(() => {{
                    delete pendingRequests[id];
                    reject(new Error('Request timeout'));
                }}, 5000);
                pendingRequests[id] = {{ resolve, reject, timeout }};
                ws.send(JSON.stringify({{ event: eventName, data: data, id: id }}));
            }});
        }}
        </script>
        """
        return js
    
    def run(self):
        import asyncio
        import json
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
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ws_server = websockets.serve(self.ws_handler, self.host, self.port + 1)
            loop.run_until_complete(ws_server)
            loop.run_forever()

        threading.Thread(target=run_flask).start()
        threading.Thread(target=run_ws).start()

def test_attributes():
    attrs = Attributes()
    attrs.bg('#000000')
    attrs.fg('#FFFFFF')
    attrs.font('Arial')
    attrs.font_size(14)
    attrs.border({'width': '2px', 'style': 'solid', 'color': '#FF0000'})
    attrs.flex("center")
    assert attrs['background'] == '#000000'
    assert attrs['color'] == '#FFFFFF'
    assert attrs['font-family'] == 'Arial'
    assert attrs['font-size'] == '14px'
    assert attrs['border'] == '2px solid #FF0000'
    assert attrs['display'] == 'flex'
    assert attrs['justify-content'] == 'center'
    assert attrs['align-items'] == 'center'

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