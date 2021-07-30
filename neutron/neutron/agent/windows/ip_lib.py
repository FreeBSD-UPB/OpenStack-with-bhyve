# Copyright 2016 Cloudbase Solutions.
# All Rights Reserved.
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

import netifaces

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class IPWrapper(object):

    def get_device_by_ip(self, ip):
        if not ip:
            return

        for device in self.get_devices():
            if device.device_has_ip(ip):
                return device

    def get_devices(self):
        try:
            return [IPDevice(iface) for iface in netifaces.interfaces()]
        except (OSError, MemoryError):
            LOG.error("Failed to get network interfaces.")
            return []


class IPDevice(object):

    def __init__(self, name):
        self.name = name
        self.link = IPLink(self)

    def read_ifaddresses(self):
        try:
            device_addresses = netifaces.ifaddresses(self.name)
        except ValueError:
            LOG.error("The device does not exist on the system: %s.",
                      self.name)
            return
        except OSError:
            LOG.error("Failed to get interface addresses: %s.",
                      self.name)
            return
        return device_addresses

    def device_has_ip(self, ip):
        device_addresses = self.read_ifaddresses()
        if device_addresses is None:
            return False

        addresses = [ip_addr['addr'] for ip_addr in
                     device_addresses.get(netifaces.AF_INET, []) +
                     device_addresses.get(netifaces.AF_INET6, [])]
        return ip in addresses


class IPLink(object):

    def __init__(self, parent):
        self._parent = parent

    @property
    def address(self):
        device_addresses = self._parent.read_ifaddresses()
        if device_addresses is None:
            return False
        return [eth_addr['addr'] for eth_addr in
                device_addresses.get(netifaces.AF_LINK, [])]


def add_namespace_to_cmd(cmd, namespace=None):
    """Add an optional namespace to the command."""

    return cmd
