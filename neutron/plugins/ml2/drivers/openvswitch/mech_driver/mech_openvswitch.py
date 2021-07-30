# Copyright (c) 2013 OpenStack Foundation
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
import uuid

from neutron_lib.api.definitions import portbindings
from neutron_lib.api.definitions import provider_net
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib import constants
from oslo_config import cfg
from oslo_log import log

from neutron._i18n import _
from neutron.agent import securitygroups_rpc
from neutron.conf.plugins.ml2.drivers.openvswitch import mech_ovs_conf
from neutron.plugins.ml2.drivers import mech_agent
from neutron.plugins.ml2.drivers.openvswitch.agent.common \
    import constants as a_const
from neutron.services.logapi.drivers.openvswitch import driver as log_driver
from neutron.services.qos.drivers.openvswitch import driver as ovs_qos_driver

LOG = log.getLogger(__name__)

IPTABLES_FW_DRIVER_FULL = ("neutron.agent.linux.iptables_firewall."
                           "OVSHybridIptablesFirewallDriver")

mech_ovs_conf.register_ovs_mech_driver_opts()


class OpenvswitchMechanismDriver(mech_agent.SimpleAgentMechanismDriverBase):
    """Attach to networks using openvswitch L2 agent.

    The OpenvswitchMechanismDriver integrates the ml2 plugin with the
    openvswitch L2 agent. Port binding with this driver requires the
    openvswitch agent to be running on the port's host, and that agent
    to have connectivity to at least one segment of the port's
    network.
    """

    resource_provider_uuid5_namespace = uuid.UUID(
        '87ee7d5c-73bb-11e8-9008-c4d987b2a692')

    def __init__(self):
        sg_enabled = securitygroups_rpc.is_firewall_enabled()
        hybrid_plug_required = (
            not cfg.CONF.SECURITYGROUP.firewall_driver or
            cfg.CONF.SECURITYGROUP.firewall_driver in (
                IPTABLES_FW_DRIVER_FULL, 'iptables_hybrid')
        ) and sg_enabled
        vif_details = {portbindings.CAP_PORT_FILTER: sg_enabled,
                       portbindings.OVS_HYBRID_PLUG: hybrid_plug_required,
                       portbindings.VIF_DETAILS_CONNECTIVITY:
                           portbindings.CONNECTIVITY_L2}
        # NOTE(moshele): Bind DIRECT (SR-IOV) port allows
        # to offload the OVS flows using tc to the SR-IOV NIC.
        # We are using OVS mechanism driver because the openvswitch (>=2.8.0)
        # support hardware offload via tc and that allow us to manage the VF by
        # OpenFlow control plane using representor net-device.
        super(OpenvswitchMechanismDriver, self).__init__(
            constants.AGENT_TYPE_OVS,
            portbindings.VIF_TYPE_OVS,
            vif_details)

        # TODO(lajoskatona): move this blacklisting to
        # SimpleAgentMechanismDriverBase. By that e blacklisting and validation
        # of the vnic_types would be available for all mechanism drivers.
        self.supported_vnic_types = self.blacklist_supported_vnic_types(
            vnic_types=[portbindings.VNIC_NORMAL,
                        portbindings.VNIC_DIRECT,
                        portbindings.VNIC_SMARTNIC],
            blacklist=cfg.CONF.OVS_DRIVER.vnic_type_blacklist
        )
        LOG.info("%s's supported_vnic_types: %s",
                 self.agent_type, self.supported_vnic_types)

        ovs_qos_driver.register()
        log_driver.register()

    def get_allowed_network_types(self, agent):
        return (agent['configurations'].get('tunnel_types', []) +
                [constants.TYPE_LOCAL, constants.TYPE_FLAT,
                 constants.TYPE_VLAN])

    def get_mappings(self, agent):
        return agent['configurations'].get('bridge_mappings', {})

    def get_standard_device_mappings(self, agent):
        """Return the agent's bridge mappings in a standard way.

        The common format for OVS and SRIOv mechanism drivers:
        {'physnet_name': ['device_or_bridge_1', 'device_or_bridge_2']}

        :param agent: The agent
        :returns A dict in the format: {'physnet_name': ['bridge_or_device']}
        :raises ValueError: if there is no bridge_mappings key in
                            agent['configurations']
        """
        if 'bridge_mappings' in agent['configurations']:
            return {k: [v] for k, v in
                    agent['configurations']['bridge_mappings'].items()}
        else:
            raise ValueError(_('Cannot standardize bridge mappings of agent '
                               'type: %s'), agent['agent_type'])

    def check_vlan_transparency(self, context):
        """Currently Openvswitch driver doesn't support vlan transparency."""
        return False

    def bind_port(self, context):
        vnic_type = context.current.get(portbindings.VNIC_TYPE,
                                        portbindings.VNIC_NORMAL)
        profile = context.current.get(portbindings.PROFILE)
        capabilities = []
        if profile:
            capabilities = profile.get('capabilities', [])
        if (vnic_type == portbindings.VNIC_DIRECT and
                'switchdev' not in capabilities):
            LOG.debug("Refusing to bind due to unsupported vnic_type: %s with "
                      "no switchdev capability", portbindings.VNIC_DIRECT)
            return
        super(OpenvswitchMechanismDriver, self).bind_port(context)

    def get_supported_vif_type(self, agent):
        caps = agent['configurations'].get('ovs_capabilities', {})
        if (any(x in caps.get('iface_types', []) for x
                in [a_const.OVS_DPDK_VHOST_USER,
                    a_const.OVS_DPDK_VHOST_USER_CLIENT]) and
                agent['configurations'].get('datapath_type') ==
                a_const.OVS_DATAPATH_NETDEV):
            return portbindings.VIF_TYPE_VHOST_USER
        return self.vif_type

    def get_vif_type(self, context, agent, segment):
        if (context.current.get(portbindings.VNIC_TYPE) ==
                portbindings.VNIC_DIRECT):
            return portbindings.VIF_TYPE_OVS
        return self.get_supported_vif_type(agent)

    def get_vhost_mode(self, iface_types):
        # NOTE(sean-k-mooney): this function converts the ovs vhost user
        # driver mode into the qemu vhost user mode. If OVS is the server,
        # qemu is the client and vice-versa.
        if (a_const.OVS_DPDK_VHOST_USER_CLIENT in iface_types):
            return portbindings.VHOST_USER_MODE_SERVER
        return portbindings.VHOST_USER_MODE_CLIENT

    def get_vif_details(self, context, agent, segment):
        vif_details = self._pre_get_vif_details(agent, context)
        self._set_bridge_name(context.current, vif_details, agent)
        return vif_details

    @staticmethod
    def _set_bridge_name(port, vif_details, agent):
        # REVISIT(rawlin): add BridgeName as a nullable column to the Port
        # model and simply check here if it's set and insert it into the
        # vif_details.

        def set_bridge_name_inner(bridge_name):
            vif_details[portbindings.VIF_DETAILS_BRIDGE_NAME] = bridge_name

        bridge_name = agent['configurations'].get('integration_bridge')
        if bridge_name:
            vif_details[portbindings.VIF_DETAILS_BRIDGE_NAME] = bridge_name

        registry.publish(
            a_const.OVS_BRIDGE_NAME, events.BEFORE_READ,
            set_bridge_name_inner,
            payload=events.EventPayload(None, metadata={'port': port}))

    def _pre_get_vif_details(self, agent, context):
        a_config = agent['configurations']
        vif_type = self.get_vif_type(context, agent, segment=None)
        if vif_type != portbindings.VIF_TYPE_VHOST_USER:
            details = dict(self.vif_details)
            hybrid = portbindings.OVS_HYBRID_PLUG
            if hybrid in a_config:
                # we only override the vif_details for hybrid plugging set
                # in the constructor if the agent specifically requests it
                details[hybrid] = a_config[hybrid]
        else:
            sock_path = self.agent_vhu_sockpath(agent, context.current['id'])
            caps = a_config.get('ovs_capabilities', {})
            mode = self.get_vhost_mode(caps.get('iface_types', []))
            details = {portbindings.CAP_PORT_FILTER: False,
                       portbindings.OVS_HYBRID_PLUG: False,
                       portbindings.VHOST_USER_MODE: mode,
                       portbindings.VHOST_USER_OVS_PLUG: True,
                       portbindings.VHOST_USER_SOCKET: sock_path}
        details[portbindings.OVS_DATAPATH_TYPE] = a_config.get(
            'datapath_type', a_const.OVS_DATAPATH_SYSTEM)
        return details

    @staticmethod
    def agent_vhu_sockpath(agent, port_id):
        """Return the agent's vhost-user socket path for a given port"""
        sockdir = agent['configurations'].get('vhostuser_socket_dir',
                                              a_const.VHOST_USER_SOCKET_DIR)
        sock_name = (constants.VHOST_USER_DEVICE_PREFIX + port_id)[:14]
        return os.path.join(sockdir, sock_name)

    @staticmethod
    def provider_network_attribute_updates_supported():
        return [provider_net.SEGMENTATION_ID]
