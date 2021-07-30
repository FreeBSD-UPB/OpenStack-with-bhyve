# Copyright 2015 Red Hat, Inc.
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

import functools

from neutron_lib import constants
from neutron_lib.services.qos import constants as qos_consts
from neutronclient.common import exceptions
from oslo_utils import uuidutils

from neutron.agent.common import ovs_lib
from neutron.agent.linux import tc_lib
from neutron.common import utils
from neutron.tests.common.agents import l2_extensions
from neutron.tests.fullstack import base
from neutron.tests.fullstack.resources import config as fullstack_config
from neutron.tests.fullstack.resources import environment
from neutron.tests.fullstack.resources import machine
from neutron.tests.unit import testlib_api

from neutron.conf.plugins.ml2.drivers import linuxbridge as \
    linuxbridge_agent_config
from neutron.plugins.ml2.drivers.linuxbridge.agent import \
    linuxbridge_neutron_agent as linuxbridge_agent
from neutron.services.qos.drivers.linuxbridge import driver as lb_drv
from neutron.services.qos.drivers.openvswitch import driver as ovs_drv


load_tests = testlib_api.module_load_tests

BANDWIDTH_BURST = 100
BANDWIDTH_LIMIT = 500
MIN_BANDWIDTH = 300
DSCP_MARK = 16


class BaseQoSRuleTestCase(object):
    number_of_hosts = 1
    physical_network = None

    @property
    def reverse_direction(self):
        if self.direction == constants.INGRESS_DIRECTION:
            return constants.EGRESS_DIRECTION
        elif self.direction == constants.EGRESS_DIRECTION:
            return constants.INGRESS_DIRECTION

    def setUp(self):
        host_desc = [
            environment.HostDescription(
                l3_agent=False,
                l2_agent_type=self.l2_agent_type
            ) for _ in range(self.number_of_hosts)]
        env_desc = environment.EnvironmentDescription(
            agent_down_time=10,
            qos=True)
        env = environment.Environment(env_desc, host_desc)
        super(BaseQoSRuleTestCase, self).setUp(env)
        self.l2_agent_process = self.environment.hosts[0].l2_agent
        self.l2_agent = self.safe_client.client.list_agents(
            agent_type=self.l2_agent_type)['agents'][0]

        self.tenant_id = uuidutils.generate_uuid()
        network_args = {}
        if self.physical_network:
            network_args = {'physical_network': self.physical_network,
                            'network_type': 'vlan'}
        self.network = self.safe_client.create_network(
            self.tenant_id, name='network-test', **network_args)
        self.subnet = self.safe_client.create_subnet(
            self.tenant_id, self.network['id'],
            cidr='10.0.0.0/24',
            gateway_ip='10.0.0.1',
            name='subnet-test',
            enable_dhcp=False)

    def _create_qos_policy(self):
        return self.safe_client.create_qos_policy(
            self.tenant_id, 'fs_policy', 'Fullstack testing policy',
            shared='False', is_default='False')

    def _prepare_vm_with_qos_policy(self, rule_add_functions):
        qos_policy = self._create_qos_policy()
        qos_policy_id = qos_policy['id']

        port = self.safe_client.create_port(
            self.tenant_id, self.network['id'],
            self.environment.hosts[0].hostname,
            qos_policy_id)

        for rule_add in rule_add_functions:
            rule_add(qos_policy)

        vm = self.useFixture(
            machine.FakeFullstackMachine(
                self.environment.hosts[0],
                self.network['id'],
                self.tenant_id,
                self.safe_client,
                neutron_port=port))

        return vm, qos_policy


class _TestBwLimitQoS(BaseQoSRuleTestCase):

    number_of_hosts = 1

    @staticmethod
    def _get_expected_egress_burst_value(limit):
        return int(
            limit * qos_consts.DEFAULT_BURST_RATE
        )

    def _wait_for_bw_rule_removed(self, vm, direction):
        # No values are provided when port doesn't have qos policy
        self._wait_for_bw_rule_applied(vm, None, None, direction)

    def _add_bw_limit_rule(self, limit, burst, direction, qos_policy):
        qos_policy_id = qos_policy['id']
        rule = self.safe_client.create_bandwidth_limit_rule(
            self.tenant_id, qos_policy_id, limit, burst, direction)
        # Make it consistent with GET reply
        rule['type'] = qos_consts.RULE_TYPE_BANDWIDTH_LIMIT
        rule['qos_policy_id'] = qos_policy_id
        qos_policy['rules'].append(rule)

    def _create_vm_with_limit_rules(self):
        # Create port with qos policy attached, with different direction
        vm, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(
                self._add_bw_limit_rule,
                BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction),
             functools.partial(
                self._add_bw_limit_rule,
                BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.reverse_direction)])

        self._wait_for_bw_rule_applied(
            vm, BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction)
        self._wait_for_bw_rule_applied(
            vm, BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.reverse_direction)
        return vm, qos_policy

    def _restart_agent_and_check_rules_applied(self, policy_id, vm,
                                               final_rules,
                                               add_rules=None,
                                               update_rules=None,
                                               delete_rules=None):
        # final_rules: the last valid rule after all operations
        # (clear/update/reset rules during the l2-agent stop) are completed.
        # add_rules: rules that need to be added during the l2-agent stop.
        # update_rules: rules that need to be updated during the l2-agent stop.
        # delete_rules:rules that need to be deleted during the l2-agent stop.

        add_rules = list() if not add_rules else add_rules
        update_rules = list() if not update_rules else update_rules
        delete_rules = list() if not delete_rules else delete_rules
        # Stop l2_agent and clear/update/reset the port qos rules
        self.l2_agent_process.stop()
        self._wait_until_agent_down(self.l2_agent['id'])

        for rule in delete_rules:
            self.client.delete_bandwidth_limit_rule(rule['id'],
                                                    policy_id)

        for rule in add_rules:
            self.safe_client.create_bandwidth_limit_rule(
                self.tenant_id, policy_id,
                rule.get('limit'), rule.get('burst'), rule['direction'])

        for rule in update_rules:
            self.client.update_bandwidth_limit_rule(
                rule['id'], policy_id,
                body={'bandwidth_limit_rule':
                      {'max_kbps': rule.get('limit'),
                       'max_burst_kbps': rule.get('burst'),
                       'direction': rule.get('direction')}})

        # Start l2_agent to check if these rules is cleared
        self.l2_agent_process.start()
        self._wait_until_agent_up(self.l2_agent['id'])

        all_directions = set([self.direction, self.reverse_direction])
        for final_rule in final_rules:
            all_directions -= set([final_rule['direction']])
            self._wait_for_bw_rule_applied(
                vm, final_rule.get('limit'),
                final_rule.get('burst'), final_rule['direction'])
        # Make sure there are no other rules.
        for direction in list(all_directions):
            self._wait_for_bw_rule_applied(vm, None, None, direction)

    def test_bw_limit_qos_policy_rule_lifecycle(self):
        new_limit = BANDWIDTH_LIMIT + 100

        # Create port with qos policy attached
        vm, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(
                self._add_bw_limit_rule,
                BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction)])
        bw_rule = qos_policy['rules'][0]

        self._wait_for_bw_rule_applied(
            vm, BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction)
        qos_policy_id = qos_policy['id']

        self.client.delete_bandwidth_limit_rule(bw_rule['id'], qos_policy_id)
        self._wait_for_bw_rule_removed(vm, self.direction)

        # Create new rule with no given burst value, in such case ovs and lb
        # agent should apply burst value as
        # bandwidth_limit * qos_consts.DEFAULT_BURST_RATE
        new_expected_burst = self._get_expected_burst_value(new_limit,
                                                            self.direction)
        new_rule = self.safe_client.create_bandwidth_limit_rule(
            self.tenant_id, qos_policy_id, new_limit, direction=self.direction)
        self._wait_for_bw_rule_applied(
            vm, new_limit, new_expected_burst, self.direction)

        # Update qos policy rule id
        self.client.update_bandwidth_limit_rule(
            new_rule['id'], qos_policy_id,
            body={'bandwidth_limit_rule': {'max_kbps': BANDWIDTH_LIMIT,
                                           'max_burst_kbps': BANDWIDTH_BURST}})
        self._wait_for_bw_rule_applied(
            vm, BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction)

        # Remove qos policy from port
        self.client.update_port(
            vm.neutron_port['id'],
            body={'port': {'qos_policy_id': None}})
        self._wait_for_bw_rule_removed(vm, self.direction)

    def test_bw_limit_direction_change(self):
        # Create port with qos policy attached, with rule self.direction
        vm, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(
                self._add_bw_limit_rule,
                BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction)])
        bw_rule = qos_policy['rules'][0]

        self._wait_for_bw_rule_applied(
            vm, BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction)

        # Update rule by changing direction to opposite then it was before
        self.client.update_bandwidth_limit_rule(
            bw_rule['id'], qos_policy['id'],
            body={'bandwidth_limit_rule': {
                'direction': self.reverse_direction}})
        self._wait_for_bw_rule_removed(vm, self.direction)
        self._wait_for_bw_rule_applied(
            vm, BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.reverse_direction)

    def test_bw_limit_qos_no_rules_l2_agent_restart(self):
        vm, qos_policy = self._create_vm_with_limit_rules()

        bw_rule_1 = qos_policy['rules'][0]
        bw_rule_2 = qos_policy['rules'][1]
        qos_policy_id = qos_policy['id']

        # final_rules indicates the last valid rule after all operations
        # (clear/update/reset rules during the l2-agent stop) are completed
        final_rules = [{'direction': self.direction,
                        'limit': None},
                       {'direction': self.reverse_direction,
                        'limit': None}]

        self._restart_agent_and_check_rules_applied(
            qos_policy_id, vm, final_rules=final_rules,
            delete_rules=[bw_rule_1, bw_rule_2])

    def test_bw_limit_qos_rules_deleted_l2_agent_restart(self):
        vm, qos_policy = self._create_vm_with_limit_rules()

        bw_rule_1 = qos_policy['rules'][0]
        qos_policy_id = qos_policy['id']

        # final_rules indicates the last valid rule after all operations
        # (clear/update/reset rules during the l2-agent stop) are completed
        final_rules = [{'direction': self.direction,
                        'limit': None},
                       {'direction': self.reverse_direction,
                        'limit': BANDWIDTH_LIMIT,
                        'burst': BANDWIDTH_BURST}]

        self._restart_agent_and_check_rules_applied(
            qos_policy_id, vm, final_rules=final_rules,
            delete_rules=[bw_rule_1])

    def test_bw_limit_qos_rules_changed_l2_agent_restart(self):
        vm, qos_policy = self._create_vm_with_limit_rules()

        bw_rule_1 = qos_policy['rules'][0]
        bw_rule_2 = qos_policy['rules'][1]
        qos_policy_id = qos_policy['id']

        add_rules = [{'direction': self.direction,
                      'limit': BANDWIDTH_LIMIT * 2,
                      'burst': BANDWIDTH_BURST * 2},
                     {'direction': self.reverse_direction,
                      'limit': BANDWIDTH_LIMIT * 2,
                      'burst': BANDWIDTH_BURST * 2}]

        self._restart_agent_and_check_rules_applied(
            qos_policy_id, vm, final_rules=add_rules,
            add_rules=add_rules,
            delete_rules=[bw_rule_1, bw_rule_2])

    def test_bw_limit_qos_rules_updated_l2_agent_restart(self):
        vm, qos_policy = self._create_vm_with_limit_rules()

        bw_rule_1 = qos_policy['rules'][0]
        bw_rule_2 = qos_policy['rules'][1]
        qos_policy_id = qos_policy['id']

        update_rules = [{'id': bw_rule_1['id'],
                         'direction': bw_rule_1['direction'],
                         'limit': BANDWIDTH_LIMIT * 2,
                         'burst': BANDWIDTH_BURST * 2},
                        {'id': bw_rule_2['id'],
                         'direction': bw_rule_2['direction'],
                         'limit': BANDWIDTH_LIMIT * 2,
                         'burst': BANDWIDTH_BURST * 2}]

        self._restart_agent_and_check_rules_applied(
            qos_policy_id, vm, final_rules=update_rules,
            update_rules=update_rules)


class TestBwLimitQoSOvs(_TestBwLimitQoS, base.BaseFullStackTestCase):
    l2_agent_type = constants.AGENT_TYPE_OVS
    scenarios = [
        ('ingress', {'direction': constants.INGRESS_DIRECTION}),
        ('egress', {'direction': constants.EGRESS_DIRECTION})
    ]

    @staticmethod
    def _get_expected_burst_value(limit, direction):
        # For egress bandwidth limit this value should be calculated as
        # bandwidth_limit * qos_consts.DEFAULT_BURST_RATE
        if direction == constants.EGRESS_DIRECTION:
            return TestBwLimitQoSOvs._get_expected_egress_burst_value(limit)
        else:
            return 0

    def _wait_for_bw_rule_applied(self, vm, limit, burst, direction):
        if direction == constants.EGRESS_DIRECTION:
            utils.wait_until_true(
                lambda: vm.bridge.get_egress_bw_limit_for_port(
                    vm.port.name) == (limit, burst))
        elif direction == constants.INGRESS_DIRECTION:
            utils.wait_until_true(
                lambda: vm.bridge.get_ingress_bw_limit_for_port(
                    vm.port.name) == (limit, burst))

    def test_bw_limit_qos_port_removed(self):
        """Test if rate limit config is properly removed when whole port is
        removed.
        """

        # Create port with qos policy attached
        vm, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(
                self._add_bw_limit_rule,
                BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction)])
        self._wait_for_bw_rule_applied(
            vm, BANDWIDTH_LIMIT, BANDWIDTH_BURST, self.direction)

        # Delete port with qos policy attached
        vm.destroy()
        self._wait_for_bw_rule_removed(vm, self.direction)
        self.assertIsNone(vm.bridge.find_qos(vm.port.name))
        self.assertIsNone(vm.bridge.find_queue(vm.port.name,
                                               ovs_lib.QOS_DEFAULT_QUEUE))


class TestBwLimitQoSLinuxbridge(_TestBwLimitQoS, base.BaseFullStackTestCase):
    l2_agent_type = constants.AGENT_TYPE_LINUXBRIDGE
    scenarios = [
        ('egress', {'direction': constants.EGRESS_DIRECTION}),
        ('ingress', {'direction': constants.INGRESS_DIRECTION}),
    ]

    @staticmethod
    def _get_expected_burst_value(limit, direction):
        # For egress bandwidth limit this value should be calculated as
        # bandwidth_limit * qos_consts.DEFAULT_BURST_RATE
        if direction == constants.EGRESS_DIRECTION:
            return TestBwLimitQoSLinuxbridge._get_expected_egress_burst_value(
                limit)
        else:
            return TestBwLimitQoSLinuxbridge._get_expected_ingress_burst_value(
                limit)

    @staticmethod
    def _get_expected_ingress_burst_value(limit):
        return int(
            float(limit) /
            float(linuxbridge_agent_config.DEFAULT_KERNEL_HZ_VALUE))

    def _wait_for_bw_rule_applied(self, vm, limit, burst, direction):
        port_name = linuxbridge_agent.LinuxBridgeManager.get_tap_device_name(
            vm.neutron_port['id'])
        tc = tc_lib.TcCommand(
            port_name,
            linuxbridge_agent_config.DEFAULT_KERNEL_HZ_VALUE,
            namespace=vm.host.host_namespace
        )
        if direction == constants.EGRESS_DIRECTION:
            utils.wait_until_true(
                lambda: tc.get_filters_bw_limits() == (limit, burst))
        elif direction == constants.INGRESS_DIRECTION:
            utils.wait_until_true(
                lambda: tc.get_tbf_bw_limits() == (limit, burst))


class _TestDscpMarkingQoS(BaseQoSRuleTestCase):

    number_of_hosts = 2

    def _wait_for_dscp_marking_rule_removed(self, vm):
        self._wait_for_dscp_marking_rule_applied(vm, None)

    def _add_dscp_rule(self, dscp_mark, qos_policy):
        qos_policy_id = qos_policy['id']
        rule = self.safe_client.create_dscp_marking_rule(
            self.tenant_id, qos_policy_id, dscp_mark)
        # Make it consistent with GET reply
        rule['type'] = qos_consts.RULE_TYPE_DSCP_MARKING
        rule['qos_policy_id'] = qos_policy_id
        qos_policy['rules'].append(rule)

    def test_dscp_qos_policy_rule_lifecycle(self):
        new_dscp_mark = DSCP_MARK + 8

        # Create port with qos policy attached
        vm, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(self._add_dscp_rule, DSCP_MARK)])
        dscp_rule = qos_policy['rules'][0]

        self._wait_for_dscp_marking_rule_applied(vm, DSCP_MARK)
        qos_policy_id = qos_policy['id']

        self.client.delete_dscp_marking_rule(dscp_rule['id'], qos_policy_id)
        self._wait_for_dscp_marking_rule_removed(vm)

        # Create new rule
        new_rule = self.safe_client.create_dscp_marking_rule(
            self.tenant_id, qos_policy_id, new_dscp_mark)
        self._wait_for_dscp_marking_rule_applied(vm, new_dscp_mark)

        # Update qos policy rule id
        self.client.update_dscp_marking_rule(
            new_rule['id'], qos_policy_id,
            body={'dscp_marking_rule': {'dscp_mark': DSCP_MARK}})
        self._wait_for_dscp_marking_rule_applied(vm, DSCP_MARK)

        # Remove qos policy from port
        self.client.update_port(
            vm.neutron_port['id'],
            body={'port': {'qos_policy_id': None}})
        self._wait_for_dscp_marking_rule_removed(vm)

    def test_dscp_marking_packets(self):
        # Create port (vm) which will be used to received and test packets
        receiver_port = self.safe_client.create_port(
            self.tenant_id, self.network['id'],
            self.environment.hosts[1].hostname)

        receiver = self.useFixture(
            machine.FakeFullstackMachine(
                self.environment.hosts[1],
                self.network['id'],
                self.tenant_id,
                self.safe_client,
                neutron_port=receiver_port))

        # Create port with qos policy attached
        sender, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(self._add_dscp_rule, DSCP_MARK)])

        sender.block_until_boot()
        receiver.block_until_boot()

        self._wait_for_dscp_marking_rule_applied(sender, DSCP_MARK)
        l2_extensions.wait_for_dscp_marked_packet(
            sender, receiver, DSCP_MARK)

    def test_dscp_marking_clean_port_removed(self):
        """Test if DSCP marking OpenFlow/iptables rules are removed when
        whole port is removed.
        """

        # Create port with qos policy attached
        vm, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(self._add_dscp_rule, DSCP_MARK)])

        self._wait_for_dscp_marking_rule_applied(vm, DSCP_MARK)

        # Delete port with qos policy attached
        vm.destroy()
        self._wait_for_dscp_marking_rule_removed(vm)


class TestDscpMarkingQoSOvs(_TestDscpMarkingQoS, base.BaseFullStackTestCase):
    l2_agent_type = constants.AGENT_TYPE_OVS

    def _wait_for_dscp_marking_rule_applied(self, vm, dscp_mark):
        l2_extensions.wait_until_dscp_marking_rule_applied_ovs(
            vm.bridge, vm.port.name, dscp_mark)


class TestDscpMarkingQoSLinuxbridge(_TestDscpMarkingQoS,
                                    base.BaseFullStackTestCase):
    l2_agent_type = constants.AGENT_TYPE_LINUXBRIDGE

    def _wait_for_dscp_marking_rule_applied(self, vm, dscp_mark):
        l2_extensions.wait_until_dscp_marking_rule_applied_linuxbridge(
            vm.host.host_namespace, vm.port.name, dscp_mark)


class TestQoSWithL2Population(base.BaseFullStackTestCase):
    scenarios = [
        (constants.AGENT_TYPE_OVS,
         {'mech_drivers': 'openvswitch',
          'supported_rules': ovs_drv.SUPPORTED_RULES}),
        (constants.AGENT_TYPE_LINUXBRIDGE,
         {'mech_drivers': 'linuxbridge',
          'supported_rules': lb_drv.SUPPORTED_RULES})
    ]

    def setUp(self):
        host_desc = []  # No need to register agents for this test case
        env_desc = environment.EnvironmentDescription(
            qos=True, l2_pop=True, mech_drivers=self.mech_drivers)
        env = environment.Environment(env_desc, host_desc)
        super(TestQoSWithL2Population, self).setUp(env)

    def test_supported_qos_rule_types(self):
        res = self.client.list_qos_rule_types()
        rule_types = {t['type'] for t in res['rule_types']}
        expected_rules = set(self.supported_rules)
        self.assertEqual(expected_rules, rule_types)


class TestQoSPolicyIsDefault(base.BaseFullStackTestCase):

    NAME = 'fs_policy'
    DESCRIPTION = 'Fullstack testing policy'
    SHARED = True

    def setUp(self):
        host_desc = []  # No need to register agents for this test case
        env_desc = environment.EnvironmentDescription(qos=True)
        env = environment.Environment(env_desc, host_desc)
        super(TestQoSPolicyIsDefault, self).setUp(env)

    def _create_qos_policy(self, project_id, is_default):
        return self.safe_client.create_qos_policy(
            project_id, self.NAME, self.DESCRIPTION, shared=self.SHARED,
            is_default=is_default)

    def _update_qos_policy(self, qos_policy_id, is_default):
        return self.client.update_qos_policy(
            qos_policy_id, body={'policy': {'is_default': is_default}})

    def test_create_one_default_qos_policy_per_project(self):
        project_ids = [uuidutils.generate_uuid(), uuidutils.generate_uuid()]
        for project_id in project_ids:
            qos_policy = self._create_qos_policy(project_id, True)
            self.assertTrue(qos_policy['is_default'])
            self.assertEqual(project_id, qos_policy['project_id'])
            qos_policy = self._create_qos_policy(project_id, False)
            self.assertFalse(qos_policy['is_default'])
            self.assertEqual(project_id, qos_policy['project_id'])

    def test_create_two_default_qos_policies_per_project(self):
        project_id = uuidutils.generate_uuid()
        qos_policy = self._create_qos_policy(project_id, True)
        self.assertTrue(qos_policy['is_default'])
        self.assertEqual(project_id, qos_policy['project_id'])
        self.assertRaises(exceptions.Conflict,
                          self._create_qos_policy, project_id, True)

    def test_update_default_status(self):
        project_ids = [uuidutils.generate_uuid(), uuidutils.generate_uuid()]
        for project_id in project_ids:
            qos_policy = self._create_qos_policy(project_id, True)
            self.assertTrue(qos_policy['is_default'])
            qos_policy = self._update_qos_policy(qos_policy['id'], False)
            self.assertFalse(qos_policy['policy']['is_default'])

    def test_update_default_status_conflict(self):
        project_id = uuidutils.generate_uuid()
        qos_policy_1 = self._create_qos_policy(project_id, True)
        self.assertTrue(qos_policy_1['is_default'])
        qos_policy_2 = self._create_qos_policy(project_id, False)
        self.assertFalse(qos_policy_2['is_default'])
        self.assertRaises(exceptions.Conflict,
                          self._update_qos_policy, qos_policy_2['id'], True)


class _TestMinBwQoS(BaseQoSRuleTestCase):

    number_of_hosts = 1
    physical_network = fullstack_config.PHYSICAL_NETWORK_NAME

    def _wait_for_min_bw_rule_removed(self, vm, direction):
        # No values are provided when port doesn't have qos policy
        self._wait_for_min_bw_rule_applied(vm, None, direction)

    def _add_min_bw_rule(self, min_bw, direction, qos_policy):
        qos_policy_id = qos_policy['id']
        rule = self.safe_client.create_minimum_bandwidth_rule(
            self.tenant_id, qos_policy_id, min_bw, direction)
        # Make it consistent with GET reply
        rule['type'] = qos_consts.RULE_TYPE_MINIMUM_BANDWIDTH
        rule['qos_policy_id'] = qos_policy_id
        qos_policy['rules'].append(rule)

    def test_min_bw_qos_policy_rule_lifecycle(self):
        new_limit = MIN_BANDWIDTH - 100

        # Create port with qos policy attached
        vm, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(
                self._add_min_bw_rule, MIN_BANDWIDTH, self.direction)])
        bw_rule = qos_policy['rules'][0]

        self._wait_for_min_bw_rule_applied(vm, MIN_BANDWIDTH, self.direction)
        qos_policy_id = qos_policy['id']

        self.client.delete_minimum_bandwidth_rule(bw_rule['id'], qos_policy_id)
        self._wait_for_min_bw_rule_removed(vm, self.direction)

        new_rule = self.safe_client.create_minimum_bandwidth_rule(
            self.tenant_id, qos_policy_id, new_limit, direction=self.direction)
        self._wait_for_min_bw_rule_applied(vm, new_limit, self.direction)

        # Update qos policy rule id
        self.client.update_minimum_bandwidth_rule(
            new_rule['id'], qos_policy_id,
            body={'minimum_bandwidth_rule': {'min_kbps': MIN_BANDWIDTH}})
        self._wait_for_min_bw_rule_applied(vm, MIN_BANDWIDTH, self.direction)

        # Remove qos policy from port
        self.client.update_port(
            vm.neutron_port['id'],
            body={'port': {'qos_policy_id': None}})
        self._wait_for_min_bw_rule_removed(vm, self.direction)


class TestMinBwQoSOvs(_TestMinBwQoS, base.BaseFullStackTestCase):
    l2_agent_type = constants.AGENT_TYPE_OVS
    scenarios = [
        ('egress', {'direction': constants.EGRESS_DIRECTION})
    ]

    def _wait_for_min_bw_rule_applied(self, vm, min_bw, direction):
        if direction == constants.EGRESS_DIRECTION:
            utils.wait_until_true(
                lambda: vm.bridge.get_egress_min_bw_for_port(
                    vm.neutron_port['id']) == min_bw)
        elif direction == constants.INGRESS_DIRECTION:
            self.fail('"%s" direction not implemented'
                      % constants.INGRESS_DIRECTION)

    def _find_agent_qos_and_queue(self, vm):
        # NOTE(ralonsoh): the "_min_bw_qos_id" in vm.bridge is not the same as
        # the ID in the agent br_int instance. We need first to find the QoS
        # register and the Queue assigned to vm.neutron_port['id']
        queue = vm.bridge._find_queue(vm.neutron_port['id'])
        queue_num = int(queue['external_ids']['queue-num'])
        qoses = vm.bridge._list_qos()
        for qos in qoses:
            qos_queue = qos['queues'].get(queue_num)
            if qos_queue and qos_queue.uuid == queue['_uuid']:
                return qos, qos_queue

        self.fail('QoS register not found with queue-num %s' % queue_num)

    def test_min_bw_qos_port_removed(self):
        """Test if min BW limit config is properly removed when port removed"""
        # Create port with qos policy attached
        vm, qos_policy = self._prepare_vm_with_qos_policy(
            [functools.partial(
                self._add_min_bw_rule, MIN_BANDWIDTH, self.direction)])
        self._wait_for_min_bw_rule_applied(
            vm, MIN_BANDWIDTH, self.direction)

        qos, queue = self._find_agent_qos_and_queue(vm)
        self.assertEqual({'min-rate': str(MIN_BANDWIDTH * 1000)},
                         queue.other_config)
        queues = vm.bridge._list_queues(port=vm.neutron_port['id'])
        self.assertEqual(1, len(queues))
        self.assertEqual(queue.uuid, queues[0]['_uuid'])

        # Delete port with qos policy attached
        vm.destroy()
        self._wait_for_min_bw_rule_removed(vm, self.direction)
        self.assertEqual([],
                         vm.bridge._list_queues(port=vm.neutron_port['id']))
