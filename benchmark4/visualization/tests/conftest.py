from pathlib import Path
import socket
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    def local_only(sock, address):
        if not isinstance(address,tuple) or address[0] not in {'127.0.0.1','::1','localhost'}:
            raise AssertionError('external network forbidden')
        return original(sock,address)
    monkeypatch.setattr(socket.socket,'connect',local_only)
    def no_process(*args, **kwargs): raise AssertionError('Docker/model subprocess forbidden')
    monkeypatch.setattr(subprocess,'run',no_process)
    monkeypatch.setattr(subprocess,'Popen',no_process)
