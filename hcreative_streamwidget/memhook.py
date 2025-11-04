import ctypes
import ctypes.wintypes
import sys
import struct
from typing import Optional, Dict, Any, Callable
import threading
import time
from .widgets import Builtin

def is_admin() -> bool:
    """Checks if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def elevate() -> None:
    """Relaunches the current script with administrator privileges."""
    if is_admin():
        return
    
    executable = sys.executable
    script = sys.argv[0]
    args = sys.argv[1:]
    
    params = f'"{script}"'
    if args:
        params += ' ' + ' '.join(f'"{arg}"' for arg in args)
    
    ret = ctypes.windll.shell32.ShellExecuteW(
        None,  # hwnd
        "runas",  # lpOperation
        executable,  # lpFile
        params,  # lpParameters
        None,  # lpDirectory
        1  # nShowCmd (SW_SHOWNORMAL)
    )
    
    # If ShellExecute succeeds, exit the current process
    if ret > 32:  # SE_ERR_SUCCESS and above
        sys.exit(0)
    else:
        raise RuntimeError("Failed to elevate privileges")

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.wintypes.DWORD), ("HighPart", ctypes.wintypes.LONG)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", ctypes.wintypes.DWORD)]

def enable_debug_privilege() -> bool:
    """Enable SeDebugPrivilege to access all processes."""
    try:
        # Get current process token
        token = ctypes.wintypes.HANDLE()
        ctypes.windll.advapi32.OpenProcessToken(
            ctypes.windll.kernel32.GetCurrentProcess(),
            0x0020,  # TOKEN_ADJUST_PRIVILEGES
            ctypes.byref(token)
        )
        
        # Lookup privilege value
        luid = LUID()
        ctypes.windll.advapi32.LookupPrivilegeValueW(
            None,
            "SeDebugPrivilege",
            ctypes.byref(luid)
        )
        
        # Enable the privilege
        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [
                ("PrivilegeCount", ctypes.wintypes.DWORD),
                ("Privileges", LUID_AND_ATTRIBUTES * 1),
            ]
        
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = 0x00000002  # SE_PRIVILEGE_ENABLED
        
        ctypes.windll.advapi32.AdjustTokenPrivileges(
            token,
            False,
            ctypes.byref(tp),
            0,
            None,
            None
        )
        
        ctypes.windll.kernel32.CloseHandle(token)
        return True
    except Exception:
        return False

def list_processes() -> list:
    """List all running processes with their PIDs and names."""
    processes = []
    enable_debug_privilege()
    
    TH32CS_SNAPPROCESS = 0x00000002
    snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    
    if snapshot == -1:
        return processes
        
    try:
        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.wintypes.DWORD),
                ("cntUsage", ctypes.wintypes.DWORD),
                ("th32ProcessID", ctypes.wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.wintypes.ULONG)),
                ("th32ModuleID", ctypes.wintypes.DWORD),
                ("th32ParentProcessID", ctypes.wintypes.DWORD),
                ("cntThreads", ctypes.wintypes.LONG),
                ("th32ThreadID", ctypes.wintypes.LONG),
                ("dwFlags", ctypes.wintypes.LONG),
                ("szExeFile", ctypes.c_char * 260),
            ]
        
        pe32 = PROCESSENTRY32()
        pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
        
        if not ctypes.windll.kernel32.Process32First(snapshot, ctypes.byref(pe32)):
            return processes
            
        while True:
            exe_name = pe32.szExeFile.decode('utf-8', errors='ignore')
            pid = pe32.th32ProcessID
            processes.append({
                'pid': pid,
                'name': exe_name,
                'threads': pe32.cntThreads,
                'parent_pid': pe32.th32ParentProcessID
            })
            
            if not ctypes.windll.kernel32.Process32Next(snapshot, ctypes.byref(pe32)):
                break
                
    finally:
        ctypes.windll.kernel32.CloseHandle(snapshot)
        
    return processes

class MemoryHook:
    """Hooks into external process memory."""
    
    def __init__(self, process_name: str):
        self.process_name = process_name
        self.process_handle = None
        self.base_address = None
        self._offsets = []
        self._data_type = 'int32'  # Default data type
        self._value = None
        self._running = False
        self._thread = None
        self.value_changed_callbacks = []
        
        # Windows API constants
        self.PROCESS_ALL_ACCESS = 0x1F0FFF
        self.MEM_COMMIT = 0x1000
        self.PAGE_READWRITE = 0x04
        
    def set_target(self, base_address: int, offsets: Optional[list] = None, data_type: str = 'int32'):
        """Set the memory address to hook into."""
        self.base_address = base_address
        self._offsets = offsets or []
        self._data_type = data_type
    
    def add_value_changed_callback(self, callback: Callable[[Any], None]):
        """Add a callback to be called when the monitored value changes."""
        self.value_changed_callbacks.append(callback)
        
    def _get_data_size(self) -> int:
        """Get the size of the data type in bytes."""
        sizes = {
            'int8': 1,
            'int16': 2,
            'int32': 4,
            'int64': 8,
            'float32': 4,
            'float64': 8,
            'uint8': 1,
            'uint16': 2,
            'uint32': 4,
            'uint64': 8,
        }
        return sizes.get(self._data_type, 4)
    
    def _read_memory(self, address: int, size: int) -> bytes:
        """Read memory from the target process."""
        if not self.process_handle:
            raise RuntimeError("Process not attached")
            
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t()
        
        success = ctypes.windll.kernel32.ReadProcessMemory(
            self.process_handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(bytes_read)
        )
        
        if not success or bytes_read.value != size:
            raise RuntimeError(f"Failed to read memory at address 0x{address:X}")
            
        return buffer.raw
    
    def _calculate_address(self) -> int:
        """Calculate the final address using base address and offsets."""
        if not self.base_address:
            raise RuntimeError("Base address not set")
            
        address = self.base_address
        
        for offset in self._offsets:
            ptr_bytes = self._read_memory(address, 8)
            address = struct.unpack('<Q', ptr_bytes)[0] + offset
            
        return address
    
    def read_value(self) -> Any:
        """Read the current value from memory."""
        address = self._calculate_address()
        size = self._get_data_size()
        data = self._read_memory(address, size)
        
        # Unpack based on data type
        if self._data_type.startswith('int'):
            signed = not self._data_type.startswith('u')
            if self._data_type == 'int8' or self._data_type == 'uint8':
                return struct.unpack('<b' if signed else '<B', data)[0]
            elif self._data_type == 'int16' or self._data_type == 'uint16':
                return struct.unpack('<h' if signed else '<H', data)[0]
            elif self._data_type == 'int32' or self._data_type == 'uint32':
                return struct.unpack('<i' if signed else '<I', data)[0]
            elif self._data_type == 'int64' or self._data_type == 'uint64':
                return struct.unpack('<q' if signed else '<Q', data)[0]
        elif self._data_type.startswith('float'):
            if self._data_type == 'float32':
                return struct.unpack('<f', data)[0]
            elif self._data_type == 'float64':
                return struct.unpack('<d', data)[0]
                
        return data # Raw bytes if unknown type

    def attach(self) -> bool:
        """Attach to the target process."""
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        PROCESS_VM_WRITE = 0x0020
        PROCESS_VM_OPERATION = 0x0008
        
        access = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        
        TH32CS_SNAPPROCESS = 0x00000002
        snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        
        if snapshot == -1:
            return False
            
        try:
            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.wintypes.DWORD),
                    ("cntUsage", ctypes.wintypes.DWORD),
                    ("th32ProcessID", ctypes.wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.wintypes.ULONG)),
                    ("th32ModuleID", ctypes.wintypes.DWORD),
                    ("th32ParentProcessID", ctypes.wintypes.DWORD),
                    ("cntThreads", ctypes.wintypes.LONG),
                    ("th32ThreadID", ctypes.wintypes.LONG),
                    ("dwFlags", ctypes.wintypes.LONG),
                    ("szExeFile", ctypes.c_char * 260),
                ]
            
            pe32 = PROCESSENTRY32()
            pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
            
            if not ctypes.windll.kernel32.Process32First(snapshot, ctypes.byref(pe32)):
                return False
                
            while True:
                exe_name = pe32.szExeFile.decode('utf-8')
                if exe_name.lower() == self.process_name.lower():
                    pid = pe32.th32ProcessID
                    self.process_handle = ctypes.windll.kernel32.OpenProcess(access, False, pid)
                    return self.process_handle is not None
                
                if not ctypes.windll.kernel32.Process32Next(snapshot, ctypes.byref(pe32)):
                    break
                    
        finally:
            ctypes.windll.kernel32.CloseHandle(snapshot)
            
        return False
    
    def detach(self) -> None:
        """Detach from the target process."""
        if self.process_handle:
            ctypes.windll.kernel32.CloseHandle(self.process_handle)
            self.process_handle = None
    
    def start_monitoring(self, callback: Callable[[Any], None], interval: float = 1.0) -> None:
        """Start monitoring the memory value and call callback when it changes."""
        if self._running:
            return
            
        self._running = True
        
        def monitor():
            last_value = None
            while self._running:
                try:
                    current_value = self.read_value()
                    if current_value != last_value:
                        last_value = current_value
                        callback(current_value)
                        for cb in self.value_changed_callbacks:
                            cb(current_value)
                except Exception as e:
                    print(f"Memory read error: {e}")
                    time.sleep(interval)
                    continue
                    
                time.sleep(interval)
        
        self._thread = threading.Thread(target=monitor, daemon=True)
        self._thread.start()
    
    def stop_monitoring(self) -> None:
        """Stop monitoring the memory value."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
    
    def scan_memory(self, value: Any, data_type: str = 'int32', max_results: int = 100) -> list:
        """Scan process memory for a specific value and return matching addresses."""
        if not self.process_handle:
            raise RuntimeError("Process not attached")
        
        addresses = []
        
        # Get system info for memory iteration
        class SYSTEM_INFO(ctypes.Structure):
            _fields_ = [
                ("dwOemId", ctypes.wintypes.DWORD),
                ("dwPageSize", ctypes.wintypes.DWORD),
                ("lpMinimumApplicationAddress", ctypes.POINTER(ctypes.wintypes.LPVOID)),
                ("lpMaximumApplicationAddress", ctypes.POINTER(ctypes.wintypes.LPVOID)),
                ("dwActiveProcessorMask", ctypes.POINTER(ctypes.wintypes.LPVOID)),
                ("dwNumberOfProcessors", ctypes.wintypes.DWORD),
                ("dwProcessorType", ctypes.wintypes.DWORD),
                ("dwAllocationGranularity", ctypes.wintypes.DWORD),
                ("wProcessorLevel", ctypes.wintypes.WORD),
                ("wProcessorRevision", ctypes.wintypes.WORD),
            ]
        
        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", ctypes.wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", ctypes.wintypes.DWORD),
                ("Protect", ctypes.wintypes.DWORD),
                ("Type", ctypes.wintypes.DWORD),
            ]
        
        sys_info = SYSTEM_INFO()
        ctypes.windll.kernel32.GetSystemInfo(ctypes.byref(sys_info))
        
        min_addr = sys_info.lpMinimumApplicationAddress
        max_addr = sys_info.lpMaximumApplicationAddress
        
        # Pack the search value
        size = self._get_data_size()
        if data_type.startswith('int'):
            signed = not data_type.startswith('u')
            if data_type == 'int8' or data_type == 'uint8':
                search_bytes = struct.pack('<b' if signed else '<B', value)
            elif data_type == 'int16' or data_type == 'uint16':
                search_bytes = struct.pack('<h' if signed else '<H', value)
            elif data_type == 'int32' or data_type == 'uint32':
                search_bytes = struct.pack('<i' if signed else '<I', value)
            elif data_type == 'int64' or data_type == 'uint64':
                search_bytes = struct.pack('<q' if signed else '<Q', value)
            else:
                search_bytes = bytes(size)
        elif data_type.startswith('float'):
            if data_type == 'float32':
                search_bytes = struct.pack('<f', value)
            elif data_type == 'float64':
                search_bytes = struct.pack('<d', value)
            else:
                search_bytes = bytes(size)
        else:
            search_bytes = value if isinstance(value, bytes) else bytes(size)
        
        current_addr = min_addr
        
        while current_addr < max_addr and len(addresses) < max_results:
            mem_info = MEMORY_BASIC_INFORMATION()
            result = ctypes.windll.kernel32.VirtualQueryEx(
                self.process_handle,
                ctypes.c_void_p(current_addr),
                ctypes.byref(mem_info),
                ctypes.sizeof(mem_info)
            )
            
            if result == 0:
                break
            
            # Check if region is readable (committed and accessible)
            if (mem_info.State == self.MEM_COMMIT and 
                (mem_info.Protect & 0xFF) not in [0x01, 0x04, 0x10]):
                
                region_start = mem_info.BaseAddress
                region_size = mem_info.RegionSize
                
                chunk_size = 4096
                for offset in range(0, region_size, chunk_size):
                    addr = region_start + offset
                    read_size = min(chunk_size, region_size - offset)
                    
                    try:
                        data = self._read_memory(addr, read_size)
                        pos = 0
                        while pos < len(data) - len(search_bytes) + 1:
                            if data[pos:pos + len(search_bytes)] == search_bytes:
                                addresses.append(addr + pos)
                                if len(addresses) >= max_results:
                                    break
                            pos += 1
                        if len(addresses) >= max_results:
                            break
                    except Exception:
                        # Skip unreadable chunks
                        pass
            
            current_addr += mem_info.RegionSize
        
        return addresses

class MemoryHookBuiltin(Builtin):
    """Builtin for memory hooking."""
    
    def __init__(self, server):
        super().__init__(server)
        self.hooks: Dict[str, MemoryHook] = {}
        
    def register(self, server):
        self.server.c2s_listeners['list_processes'] = self.list_processes_handler
        self.server.c2s_listeners['create_memory_hook'] = self.create_memory_hook
        self.server.c2s_listeners['scan_memory'] = self.scan_memory_handler
        self.server.c2s_listeners['read_memory_value'] = self.read_memory_value
        self.server.c2s_listeners['start_memory_monitoring'] = self.start_memory_monitoring
        self.server.c2s_listeners['stop_memory_monitoring'] = self.stop_memory_monitoring
        self.server.c2s_listeners['detach_memory_hook'] = self.detach_memory_hook
    
    async def list_processes_handler(self, data, websocket):
        enable_debug_privilege()
        print("Listing processes...")
        try:
            processes = list_processes()
            print(f"Found {len(processes)} processes")
            return {'success': True, 'processes': processes}
        except Exception as e:
            print(f"Error listing processes: {e}")
            return {'success': False, 'error': str(e)}
    
    async def create_memory_hook(self, data, websocket):
        hook_id = data['hook_id']
        process_name = data['process_name']
        base_address = int(data['base_address'], 16) if isinstance(data['base_address'], str) else data['base_address']
        offsets = data.get('offsets', [])
        data_type = data.get('data_type', 'int32')
        
        hook = MemoryHook(process_name)
        hook.set_target(base_address, offsets, data_type)
        
        if hook.attach():
            self.hooks[hook_id] = hook
            return {'success': True, 'hook_id': hook_id}
        else:
            return {'success': False, 'error': 'Failed to attach to process'}
    
    async def scan_memory_handler(self, data, websocket):
        hook_id = data['hook_id']
        value = data['value']
        data_type = data.get('data_type', 'int32')
        max_results = data.get('max_results', 100)
        hook = self.hooks.get(hook_id)
        if not hook:
            return {'success': False, 'error': 'Hook not found'}
        
        try:
            addresses = hook.scan_memory(value, data_type, max_results)
            return {'success': True, 'addresses': addresses}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def read_memory_value(self, data, websocket):
        hook_id = data['hook_id']
        hook = self.hooks.get(hook_id)
        if not hook:
            return {'success': False, 'error': 'Hook not found'}
        
        try:
            value = hook.read_value()
            return {'success': True, 'value': value}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def start_memory_monitoring(self, data, websocket):
        hook_id = data['hook_id']
        interval = data.get('interval', 1.0)
        hook = self.hooks.get(hook_id)
        if not hook:
            return {'success': False, 'error': 'Hook not found'}
        
        def on_value_change(value):
            self.server.to_client('memory_value_changed', {
                'hook_id': hook_id,
                'value': value
            })
        
        hook.start_monitoring(on_value_change, interval)
        return {'success': True}
    
    async def stop_memory_monitoring(self, data, websocket):
        hook_id = data['hook_id']
        hook = self.hooks.get(hook_id)
        if hook:
            hook.stop_monitoring()
        return {'success': True}
    
    async def detach_memory_hook(self, data, websocket):
        hook_id = data['hook_id']
        hook = self.hooks.pop(hook_id, None)
        if hook:
            hook.stop_monitoring()
            hook.detach()
        return {'success': True}
