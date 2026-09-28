"""Exact virtual desktop selection in a short-lived, isolated COM process."""
import multiprocessing as mp
import time
from cmd_event import CmdEvent


def _switch_worker(connection):
    try:
        # Import inside this process: COM interfaces never cross Python threads.
        from pyvda import VirtualDesktop, get_virtual_desktops
        if connection.poll():
            return
        if len(get_virtual_desktops()) < 2:
            VirtualDesktop.create()
        if connection.poll():
            return
        VirtualDesktop(2).go()
        until = time.monotonic() + 3
        while VirtualDesktop.current().number != 2:
            if connection.poll(.05):
                return
            if time.monotonic() >= until:
                raise RuntimeError('Windows не подтвердила переход на рабочий стол 2.')
        connection.send(('result', 'Открыт рабочий стол 2. Возврат: Win + Ctrl + ←.'))
    except Exception as exc:
        try: connection.send(('error', str(exc)))
        except (OSError, EOFError): pass
    finally:
        try: connection.send(('finished', None))
        except (OSError, EOFError): pass
        connection.close()


class DesktopSwitch(CmdEvent):
    def start(self):
        self.stop()
        context = mp.get_context('spawn')
        parent, child = context.Pipe()
        process = context.Process(target=_switch_worker, args=(child,), name='DesktopSwitch')
        try:
            process.start()
        except Exception:
            parent.close(); child.close()
            raise
        child.close()
        self.process, self.connection, self.pending = process, parent, True
        self.started = time.monotonic()

    def poll(self):
        messages = super().poll()
        if self.pending and time.monotonic()-self.started > 8:
            self.stop()
            messages.append(('error', 'Превышено время переключения рабочего стола.'))
        return messages

    def remaining(self):
        return 0.0
