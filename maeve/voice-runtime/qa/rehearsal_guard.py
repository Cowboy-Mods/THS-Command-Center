"""Test-only fail-closed guard. Install before importing any runtime QA."""
import sys, os
from subprocess_guard import effective_executable

def install():
    sys.dont_write_bytecode=True
    roots=[os.path.normcase(os.path.abspath(os.environ[k])) for k in ('MAEVE_QA_ROOT','MAEVE_QA_TEMP')]
    roots.append(os.path.normcase(os.path.dirname(sys.executable)))
    def blocked(category):
        print('ISOLATION_BLOCK '+category,file=sys.stderr)
        raise RuntimeError('ISOLATION_BLOCK '+category)
    def check(p):
        if isinstance(p,int): return
        p=os.path.normcase(os.path.abspath(os.fsdecode(p)))
        if p==os.path.normcase(os.path.abspath(os.devnull)): return
        if any(p==r or p.startswith(r+os.sep) for r in roots): return
        blocked('filesystem-outside-rehearsal-toolchain-temp')
    def audit(event,args):
        if event=='open': check(args[0])
        elif event in ('os.listdir','os.scandir'): check(args[0] or os.getcwd())
        elif event in ('socket.connect','socket.bind','socket.getaddrinfo','os.system'): blocked(event)
        elif event=='ctypes.dlopen':
            if any(s in str(args[0] or '').casefold() for s in ('advapi','credui','vault','winhttp','wininet','ws2_32','winmm')): blocked('native-private-or-device-api')
        elif event=='ctypes.dlsym' and any(s in str(args[1]).casefold() for s in ('credread','credwrite','creddelete','vault')): blocked('native-credential-symbol')
        elif event=='subprocess.Popen': effective_executable(args[0],args[1],sys.executable)
    sys.addaudithook(audit)
