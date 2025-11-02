import os
from typing import cast
from hcreative_streamwidget import widgets
import threading
import dotenv
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.chat import Chat
import json
import asyncio

dotenv.load_dotenv()

twitch = Twitch(
    app_id=os.environ.get("TWITCH_CLIENT_ID"),
    app_secret=os.environ.get("TWITCH_CLIENT_SECRET"),
)

auth = UserAuthenticator(twitch, ["user:read:email", "chat:read", "chat:edit"])

asyncio.run(auth.authenticate())

twitch.authenticate_app([
    "user:read:email",
    "chat:read",
    "chat:edit",
])

server = widgets.Server()

@server.builtin
class TwitchAPIBuiltin(widgets.Builtin):
    def register(self, server):
        self.twitch = twitch
        @server.c2s('get_user_info')
        async def get_user_info(data, websocket):
            user_info = await self.twitch.get_users(logins=[data['login']])
            return {'user_info': user_info}
        
        chat = Chat(twitch)

        @server.c2s('send_chat_message')
        async def send_chat_message(data, websocket):
            channel = data['channel']
            message = data['message']
            await chat.send_message(channel, message)
            return {}
        
        chat.register_event("on_message", self.on_message)

    def on_message(self, msg):
        data = {
            'user': msg.user.name,
            'message': msg.text,
            'channel': msg.channel.name
        }
        server.dispatch_s2c('chat_message', data)

@server.widget('counter', 'div')
class CounterWidget(widgets.Widget):
    def initialize(self):
        self.count = 0
        self.element.attrs.dims({'width': 200, 'height': 100}) \
            .pos({'top': 50, 'left': 50}) \
            .border({'width': '1px', 'style': 'solid', 'color': '#000000'})
        self.update_content()
    
    def update_content(self):
        self.element.content = f'Count: {self.count}'
    
    def build(self):
        return self.element
    
    @server.c2s('increment')
    def increment(self, data):
        self.count += 1
        self.update_content()
        server.trigger_event('update', {'widget': 'counter', 'count': self.count})

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
    def on_chat_message(data):
        from browser import document, html
        chat_div = document['chat-messages']
        msg_div = html.DIV(f"{data['user']}: {data['message']}")
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
        
        import browser.timer
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