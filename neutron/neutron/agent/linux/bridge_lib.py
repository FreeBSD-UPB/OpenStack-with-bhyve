# Copyright 2015 Intel Corporation.
# Copyright 2015 Isaku Yamahata <isaku.yamahata at intel com>
#                               <isaku.yamahata at gmail com>
# All Rights Reserved.
#
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

import os

from oslo_utils import excutils

from neutron.agent.linux import ip_lib

# NOTE(toabctl): Don't use /sys/devices/virtual/net here because not all tap
# devices are listed here (i.e. when using Xen)
BRIDGE_FS = "/sys/class/net/"
BRIDGE_INTERFACE_FS = BRIDGE_FS + "%(bridge)s/brif/%(interface)s"
BRIDGE_INTERFACES_FS = BRIDGE_FS + "%s/brif/"
BRIDGE_PORT_FS_FOR_DEVICE = BRIDGE_FS + "%s/brport"
BRIDGE_PATH_FOR_DEVICE = BRIDGE_PORT_FS_FOR_DEVICE + '/bridge'


def is_bridged_interface(interface):
    if not interface:
        return False
    else:
        return os.path.exists(BRIDGE_PORT_FS_FOR_DEVICE % interface)


def get_interface_ifindex(interface):
    try:
        with open(os.path.join(BRIDGE_FS, interface, 'ifindex'), 'r') as fh:
            return int(fh.read().strip())
    except (IOError, ValueError):
        pass


def get_bridge_names():
    return os.listdir(BRIDGE_FS)


class BridgeDevice(ip_lib.IPDevice):
    def _ip_link(self, cmd):
        cmd = ['ip', 'link'] + cmd
        ip_wrapper = ip_lib.IPWrapper(self.namespace)
        return ip_wrapper.netns.execute(cmd, run_as_root=True)

    @classmethod
    def addbr(cls, name, namespace=None):
        bridge = cls(name, namespace, 'bridge')
        try:
            bridge.link.create()
        except RuntimeError:
            with excutils.save_and_reraise_exception() as ectx:
                ectx.reraise = not bridge.exists()
        return bridge

    @classmethod
    def get_interface_bridge(cls, interface):
        try:
            path = os.readlink(BRIDGE_PATH_FOR_DEVICE % interface)
        except OSError:
            return None
        else:
            name = path.rpartition('/')[-1]
            return cls(name)

    def delbr(self):
        return self.link.delete()

    def addif(self, interface):
        return self._ip_link(['set', 'dev', interface, 'master', self.name])

    def delif(self, interface):
        return self._ip_link(['set', 'dev', interface, 'nomaster'])

    def setfd(self, fd):
        return self._ip_link(['set', 'dev', self.name, 'type', 'bridge',
                              'forward_delay', str(fd)])

    def disable_stp(self):
        return self._ip_link(['set', 'dev', self.name, 'type', 'bridge',
                              'stp_state', 0])

    def owns_interface(self, interface):
        return os.path.exists(
            BRIDGE_INTERFACE_FS % {'bridge': self.name,
                                   'interface': interface})

    def get_interfaces(self):
        try:
            return os.listdir(BRIDGE_INTERFACES_FS % self.name)
        except OSError:
            return []


class FdbInterface(object):
    """provide basic functionality to edit the FDB table"""

    @staticmethod
    def _execute_bridge(cmd, namespace, **kwargs):
        ip_wrapper = ip_lib.IPWrapper(namespace)
        return ip_wrapper.netns.execute(cmd, run_as_root=True, **kwargs)

    @classmethod
    def _cmd(cls, op, mac, dev, ip_dst, namespace, **kwargs):
        cmd = ['bridge', 'fdb', op, mac, 'dev', dev]
        if ip_dst is not None:
            cmd += ['dst', ip_dst]
        cls._execute_bridge(cmd, namespace, **kwargs)

    @classmethod
    def add(cls, mac, dev, ip_dst=None, namespace=None, **kwargs):
        return cls._cmd('add', mac, dev, ip_dst, namespace, **kwargs)

    @classmethod
    def append(cls, mac, dev, ip_dst=None, namespace=None, **kwargs):
        return cls._cmd('append', mac, dev, ip_dst, namespace, **kwargs)

    @classmethod
    def replace(cls, mac, dev, ip_dst=None, namespace=None, **kwargs):
        return cls._cmd('replace', mac, dev, ip_dst, namespace, **kwargs)

    @classmethod
    def delete(cls, mac, dev, ip_dst=None, namespace=None, **kwargs):
        return cls._cmd('delete', mac, dev, ip_dst, namespace, **kwargs)

    @classmethod
    def show(cls, dev=None, namespace=None, **kwargs):
        cmd = ['bridge', 'fdb', 'show']
        if dev:
            cmd += ['dev', dev]
        return cls._execute_bridge(cmd, namespace, **kwargs)
