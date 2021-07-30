# Copyright 2013 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import signal

import eventlet
import eventlet.event
from eventlet.green import subprocess
import eventlet.queue
from neutron_lib.utils import helpers
from oslo_log import log as logging

from neutron._i18n import _
from neutron.agent.common import ip_lib
from neutron.agent.common import utils
from neutron.common import utils as common_utils


LOG = logging.getLogger(__name__)


class AsyncProcessException(Exception):
    pass


class AsyncProcess(object):
    """Manages an asynchronous process.

    This class spawns a new process via subprocess and uses
    greenthreads to read stderr and stdout asynchronously into queues
    that can be read via repeatedly calling iter_stdout() and
    iter_stderr().

    If respawn_interval is non-zero, any error in communicating with
    the managed process will result in the process and greenthreads
    being cleaned up and the process restarted after the specified
    interval.

    Example usage:

    >>> import time
    >>> proc = AsyncProcess(['ping'])
    >>> proc.start()
    >>> time.sleep(5)
    >>> proc.stop()
    >>> for line in proc.iter_stdout():
    ...     print(line)
    """

    def __init__(self, cmd, run_as_root=False, respawn_interval=None,
                 namespace=None, log_output=False, die_on_error=False):
        """Constructor.

        :param cmd: The list of command arguments to invoke.
        :param run_as_root: The process should run with elevated privileges.
        :param respawn_interval: Optional, the interval in seconds to wait
               to respawn after unexpected process death. Respawn will
               only be attempted if a value of 0 or greater is provided.
        :param namespace: Optional, start the command in the specified
               namespace.
        :param log_output: Optional, also log received output.
        :param die_on_error: Optional, kills the process on stderr output.
        """
        self.cmd_without_namespace = cmd
        self._cmd = ip_lib.add_namespace_to_cmd(cmd, namespace)
        self.run_as_root = run_as_root
        if respawn_interval is not None and respawn_interval < 0:
            raise ValueError(_('respawn_interval must be >= 0 if provided.'))
        self.respawn_interval = respawn_interval
        self._process = None
        self._pid = None
        self._is_running = False
        self._kill_event = None
        self._reset_queues()
        self._watchers = []
        self.log_output = log_output
        self.die_on_error = die_on_error

    @property
    def cmd(self):
        return ' '.join(self._cmd)

    def _reset_queues(self):
        self._stdout_lines = eventlet.queue.LightQueue()
        self._stderr_lines = eventlet.queue.LightQueue()

    def is_active(self):
        # If using sudo rootwrap as a root_helper, we have to wait until sudo
        # spawns rootwrap and rootwrap spawns the process. self.pid will make
        # sure to get the correct pid.
        return utils.pid_invoked_with_cmdline(
            self.pid, self.cmd_without_namespace)

    def start(self, block=False):
        """Launch a process and monitor it asynchronously.

        :param block: Block until the process has started.
        :raises utils.WaitTimeout if blocking is True and the process
                did not start in time.
        """
        LOG.debug('Launching async process [%s].', self.cmd)
        if self._is_running:
            raise AsyncProcessException(_('Process is already started'))
        else:
            self._spawn()

        if block:
            common_utils.wait_until_true(self.is_active)

    def stop(self, block=False, kill_signal=None, kill_timeout=None):
        """Halt the process and watcher threads.

        :param block: Block until the process has stopped.
        :param kill_signal: Number of signal that will be sent to the process
                            when terminating the process
        :param kill_timeout: If given, process will be killed with SIGKILL
                             if timeout will be reached and process will
                             still be running
        :raises utils.WaitTimeout if blocking is True and the process
                did not stop in time.
        """
        kill_signal = kill_signal or getattr(signal, 'SIGKILL', signal.SIGTERM)
        if self._is_running:
            LOG.debug('Halting async process [%s].', self.cmd)
            self._kill(kill_signal, kill_timeout)
        else:
            raise AsyncProcessException(_('Process is not running.'))

        if block:
            common_utils.wait_until_true(lambda: not self.is_active())

    def _spawn(self):
        """Spawn a process and its watchers."""
        self._is_running = True
        self._pid = None
        self._kill_event = eventlet.event.Event()
        self._process, cmd = utils.create_process(self._cmd,
                                                  run_as_root=self.run_as_root)
        self._watchers = []
        for reader in (self._read_stdout, self._read_stderr):
            # Pass the stop event directly to the greenthread to
            # ensure that assignment of a new event to the instance
            # attribute does not prevent the greenthread from using
            # the original event.
            watcher = eventlet.spawn(self._watch_process,
                                     reader,
                                     self._kill_event)
            self._watchers.append(watcher)

    @property
    def pid(self):
        if self._process:
            if not self._pid:
                self._pid = utils.get_root_helper_child_pid(
                    self._process.pid,
                    self.cmd_without_namespace,
                    run_as_root=self.run_as_root)
            return self._pid

    def _kill(self, kill_signal, kill_timeout=None):
        """Kill the process and the associated watcher greenthreads."""
        pid = self.pid
        if pid:
            self._is_running = False
            self._pid = None
            self._kill_process_and_wait(pid, kill_signal, kill_timeout)

        # Halt the greenthreads if they weren't already.
        if self._kill_event:
            self._kill_event.send()
            self._kill_event = None

    def _kill_process_and_wait(self, pid, kill_signal, kill_timeout=None):
        kill_result = self._kill_process(pid, kill_signal)
        if kill_result is False:
            return kill_result

        if self._process:
            try:
                self._process.wait(kill_timeout)
            except subprocess.TimeoutExpired:
                LOG.warning("Process %(pid)s [%(cmd)s] still running after "
                            "%(timeout)d seconds. Sending %(signal)d to kill "
                            "it.",
                            {'pid': pid,
                             'cmd': self.cmd,
                             'timeout': kill_timeout,
                             'signal': signal.SIGKILL})
                return self._kill_process(pid, signal.SIGKILL)
        return True

    def _kill_process(self, pid, kill_signal):
        try:
            # A process started by a root helper will be running as
            # root and need to be killed via the same helper.
            utils.kill_process(pid, kill_signal, self.run_as_root)
        except Exception:
            LOG.exception('An error occurred while killing [%s].',
                          self.cmd)
            return False
        return True

    def _handle_process_error(self):
        """Kill the async process and respawn if necessary."""
        stdout = list(self.iter_stdout())
        stderr = list(self.iter_stderr())
        LOG.debug('Halting async process [%s] in response to an error. stdout:'
                  ' [%s] - stderr: [%s]', self.cmd, stdout, stderr)
        self._kill(getattr(signal, 'SIGKILL', signal.SIGTERM))
        if self.respawn_interval is not None and self.respawn_interval >= 0:
            eventlet.sleep(self.respawn_interval)
            LOG.debug('Respawning async process [%s].', self.cmd)
            try:
                self.start()
            except AsyncProcessException:
                # Process was already respawned by someone else...
                pass

    def _watch_process(self, callback, kill_event):
        while not kill_event.ready():
            try:
                output = callback()
                if not output and output != "":
                    break
            except Exception:
                LOG.exception('An error occurred while communicating '
                              'with async process [%s].', self.cmd)
                break
            # Ensure that watching a process with lots of output does
            # not block execution of other greenthreads.
            eventlet.sleep()
        # self._is_running being True indicates that the loop was
        # broken out of due to an error in the watched process rather
        # than the loop condition being satisfied.
        if self._is_running:
            self._is_running = False
            self._handle_process_error()

    def _read(self, stream, queue):
        data = stream.readline()
        if data:
            data = helpers.safe_decode_utf8(data.strip())
            queue.put(data)
            return data

    def _read_stdout(self):
        data = self._read(self._process.stdout, self._stdout_lines)
        if self.log_output:
            LOG.debug('Output received from [%(cmd)s]: %(data)s',
                      {'cmd': self.cmd,
                       'data': data})
        return data

    def _read_stderr(self):
        data = self._read(self._process.stderr, self._stderr_lines)
        if self.log_output:
            LOG.error('Error received from [%(cmd)s]: %(err)s',
                      {'cmd': self.cmd,
                       'err': data})
        if self.die_on_error:
            LOG.error("Process [%(cmd)s] dies due to the error: %(err)s",
                      {'cmd': self.cmd,
                       'err': data})
            # the callback caller will use None to indicate the need to bail
            # out of the thread
            return None

        return data

    def _iter_queue(self, queue, block):
        while True:
            try:
                yield queue.get(block=block)
            except eventlet.queue.Empty:
                break

    def iter_stdout(self, block=False):
        return self._iter_queue(self._stdout_lines, block)

    def iter_stderr(self, block=False):
        return self._iter_queue(self._stderr_lines, block)
