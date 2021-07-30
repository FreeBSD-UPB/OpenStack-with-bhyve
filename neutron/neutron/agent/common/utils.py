# Copyright 2015 Cloudbase Solutions.
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

import os
import socket
import platform

from neutron_lib.utils import runtime
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from neutron.conf.agent import common as config
from neutron.conf.agent.database import agents_db


if os.name == 'nt':
    from neutron.agent.windows import utils
#elif platform.system().lower() == "freebsd":
#    from neutron.agent.freebsd import utils
else:
    from neutron.agent.linux import utils


LOG = logging.getLogger(__name__)
config.register_root_helper(cfg.CONF)
agents_db.register_db_agents_opts()

INTERFACE_NAMESPACE = 'neutron.interface_drivers'


create_process = utils.create_process
kill_process = utils.kill_process
execute = utils.execute
get_root_helper_child_pid = utils.get_root_helper_child_pid
pid_invoked_with_cmdline = utils.pid_invoked_with_cmdline


def load_interface_driver(conf, get_networks_callback=None):
    """Load interface driver for agents like DHCP or L3 agent.

    :param conf: Driver configuration object
    :param get_networks_callback: A callback to get network information.
                                  This will be passed as additional keyword
                                  argument to the interface driver.
    :raises SystemExit of 1 if driver cannot be loaded
    """

    try:
        loaded_class = runtime.load_class_by_alias_or_classname(
                INTERFACE_NAMESPACE, conf.interface_driver)
        return loaded_class(conf, get_networks_callback=get_networks_callback)
    except ImportError:
        LOG.error("Error loading interface driver '%s'",
                  conf.interface_driver)
        raise SystemExit(1)


def is_agent_down(heart_beat_time):
    return timeutils.is_older_than(heart_beat_time,
                                   cfg.CONF.agent_down_time)


def default_rp_hypervisors(hypervisors, device_mappings):
    """Fill config option 'resource_provider_hypervisors' with defaults.

    Default hypervisor names to socket.gethostname(). Since libvirt knows
    itself by the same name, the default is good for libvirt.

    :param hypervisors: Config option 'resource_provider_hypervisors'
        as parsed by oslo.config, that is a dict with keys of physical devices
        and values of hypervisor names.
    :param device_mappings: Device mappings standardized to the list-valued
        format.
    """
    default_hypervisor = socket.gethostname()
    rv = {}
    for _physnet, devices in device_mappings.items():
        for device in devices:
            if device in hypervisors:
                rv[device] = hypervisors[device]
            else:
                rv[device] = default_hypervisor
    return rv
