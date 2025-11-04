import os
from typing import cast, Dict, Any
from hcreative_streamwidget import widgets
import threading
import dotenv
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.chat import Chat
import json
import asyncio
from typing import TypeVar
from twitchAPI.chat import ChatEvent
from hcreative_streamwidget import elevate, is_admin
from hcreative_streamwidget.memhook import MemoryHookBuiltin

if not is_admin():
    elevate()

dotenv.load_dotenv()

T = TypeVar('T')
def required(opt: T | None) -> T:
    if opt is None:
        raise ValueError("Required environment variable is missing")
    return cast(T, opt)

twitch = None

async def main():
    global twitch
    twitch = await Twitch(
        app_id=required(os.environ["TWITCH_API_ID"]),
        app_secret=required(os.environ["TWITCH_API_SECRET"]),
    )
    auth = UserAuthenticator(twitch, [AuthScope.USER_READ_EMAIL, AuthScope.CHAT_READ, AuthScope.CHAT_EDIT])

    auth_result = await auth.authenticate()
    assert auth_result is not None, "Authentication failed, no token received."
    token, refresh_token = auth_result
    await twitch.set_user_authentication(token, [AuthScope.USER_READ_EMAIL, AuthScope.CHAT_READ, AuthScope.CHAT_EDIT], refresh_token)

    chat = required(await Chat(twitch))

    server = widgets.Server()
    server.builtin(MemoryHookBuiltin)

    @server.builtin
    class TwitchAPIBuiltin(widgets.Builtin):
        def register(self, server):
            self.twitch = required(twitch)
            @self.c2s('get_user_info')
            async def get_user_info(self, data, websocket):
                user_info = [user async for user in self.twitch.get_users(logins=[data['login']])]
                return {'user_info': user_info}
            
            @self.c2s('send_chat_message')
            async def send_chat_message(self, data, websocket):
                channel = data['channel']
                message = data['message']
                await chat.send_message(channel, message)
                return {}
            
            @self.s2c('chat_message')
            def chat_message(self, data):
                return data
            
            chat.register_event(ChatEvent.MESSAGE, self.on_message)
            chat.register_event(ChatEvent.READY, self.on_ready)

        async def on_message(self, msg):
            data = {
                'user': msg.user.name,
                'message': msg.text,
                'channel': msg.room.name
            }
            self.server.to_client('chat_message', data, recent=True)

        async def on_ready(self, msg):
            data = {
                'user': 'System',
                'message': 'Chat connected.',
                'channel': 'moldsporebirth'
            }
            self.server.to_client('chat_message', data, recent=True)

    @server.widget('counter', 'div')
    class CounterWidget(widgets.Widget):
        def initialize(self):
            self.element.attrs.dims({'width': 400, 'height': 300}) \
                .border({'width': '2.5px', 'style': 'solid', 'color': '#000'}) \
                .shadow({'blur': '0px', 'color': '#000', 'offset': ['5px', '5px']}) \
                .corners({'all': '5px'}) \
                .font('Arial') \
                .font_size(20) \
                .font_weight('normal') \
                .on_click('increment')
            self.count = 0
            self.update_content()

        def update_content(self):
            self.element.content = f'Count: {self.count}'
        
        @widgets.c2s('increment')
        async def increment(self, data: Dict[str, Any], websocket=None) -> None:
            self.count += 1
            self.update_content()
            self.server.to_client('update', {'widget': 'counter', 'count': self.count})
        
        @widgets.client('update')
        def on_update(self, data, document):
            if data.get('widget') == 'counter':
                counter_div = document.getElementById('counter')
                if counter_div:
                    counter_div.textContent = f"Count: {data['count']}"
        
        def build(self):
            return self.element

    @server.widget('twitch_chat')
    class TwitchChatWidget(widgets.Widget):
        def initialize(self):
            self.element.attrs.dims({'width': 400, 'height': 300}) \
                .bg('#f0f0f0') \
                .border({'width': '2.5px', 'style': 'solid', 'color': '#000'}) \
                .shadow({'blur': '0px', 'color': '#000', 'offset': ['5px', '5px']}) \
                .corners({'all': '5px'}) \
                .font('Arial') \
                .font_size(14) \
                .font_weight('normal') \
                .custom('style', 'position: relative;')
            
            chat_messages = widgets.div(
                attrs=widgets.Attributes()
                    .custom('id', 'chat-messages')
                    .custom('style', 'height: 100%; overflow-y: auto; padding: 10px;')
            )
            self.element.content = []
            self.element.content.append(chat_messages)
        
        def build(self):
            return self.element
        
        @widgets.client('chat_message')
        def on_chat_message(self, data, document, window):
            chat_div = document.getElementById('chat-messages')
            user = data.get('user', 'Unknown')
            message = data.get('message', '')
            msg_div = document.createElement('div')
            msg_div.textContent = f"{user}: {message}"
            msg_div.style.opacity = '0'
            msg_div.style.transform = 'translateY(20px)'
            msg_div.style.marginBottom = '5px'
            msg_div.style.padding = '5px'
            msg_div.style.backgroundColor = '#e0e0e0'
            msg_div.style.border = '1px solid #000'
            msg_div.style.boxShadow = '2px 2px 0px rgba(0,0,0,1)'
            msg_div.style.borderRadius = '5px'
            chat_div.appendChild(msg_div)
            
            def animate():
                msg_div.style.transition = 'all 0.5s'
                msg_div.style.opacity = '1'
                msg_div.style.transform = 'translateY(0)'
            
            window.setTimeout(animate, 10)
            
            if len(chat_div.children) > 50:
                chat_div.removeChild(chat_div.firstChild)

    asyncio.create_task(server.run())

    chat.start()

    await chat.join_room('moldsporebirth')

    await asyncio.sleep(float('inf'))

if __name__ == "__main__":
    if not is_admin():
        elevate()
    
    asyncio.run(main())