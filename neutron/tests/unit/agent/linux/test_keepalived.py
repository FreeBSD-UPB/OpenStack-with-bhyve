# Copyright (C) 2014 eNovance SAS <licensing@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

import os
import textwrap

import mock
from neutron_lib import constants as n_consts
import testtools

from neutron.agent.linux import keepalived
from neutron.tests import base

# Keepalived user guide:
# http://www.keepalived.org/pdf/UserGuide.pdf

KEEPALIVED_GLOBAL_CONFIG = textwrap.dedent("""\
    global_defs {
        notification_email_from %(email_from)s
        router_id %(router_id)s
    }""") % dict(
        email_from=keepalived.KEEPALIVED_EMAIL_FROM,
        router_id=keepalived.KEEPALIVED_ROUTER_ID)
VRRP_ID = 1
VRRP_INTERVAL = 5


class KeepalivedGetFreeRangeTestCase(base.BaseTestCase):
    def test_get_free_range(self):
        free_range = keepalived.get_free_range(
            parent_range='169.254.0.0/16',
            excluded_ranges=['169.254.0.0/24',
                             '169.254.1.0/24',
                             '169.254.2.0/24'],
            size=24)
        self.assertEqual('169.254.3.0/24', free_range)

    def test_get_free_range_without_excluded(self):
        free_range = keepalived.get_free_range(
            parent_range='169.254.0.0/16',
            excluded_ranges=[],
            size=20)
        self.assertEqual('169.254.0.0/20', free_range)

    def test_get_free_range_excluded_out_of_parent(self):
        free_range = keepalived.get_free_range(
            parent_range='169.254.0.0/16',
            excluded_ranges=['255.255.255.0/24'],
            size=24)
        self.assertEqual('169.254.0.0/24', free_range)

    def test_get_free_range_not_found(self):
        tiny_parent_range = '192.168.1.0/24'
        huge_size = 8
        with testtools.ExpectedException(ValueError):
            keepalived.get_free_range(
                parent_range=tiny_parent_range,
                excluded_ranges=[],
                size=huge_size)


class KeepalivedConfBaseMixin(object):

    def _get_config(self):
        config = keepalived.KeepalivedConf()

        instance1 = keepalived.KeepalivedInstance('MASTER', 'eth0', 1,
                                                  ['169.254.192.0/18'],
                                                  advert_int=5)
        instance1.set_authentication('AH', 'pass123')
        instance1.track_interfaces.append("eth0")

        vip_address1 = keepalived.KeepalivedVipAddress('192.168.1.0/24',
                                                       'eth1', track=False)

        vip_address2 = keepalived.KeepalivedVipAddress('192.168.2.0/24',
                                                       'eth2', track=False)

        vip_address3 = keepalived.KeepalivedVipAddress('192.168.3.0/24',
                                                       'eth2', track=False)

        vip_address_ex = keepalived.KeepalivedVipAddress('192.168.55.0/24',
                                                         'eth10', track=False)

        instance1.vips.append(vip_address1)
        instance1.vips.append(vip_address2)
        instance1.vips.append(vip_address3)
        instance1.vips.append(vip_address_ex)

        virtual_route = keepalived.KeepalivedVirtualRoute(n_consts.IPv4_ANY,
                                                          "192.168.1.1",
                                                          "eth1")
        instance1.virtual_routes.gateway_routes = [virtual_route]

        instance2 = keepalived.KeepalivedInstance('MASTER', 'eth4', 2,
                                                  ['169.254.192.0/18'],
                                                  mcast_src_ip='224.0.0.1')
        instance2.track_interfaces.append("eth4")

        vip_address1 = keepalived.KeepalivedVipAddress('192.168.3.0/24',
                                                       'eth6', track=False)

        instance2.vips.append(vip_address1)
        instance2.vips.append(vip_address2)
        instance2.vips.append(vip_address_ex)

        config.add_instance(instance1)
        config.add_instance(instance2)

        return config


class KeepalivedConfTestCase(base.BaseTestCase,
                             KeepalivedConfBaseMixin):

    expected = KEEPALIVED_GLOBAL_CONFIG + textwrap.dedent("""
        vrrp_instance VR_1 {
            state MASTER
            interface eth0
            virtual_router_id 1
            priority 50
            garp_master_delay 60
            advert_int 5
            authentication {
                auth_type AH
                auth_pass pass123
            }
            track_interface {
                eth0
            }
            virtual_ipaddress {
                169.254.0.1/24 dev eth0
            }
            virtual_ipaddress_excluded {
                192.168.1.0/24 dev eth1 no_track
                192.168.2.0/24 dev eth2 no_track
                192.168.3.0/24 dev eth2 no_track
                192.168.55.0/24 dev eth10 no_track
            }
            virtual_routes {
                0.0.0.0/0 via 192.168.1.1 dev eth1 no_track
            }
        }
        vrrp_instance VR_2 {
            state MASTER
            interface eth4
            virtual_router_id 2
            priority 50
            garp_master_delay 60
            mcast_src_ip 224.0.0.1
            track_interface {
                eth4
            }
            virtual_ipaddress {
                169.254.0.2/24 dev eth4
            }
            virtual_ipaddress_excluded {
                192.168.2.0/24 dev eth2 no_track
                192.168.3.0/24 dev eth6 no_track
                192.168.55.0/24 dev eth10 no_track
            }
        }""")

    def test_config_generation(self):
        config = self._get_config()
        self.assertEqual(self.expected, config.get_config_str())

    def test_config_with_reset(self):
        config = self._get_config()
        self.assertEqual(self.expected, config.get_config_str())

        config.reset()
        self.assertEqual(KEEPALIVED_GLOBAL_CONFIG, config.get_config_str())

    def test_get_existing_vip_ip_addresses_returns_list(self):
        config = self._get_config()
        instance = config.get_instance(1)
        current_vips = sorted(instance.get_existing_vip_ip_addresses('eth2'))
        self.assertEqual(['192.168.2.0/24', '192.168.3.0/24'], current_vips)


class KeepalivedStateExceptionTestCase(base.BaseTestCase):
    def test_state_exception(self):
        invalid_vrrp_state = 'a seal walks'
        self.assertRaises(keepalived.InvalidInstanceStateException,
                          keepalived.KeepalivedInstance,
                          invalid_vrrp_state, 'eth0', 33,
                          ['169.254.192.0/18'])

        invalid_auth_type = 'into a club'
        instance = keepalived.KeepalivedInstance('MASTER', 'eth0', 1,
                                                 ['169.254.192.0/18'])
        self.assertRaises(keepalived.InvalidAuthenticationTypeException,
                          instance.set_authentication,
                          invalid_auth_type, 'some_password')


class KeepalivedInstanceRoutesTestCase(base.BaseTestCase):
    @classmethod
    def _get_instance_routes(cls):
        routes = keepalived.KeepalivedInstanceRoutes()
        default_gw_eth0 = keepalived.KeepalivedVirtualRoute(
            '0.0.0.0/0', '1.0.0.254', 'eth0')
        default_gw_eth1 = keepalived.KeepalivedVirtualRoute(
            '::/0', 'fe80::3e97:eff:fe26:3bfa/64', 'eth1')
        routes.gateway_routes = [default_gw_eth0, default_gw_eth1]
        extra_routes = [
            keepalived.KeepalivedVirtualRoute('10.0.0.0/8', '1.0.0.1'),
            keepalived.KeepalivedVirtualRoute('20.0.0.0/8', '2.0.0.2')]
        routes.extra_routes = extra_routes
        extra_subnets = [
            keepalived.KeepalivedVirtualRoute(
                '30.0.0.0/8', None, 'eth0', scope='link')]
        routes.extra_subnets = extra_subnets
        return routes

    def test_routes(self):
        routes = self._get_instance_routes()
        self.assertEqual(len(routes.routes), 5)

    def test_remove_routes_on_interface(self):
        routes = self._get_instance_routes()
        routes.remove_routes_on_interface('eth0')
        self.assertEqual(len(routes.routes), 3)
        routes.remove_routes_on_interface('eth1')
        self.assertEqual(len(routes.routes), 2)

    def test_build_config(self):
        expected = """    virtual_routes {
        0.0.0.0/0 via 1.0.0.254 dev eth0 no_track
        ::/0 via fe80::3e97:eff:fe26:3bfa/64 dev eth1 no_track
        10.0.0.0/8 via 1.0.0.1 no_track
        20.0.0.0/8 via 2.0.0.2 no_track
        30.0.0.0/8 dev eth0 scope link no_track
    }"""
        routes = self._get_instance_routes()
        self.assertEqual(expected, '\n'.join(routes.build_config()))


class KeepalivedInstanceTestCase(base.BaseTestCase,
                                 KeepalivedConfBaseMixin):
    def test_get_primary_vip(self):
        instance = keepalived.KeepalivedInstance('MASTER', 'ha0', 42,
                                                 ['169.254.192.0/18'])
        self.assertEqual('169.254.0.42/24', instance.get_primary_vip())

    def test_remove_addresses_by_interface(self):
        config = self._get_config()
        instance = config.get_instance(1)
        instance.remove_vips_vroutes_by_interface('eth2')
        instance.remove_vips_vroutes_by_interface('eth10')

        expected = KEEPALIVED_GLOBAL_CONFIG + textwrap.dedent("""
            vrrp_instance VR_1 {
                state MASTER
                interface eth0
                virtual_router_id 1
                priority 50
                garp_master_delay 60
                advert_int 5
                authentication {
                    auth_type AH
                    auth_pass pass123
                }
                track_interface {
                    eth0
                }
                virtual_ipaddress {
                    169.254.0.1/24 dev eth0
                }
                virtual_ipaddress_excluded {
                    192.168.1.0/24 dev eth1 no_track
                }
                virtual_routes {
                    0.0.0.0/0 via 192.168.1.1 dev eth1 no_track
                }
            }
            vrrp_instance VR_2 {
                state MASTER
                interface eth4
                virtual_router_id 2
                priority 50
                garp_master_delay 60
                mcast_src_ip 224.0.0.1
                track_interface {
                    eth4
                }
                virtual_ipaddress {
                    169.254.0.2/24 dev eth4
                }
                virtual_ipaddress_excluded {
                    192.168.2.0/24 dev eth2 no_track
                    192.168.3.0/24 dev eth6 no_track
                    192.168.55.0/24 dev eth10 no_track
                }
            }""")

        self.assertEqual(expected, config.get_config_str())

    def test_build_config_no_vips(self):
        expected = textwrap.dedent("""\
            vrrp_instance VR_1 {
                state MASTER
                interface eth0
                virtual_router_id 1
                priority 50
                garp_master_delay 60
                virtual_ipaddress {
                    169.254.0.1/24 dev eth0
                }
            }""")
        instance = keepalived.KeepalivedInstance(
            'MASTER', 'eth0', VRRP_ID, ['169.254.192.0/18'])
        self.assertEqual(expected, os.linesep.join(instance.build_config()))

    def test_build_config_no_vips_track_script(self):
        expected = """
vrrp_script ha_health_check_1 {
    script "/etc/ha_confs/qrouter-x/ha_check_script_1.sh"
    interval 5
    fall 2
    rise 2
}

vrrp_instance VR_1 {
    state MASTER
    interface eth0
    virtual_router_id 1
    priority 50
    garp_master_delay 60
    virtual_ipaddress {
        169.254.0.1/24 dev eth0
    }
}"""
        instance = keepalived.KeepalivedInstance(
            'MASTER', 'eth0', VRRP_ID, ['169.254.192.0/18'])
        instance.track_script = keepalived.KeepalivedTrackScript(
            VRRP_INTERVAL, '/etc/ha_confs/qrouter-x', VRRP_ID)
        self.assertEqual(expected, '\n'.join(instance.build_config()))


class KeepalivedVipAddressTestCase(base.BaseTestCase):
    def test_vip_with_scope(self):
        vip = keepalived.KeepalivedVipAddress('fe80::3e97:eff:fe26:3bfa/64',
                                              'eth1',
                                              'link')
        self.assertEqual('fe80::3e97:eff:fe26:3bfa/64 dev eth1 scope link',
                         vip.build_config())

    def test_add_vip_idempotent(self):
        instance = keepalived.KeepalivedInstance('MASTER', 'eth0', 1,
                                                 ['169.254.192.0/18'])
        instance.add_vip('192.168.222.1/32', 'eth11', None)
        instance.add_vip('192.168.222.1/32', 'eth12', 'link')
        self.assertEqual(1, len(instance.vips))


class KeepalivedVirtualRouteTestCase(base.BaseTestCase):
    def test_virtual_route_with_dev(self):
        route = keepalived.KeepalivedVirtualRoute(n_consts.IPv4_ANY, '1.2.3.4',
                                                  'eth0')
        self.assertEqual('0.0.0.0/0 via 1.2.3.4 dev eth0 no_track',
                         route.build_config())

    def test_virtual_route_without_dev(self):
        route = keepalived.KeepalivedVirtualRoute('50.0.0.0/8', '1.2.3.4')
        self.assertEqual('50.0.0.0/8 via 1.2.3.4 no_track',
                         route.build_config())


class KeepalivedTrackScriptTestCase(base.BaseTestCase):

    def test_build_config_preamble(self):
        exp_conf = [
            '',
            'vrrp_script ha_health_check_1 {',
            '    script "/etc/ha_confs/qrouter-x/ha_check_script_1.sh"',
            '    interval 5',
            '    fall 2',
            '    rise 2',
            '}',
            '']
        ts = keepalived.KeepalivedTrackScript(
            VRRP_INTERVAL, '/etc/ha_confs/qrouter-x', VRRP_ID)
        self.assertEqual(exp_conf, ts.build_config_preamble())

    def test_get_config_str(self):
        ts = keepalived.KeepalivedTrackScript(
            VRRP_INTERVAL, '/etc/ha_confs/qrouter-x', VRRP_ID)
        ts.routes = [
            keepalived.KeepalivedVirtualRoute('12.0.0.0/24', '10.0.0.1'), ]
        self.assertEqual('''    track_script {
        ha_health_check_1
    }''', ts.get_config_str())

    def test_get_script_str(self):
        ts = keepalived.KeepalivedTrackScript(
            VRRP_INTERVAL, '/etc/ha_confs/qrouter-x', VRRP_ID)
        ts.routes = [
            keepalived.KeepalivedVirtualRoute('12.0.0.0/24', '10.0.0.1'), ]
        ts.vips = [
            keepalived.KeepalivedVipAddress('192.168.0.3/18', 'ha-xxx'), ]

        self.assertEqual("""#!/bin/bash -eu
ip a | grep 192.168.0.3 || exit 0
ping -c 1 -w 1 10.0.0.1 1>/dev/null || exit 1""",
                         ts._get_script_str())

    def test_get_script_str_no_routes(self):
        ts = keepalived.KeepalivedTrackScript(
            VRRP_INTERVAL, '/etc/ha_confs/qrouter-x', VRRP_ID)

        self.assertEqual('#!/bin/bash -eu\n', ts._get_script_str())

    def test_write_check_script(self):
        conf_dir = '/etc/ha_confs/qrouter-x'
        ts = keepalived.KeepalivedTrackScript(VRRP_INTERVAL, conf_dir, VRRP_ID)
        ts.routes = [
            keepalived.KeepalivedVirtualRoute('12.0.0.0/24', '10.0.0.1'),
            keepalived.KeepalivedVirtualRoute('2001:db8::1', '2001:db8::1'), ]
        with mock.patch.object(keepalived, 'file_utils') as patched_utils:
            ts.write_check_script()
            patched_utils.replace_file.assert_called_with(
                os.path.join(conf_dir, 'ha_check_script_1.sh'),
                """#!/bin/bash -eu

ping -c 1 -w 1 10.0.0.1 1>/dev/null || exit 1
ping6 -c 1 -w 1 2001:db8::1 1>/dev/null || exit 1""",
                0o520
            )

    def test_write_check_script_no_routes(self):
        conf_dir = '/etc/ha_confs/qrouter-x'
        ts = keepalived.KeepalivedTrackScript(
            VRRP_INTERVAL, conf_dir, VRRP_ID)
        with mock.patch.object(keepalived, 'file_utils') as patched_utils:
            ts.write_check_script()
            patched_utils.replace_file.assert_not_called()
