from hcreative_streamwidget.widgets import Widget, div, button, input, python, table, thead, tbody, tr, td, th, select, option, h2, p, ul, li, c2s, client, Attributes
from hcreative_streamwidget.memhook import is_admin, elevate

class ProcAnalyzeWidget(Widget):
    def initialize(self):
        self.selected_process = None
        self.hook_id = None
        self.scan_results = []
        self.monitored_addresses = []
        
    def build(self):
        if not is_admin():
            return div(
                h2("Administrator Privileges Required"),
                p("This tool requires administrator privileges to access process memory."),
                button("Elevate Privileges", attrs=Attributes().on_click('elevate_privileges'))
            )
        
        return div(
            h2("Memory Scanner"),
            div(
                h2("Process List"),
                button("Refresh Processes", attrs=Attributes().on_click('refresh_processes')),
                div(attrs=Attributes().custom('id', 'process_list').custom('style', 'max-height: 200px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'))
            ),
            div(
                h2("Memory Search"),
                div(
                    "Value: ", input(attrs=Attributes().custom('id', 'search_value').custom('type', 'text')),
                    " Type: ", select(
                        option("int32", "int32"),
                        option("int64", "int64"),
                        option("float32", "float32"),
                        option("float64", "float64"),
                        attrs=Attributes().custom('id', 'search_type')
                    ),
                    button("First Scan", attrs=Attributes().on_click('first_scan')),
                    button("Next Scan", attrs=Attributes().on_click('next_scan'))
                )
            ),
            div(
                h2("Scan Results"),
                table(
                    thead(tr(th("Address"), th("Value"), th("Actions"))),
                    tbody(attrs=Attributes().custom('id', 'scan_results'))
                )
            ),
            div(
                h2("Monitored Addresses"),
                table(
                    thead(tr(th("Address"), th("Current Value"), th("Actions"))),
                    tbody(attrs=Attributes().custom('id', 'monitored_addresses'))
                )
            ),
            python(
                """
from browser import window

window.on_ws_open(lambda: window.server.emit("refresh_processes"))
                """
            )
        )
    
    @c2s('elevate_privileges')
    async def elevate_privileges(self, data, websocket):
        elevate()
        return {'success': True}
    
    @c2s('refresh_processes')
    async def refresh_processes(self, data, websocket):
        # Call the builtin
        if 'list_processes' in self.server.c2s_listeners:
            response = await self.server.c2s_listeners['list_processes']({}, websocket)
            if response.get('success'):
                processes = response['processes']
                process_html = ul(*[li(f"{p['name']} (PID: {p['pid']})", attrs=Attributes().on_click('select_process').custom('data-pid', str(p['pid'])).custom('data-name', p['name'])) for p in processes[:50]], attrs=Attributes().custom('style', 'list-style: none; padding: 0; margin: 0;')).render()
                self.server.to_client('update_process_list', {'html': process_html})
        return {'success': True}
    
    @c2s('select_process')
    async def select_process(self, data, websocket):
        pid = data['pid']
        name = data['name']
        self.selected_process = name
        # Create hook
        response = {'success': False}
        if 'create_memory_hook' in self.server.c2s_listeners:
            response = await self.server.c2s_listeners['create_memory_hook']({
                'hook_id': f'hook_{pid}',
                'process_name': name,
                'base_address': 0,
                'offsets': [],
                'data_type': 'int32'
            }, websocket)
            if response.get('success'):
                self.hook_id = f'hook_{pid}'
        return response
    
    @c2s('first_scan')
    async def first_scan(self, data, websocket):
        if not self.hook_id:
            return {'success': False, 'error': 'No process selected'}
        
        value_str = data.get('value', '')
        data_type = data.get('type', 'int32')
        
        try:
            if data_type.startswith('int'):
                value = int(value_str)
            elif data_type.startswith('float'):
                value = float(value_str)
            else:
                return {'success': False, 'error': 'Invalid data type'}
        except ValueError:
            return {'success': False, 'error': 'Invalid value'}
        
        response = {'success': False}
        if 'scan_memory' in self.server.c2s_listeners:
            response = await self.server.c2s_listeners['scan_memory']({
                'hook_id': self.hook_id,
                'value': value,
                'data_type': data_type,
                'max_results': 100
            }, websocket)
            
            if response.get('success'):
                self.scan_results = response['addresses']
                rows = []
                for addr in self.scan_results[:50]:
                    rows.append(tr(
                        td(f"0x{addr:X}"),
                        td("?", attrs=Attributes().custom('id', f'value_{addr}')),
                        td(button("Monitor", attrs=Attributes().on_click('monitor_address').custom('data-addr', str(addr))))
                    ).render())
                results_html = ''.join(rows)
                self.server.to_client('update_scan_results', {'html': results_html})
        return response
    
    @c2s('monitor_address')
    async def monitor_address(self, data, websocket):
        addr = int(data['addr'])
        if addr not in self.monitored_addresses:
            self.monitored_addresses.append(addr)
            hook_id = f'monitor_{addr}'
            if 'create_memory_hook' in self.server.c2s_listeners:
                response = await self.server.c2s_listeners['create_memory_hook']({
                    'hook_id': hook_id,
                    'process_name': self.selected_process,
                    'base_address': addr,
                    'offsets': [],
                    'data_type': 'int32'  # Assume int32
                }, websocket)
                if response.get('success'):
                    if 'start_memory_monitoring' in self.server.c2s_listeners:
                        await self.server.c2s_listeners['start_memory_monitoring']({
                            'hook_id': hook_id,
                            'interval': 1.0
                        }, websocket)
                    row = tr(
                        td(f"0x{addr:X}"),
                        td("?", attrs=Attributes().custom('id', f'monitor_value_{addr}')),
                        td(button("Stop", attrs=Attributes().on_click('stop_monitor').custom('data-addr', str(addr))))
                    , attrs=Attributes().custom('id', f'monitor_row_{addr}')).render()
                    self.server.to_client('add_monitored', {'html': row})
        return {'success': True}
    
    @c2s('stop_monitor')
    async def stop_monitor(self, data, websocket):
        addr = int(data['addr'])
        if addr in self.monitored_addresses:
            self.monitored_addresses.remove(addr)
            hook_id = f'monitor_{addr}'
            if 'stop_memory_monitoring' in self.server.c2s_listeners:
                await self.server.c2s_listeners['stop_memory_monitoring']({'hook_id': hook_id}, websocket)
            if 'detach_memory_hook' in self.server.c2s_listeners:
                await self.server.c2s_listeners['detach_memory_hook']({'hook_id': hook_id}, websocket)
            self.server.to_client('remove_monitored', {'addr': addr})
        return {'success': True}
    
    # Client-side event handlers
    @client('update_process_list')
    def update_process_list(self, data, document, browser):
        elem = document.getElementById('process_list')
        if elem:
            elem.html = data['html']
            browser.console.log("Updated process list with HTML")
        else:
            browser.console.log("Element 'process_list' not found")
    
    @client('update_scan_results')
    def update_scan_results(self, data, document):
        elem = document.getElementById('scan_results')
        if elem:
            elem.innerHTML = data['html']
    
    @client('add_monitored')
    def add_monitored(self, data, document):
        tbody = document.getElementById('monitored_addresses')
        if tbody:
            tbody.innerHTML += data['html']
    
    @client('remove_monitored')
    def remove_monitored(self, data, document):
        addr = data['addr']
        row = document.getElementById(f'monitor_row_{addr}')
        if row:
            row.remove()
    
    @client('memory_value_changed')
    def memory_value_changed(self, data, document):
        hook_id = data['hook_id']
        value = data['value']
        if hook_id.startswith('monitor_'):
            addr = hook_id.split('_')[1]
            elem = document.getElementById(f'monitor_value_{addr}')
            if elem:
                elem.textContent = str(value)

if __name__ == '__main__':
    from hcreative_streamwidget.widgets import Server
    from hcreative_streamwidget.memhook import MemoryHookBuiltin
    
    server = Server(host='127.0.0.1', port=5001)
    
    server.builtin(MemoryHookBuiltin)
    
    @server.widget('proc_analyze')
    class ProcAnalyzeWidgetInstance(ProcAnalyzeWidget):
        pass
    
    import asyncio
    asyncio.run(server.run())
