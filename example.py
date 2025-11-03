import os
from typing import cast
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
            
            chat.register_event(ChatEvent.MESSAGE, self.on_message)
            chat.register_event(ChatEvent.READY, self.on_ready)

        async def on_message(self, msg):
            data = {
                'user': msg.user.name,
                'message': msg.text,
                'channel': msg.channel.name
            }
            server.dispatch_s2c('chat_message', data)

        async def on_ready(self, msg):
            print(dir(msg))
            data = {
                'user': 'System',
                'message': 'Chat is ready!',
                'channel': 'cr.t'
            }
            server.dispatch_s2c('chat_message', data)

    chat.start()

    await chat.join_room('cr.t')

    @server.widget('counter', 'div')
    class CounterWidget(widgets.Widget):
        def initialize(self):
            self.count = 0
            self.element.attrs.dims({'width': 200, 'height': 100}) \
                .pos({'top': 50, 'left': 50}) \
                .border({'width': '1px', 'style': 'solid', 'color': '#000000'})
            self.update_content()
            @self.c2s('increment')
            async def increment(self, data):
                self.count += 1
                self.update_content()
                self.server.trigger_event('update', {'widget': 'counter', 'count': self.count})
        
        def update_content(self):
            self.element.content = f'Count: {self.count}'
        
        def build(self):
            return self.element

    @server.widget('twitch_chat')
    class TwitchChatWidget(widgets.Widget):
        def initialize(self):
            self.element.attrs.dims({'width': 400, 'height': 300}) \
                .bg('#f0f0f0') \
                .border({'width': '1px', 'style': 'solid', 'color': '#000'}) \
                .custom('style', 'position: relative;')
            
            chat_messages = widgets.div(
                attrs=widgets.Attributes()
                    .custom('id', 'chat-messages')
                    .custom('style', 'height: 100%; overflow-y: auto; padding: 10px;')
            )
            self.element.content = [chat_messages]
        
        def build(self):
            return self.element
        
        @widgets.client('chat_message')
        def on_chat_message(self, data, browser):
            document = browser.document
            html = browser.html
            chat_div = document.getElementById('chat-messages')
            user = data.get('user', 'Unknown')
            message = data.get('message', '')
            msg_div = html.DIV(f"{user}: {message}")
            msg_div.style.opacity = '0'
            msg_div.style.transform = 'translateY(20px)'
            msg_div.style.marginBottom = '5px'
            msg_div.style.padding = '5px'
            msg_div.style.backgroundColor = '#e0e0e0'
            msg_div.style.borderRadius = '5px'
            chat_div.appendChild(msg_div)
            
            def animate():
                msg_div.style.transition = 'all 0.5s'
                msg_div.style.opacity = '1'
                msg_div.style.transform = 'translateY(0)'
            
            browser.timer.set_timeout(animate, 10)
            
            if len(chat_div.children) > 50:
                chat_div.removeChild(chat_div.firstChild)

    server.run()

    def timer_increment():
        import time
        while True:
            time.sleep(5)
            server.dispatch_c2s('increment', {})

    threading.Thread(target=timer_increment, daemon=True).start()

asyncio.run(main())