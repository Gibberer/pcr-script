"""Read-only LeiDian discovery with independent process handles."""
import os
import subprocess


def query_list2(path):
    command = [os.path.join(path, 'ldconsole.exe'), 'list2']
    for attempt in range(3):
        try:
            return subprocess.check_output(command, encoding='mbcs', errors='replace',
                timeout=15, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.CalledProcessError as error:
            # A read-only retry is safe; never replay runapp or input here.
            if (error.returncode & 0xffffffff) != 0xC0000008 or attempt == 2:
                raise
