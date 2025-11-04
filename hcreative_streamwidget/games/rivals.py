from typing import Dict
from hcreative_streamwidget.memhook import MemoryHook
from hcreative_streamwidget.widgets import Builtin


class RivalsBuiltin(Builtin):
    """Builtin for hooking into an active Marvel Rivals program."""
    
    def __init__(self, server):
        super().__init__(server)
        
    def register(self, server):
        program_name = "Marvel-Win64-Shipping.exe"
        self.hooks: Dict[str, MemoryHook] = {}
        self.program_name = program_name

        self.hooks['user_data'] = MemoryHook(program_name)
        self.hooks['user_data'].attach()
        self.hooks['user_data'].start_monitoring(lambda x: server.to_client('user_data', x))

        @server.c2s('user_data')
        def handle_user_data(data):
            pass