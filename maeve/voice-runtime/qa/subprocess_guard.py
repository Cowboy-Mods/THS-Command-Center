"""Pure Windows executable classification; no process launch or command logging."""
import os
from pathlib import Path

class ExecutableRejected(RuntimeError):
    pass

def reject():
    raise ExecutableRejected('UNRESOLVABLE_OR_PROHIBITED_EXECUTABLE')

def windows_words(command):
    if not isinstance(command,str) or not command.strip() or '\0' in command:
        reject()
    words=[]; i=0
    while i<len(command):
        while i<len(command) and command[i] in ' \t': i+=1
        if i==len(command): break
        word=[]; quoted=False
        while i<len(command) and (quoted or command[i] not in ' \t'):
            slashes=0
            while i<len(command) and command[i]=='\\': slashes+=1; i+=1
            if i<len(command) and command[i]=='"':
                word.extend('\\'*(slashes//2))
                if slashes%2: word.append('"')
                else: quoted=not quoted
                i+=1
            else:
                word.extend('\\'*slashes)
                if i<len(command) and (quoted or command[i] not in ' \t'):
                    word.append(command[i]); i+=1
        if quoted: reject()
        words.append(''.join(word))
    if not words or not words[0]: reject()
    return words

def effective_executable(explicit,command,allowed):
    """Accept an exact absolute allowlisted file, without PATH or shell lookup."""
    if isinstance(command,os.PathLike): command=os.fspath(command)
    if isinstance(command,str): words=windows_words(command)
    elif isinstance(command,(list,tuple)) and command:
        try: words=[os.fspath(x) for x in command]
        except TypeError: reject()
        if not all(isinstance(x,str) and '\0' not in x for x in words) or not words[0]: reject()
    else: reject()
    try:
        value=os.fspath(explicit) if explicit is not None else words[0]
        if not isinstance(value,str) or not value or '\0' in value: reject()
        target=Path(value)
        if not target.is_absolute(): reject()
        # Reject before touching a prohibited path, including protected/user files.
        if os.path.normcase(os.path.normpath(value))!=os.path.normcase(os.path.normpath(os.fspath(allowed))): reject()
        if not target.is_file(): reject()
    except (TypeError,ValueError,OSError): reject()
    return target
