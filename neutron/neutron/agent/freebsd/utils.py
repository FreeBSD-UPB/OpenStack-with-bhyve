import os
import threading
import time

import eventlet
from eventlet.green import subprocess
from neutron_lib import exceptions
from neutron_lib.utils import helpers
from oslo_config import cfg
from neutron.common import utils
from oslo_log import log as logging

LOG = logging.getLogger(__name__)

def addl_env_args(addl_env):
    """
        Build arguments for adding additional environment vars with env.
    """
    if addl_env is None:
        return []
    return ['env'] + ['%s=%s' % pair for pair in addl_env.items()]

def process_is_running(pid):
    """
        Find if the given PID is running in the system.
    """
    return pid and os.path.exists('/proc/%s' % pid)

def get_cmdline_from_pid(pid):
    """
        Parse the command of the process with a given PID.
    """
    if not process_is_running(pid):
        return []
    try:
        with open('/proc/%s/cmdline' % pid, 'r') as f:
            cmdline = f.readline().split('\0')[:-1]
    except IOError:
        return []

    if len(cmdline) == 1:
        cmdline = cmdline[0].split(' ')

    LOG.info("Found cmdline %s for process with PID %s.", cmdline, pid)
    return cmdline

def create_process(cmd, run_as_root=False, addl_env=None):
    """
        Create a process object for the given command.

        The return value will be a tuple of the process object and the
        list of command arguments used to create it.
    """

    cmd = list(map(str, addl_env_args(addl_env) + cmd))
    if run_as_root:
        cmd = ["sudo"] + cmd
    LOG.info("Running command: %s", cmd)
    obj = utils.subprocess_popen(cmd, shell=False,
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)

    return obj, cmd

def remove_abs_path(cmd):
    """
        Remove absolute path for a command.
    """
    if cmd and os.path.isabs(cmd[0]):
        cmd = list(cmd)
        cmd[0] = os.path.basename(cmd[0])

    return cmd

def cmd_matches_expected(cmd, expected_cmd):
    """
        Checks whether two commands match.
    """
    abs_cmd = remove_abs_path(cmd)
    abs_expected_cmd = remove_abs_path(expected_cmd)
    if abs_cmd != abs_expected_cmd:
        abs_cmd = remove_abs_path(abs_cmd[1:])
    return abs_cmd == abs_expected_cmd

def pid_invoked_with_cmdline(pid, expected_cmd):
    """
        Validate process with given PID is running with provided parameters.
    """
    cmd = get_cmdline_from_pid(pid)
    return cmd_matches_expected(cmd, expected_cmd)

def execute(cmd, process_input=None, addl_env=None,
            check_exit_code=True, return_stderr=False, log_fail_as_error=True,
            extra_ok_codes=None, run_as_root=False):
    try:
        if process_input is not None:
            _process_input = encodeutils.to_utf8(process_input)
        else:
            _process_input = None
        if run_as_root:
            cmd = ["sudo"] + cmd
        obj, cmd = create_process(cmd, run_as_root=run_as_root,
                                  addl_env=addl_env)
        _stdout, _stderr = obj.communicate(_process_input)
        returncode = obj.returncode
        obj.stdin.close()
        _stdout = helpers.safe_decode_utf8(_stdout)
        _stderr = helpers.safe_decode_utf8(_stderr)

        extra_ok_codes = extra_ok_codes or []
        if returncode and returncode not in extra_ok_codes:
            msg = _("Exit code: %(returncode)d; "
                    "Stdin: %(stdin)s; "
                    "Stdout: %(stdout)s; "
                    "Stderr: %(stderr)s") % {
                            'returncode': returncode,
                            'stdin': process_input or '',
                            'stdout': _stdout,
                            'stderr': _stderr}

            if log_fail_as_error:
                LOG.error(msg)
            if check_exit_code:
                raise exceptions.ProcessExecutionError(msg,
                                                       returncode=returncode)

    finally:
        time.sleep(0)

    return (_stdout, _stderr) if return_stderr else _stdout

def kill_process(pid, signal, run_as_root=False):
    """
        Kill the process with the given PID using the given signal.
    """
    try:
        execute(['kill', '-%d' % signal, pid], run_as_root=run_as_root)
    except exceptions.ProcessExecutionError:
        if process_is_running(pid):
            raise

def get_root_helper_child_pid():
    pass
