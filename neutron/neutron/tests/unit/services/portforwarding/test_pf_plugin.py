# Copyright (C) 2018 OpenStack Foundation
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

import mock

from neutron_lib import context
from neutron_lib import exceptions as lib_exc
from neutron_lib.exceptions import l3 as lib_l3_exc
from neutron_lib.objects import exceptions as obj_exc
from neutron_lib.plugins import constants as lib_plugin_conts
from neutron_lib.plugins import directory
from oslo_config import cfg

from neutron.api.rpc.callbacks.consumer import registry as cons_registry
from neutron.api.rpc.callbacks import events as rpc_events
from neutron.api.rpc.callbacks.producer import registry as prod_registry
from neutron.api.rpc.callbacks import resource_manager
from neutron.api.rpc.handlers import resources_rpc
from neutron.db import db_base_plugin_v2
from neutron.db import l3_db
from neutron import manager
from neutron.objects import base as obj_base
from neutron.objects import port_forwarding
from neutron.objects import router
from neutron.services.portforwarding.common import exceptions as pf_exc
from neutron.services.portforwarding import pf_plugin
from neutron.tests.unit import testlib_api


DB_PLUGIN_KLASS = 'neutron.db.db_base_plugin_v2.NeutronDbPluginV2'


class TestPortForwardingPlugin(testlib_api.SqlTestCase):

    def setUp(self):
        super(TestPortForwardingPlugin, self).setUp()

        with mock.patch.object(
                resource_manager.ResourceCallbacksManager, '_singleton',
                new_callable=mock.PropertyMock(return_value=False)):

            self.cons_mgr = resource_manager.ConsumerResourceCallbacksManager()
            self.prod_mgr = resource_manager.ProducerResourceCallbacksManager()
            for mgr in (self.cons_mgr, self.prod_mgr):
                mgr.clear()

        mock.patch.object(
            cons_registry, '_get_manager', return_value=self.cons_mgr).start()

        mock.patch.object(
            prod_registry, '_get_manager', return_value=self.prod_mgr).start()
        self.setup_coreplugin(load_plugins=False)

        mock.patch('neutron.objects.db.api.create_object').start()
        mock.patch('neutron.objects.db.api.update_object').start()
        mock.patch('neutron.objects.db.api.delete_object').start()
        mock.patch('neutron.objects.db.api.get_object').start()
        # We don't use real models as per mocks above. We also need to mock-out
        # methods that work with real data types
        mock.patch(
            'neutron.objects.base.NeutronDbObject.modify_fields_from_db'
        ).start()

        cfg.CONF.set_override("core_plugin", DB_PLUGIN_KLASS)
        cfg.CONF.set_override("service_plugins", ["router", "port_forwarding"])

        manager.init()
        self.pf_plugin = directory.get_plugin(lib_plugin_conts.PORTFORWARDING)
        self.ctxt = context.Context('admin', 'fake_tenant')
        mock.patch.object(self.ctxt.session, 'refresh').start()
        mock.patch.object(self.ctxt.session, 'expunge').start()

    @mock.patch.object(port_forwarding.PortForwarding, 'get_object')
    def test_get_floatingip_port_forwarding(self, get_object_mock):
        self.pf_plugin.get_floatingip_port_forwarding(
            self.ctxt, 'pf_id', 'test-fip-id', fields=None)
        get_object_mock.assert_called_once_with(self.ctxt, id='pf_id')

    @mock.patch.object(port_forwarding.PortForwarding, 'get_object',
                       return_value=None)
    def test_negative_get_floatingip_port_forwarding(self, get_object_mock):
        self.assertRaises(
            pf_exc.PortForwardingNotFound,
            self.pf_plugin.get_floatingip_port_forwarding,
            self.ctxt, 'pf_id', 'test-fip-id', fields=None)

    @mock.patch.object(port_forwarding.PortForwarding, 'get_objects')
    def test_get_floatingip_port_forwardings(self, get_objects_mock):
        self.pf_plugin.get_floatingip_port_forwardings(self.ctxt)
        get_objects_mock.assert_called_once_with(
            self.ctxt, _pager=mock.ANY, floatingip_id=None)

    @mock.patch.object(resources_rpc.ResourcesPushRpcApi, 'push')
    @mock.patch.object(port_forwarding.PortForwarding, 'get_object')
    @mock.patch.object(port_forwarding.PortForwarding, 'get_objects')
    @mock.patch.object(router.FloatingIP, 'get_object')
    def test_delete_floatingip_port_forwarding(
            self, fip_get_object_mock, pf_get_objects_mock,
            pf_get_object_mock, push_api_mock):

        # After delete, not empty resource list
        pf_get_objects_mock.return_value = [mock.Mock(id='pf_id'),
                                            mock.Mock(id='pf_id2')]
        pf_obj = mock.Mock(id='pf_id', floatingip_id='fip_id')
        pf_get_object_mock.return_value = pf_obj
        self.pf_plugin.delete_floatingip_port_forwarding(
            self.ctxt, 'pf_id', 'fip_id')
        pf_get_objects_mock.assert_called_once_with(
            self.ctxt, floatingip_id='fip_id')
        pf_obj.delete.assert_called()
        push_api_mock.assert_called_once_with(
            self.ctxt, mock.ANY, rpc_events.DELETED)

        # After delete, empty resource list
        pf_get_objects_mock.reset_mock()
        pf_get_object_mock.reset_mock()
        push_api_mock.reset_mock()
        pf_obj = mock.Mock(id='need_to_delete_pf_id', floatingip_id='fip_id')
        fip_obj = mock.Mock(id='fip_id')
        fip_get_object_mock.return_value = fip_obj
        pf_get_object_mock.return_value = pf_obj
        pf_get_objects_mock.return_value = [
            mock.Mock(id='need_to_delete_pf_id')]

        self.pf_plugin.delete_floatingip_port_forwarding(
            self.ctxt, 'need_to_delete_pf_id', 'fip_id')
        pf_get_objects_mock.assert_called_once_with(
            self.ctxt, floatingip_id='fip_id')
        pf_get_object_mock.assert_called_once_with(
            self.ctxt, id='need_to_delete_pf_id')
        fip_obj.update_fields.assert_called_once_with({'router_id': None})
        fip_obj.update.assert_called()
        push_api_mock.assert_called_once_with(
            self.ctxt, mock.ANY, rpc_events.DELETED)

    @mock.patch.object(port_forwarding.PortForwarding, 'get_object')
    def test_negative_delete_floatingip_port_forwarding(
            self, pf_get_object_mock):
        pf_get_object_mock.return_value = None
        self.assertRaises(
            pf_exc.PortForwardingNotFound,
            self.pf_plugin.delete_floatingip_port_forwarding,
            self.ctxt, 'pf_id', floatingip_id='fip_id')

    @mock.patch.object(resources_rpc.ResourcesPushRpcApi, 'push')
    @mock.patch.object(port_forwarding.PortForwarding, 'get_object')
    def test_update_floatingip_port_forwarding(
            self, mock_pf_get_object, mock_rpc_push):
        pf_input = {
            'port_forwarding':
                {'port_forwarding': {
                    'internal_ip_address': '1.1.1.1',
                    'floatingip_id': 'fip_id'}},
            'floatingip_id': 'fip_id'}
        pf_obj = mock.Mock()
        mock_pf_get_object.return_value = pf_obj
        self.pf_plugin.update_floatingip_port_forwarding(
            self.ctxt, 'pf_id', **pf_input)
        mock_pf_get_object.assert_called_once_with(self.ctxt, id='pf_id')
        self.assertTrue(pf_obj.update_fields)
        self.assertTrue(pf_obj.update)
        mock_rpc_push.assert_called_once_with(
            self.ctxt, mock.ANY, rpc_events.UPDATED)

    @mock.patch.object(port_forwarding.PortForwarding, 'get_object')
    def test_negative_update_floatingip_port_forwarding(
            self, mock_pf_get_object):
        pf_input = {
            'port_forwarding':
                {'port_forwarding': {
                    'internal_ip_address': '1.1.1.1',
                    'floatingip_id': 'fip_id'}},
            'floatingip_id': 'fip_id'}
        mock_pf_get_object.return_value = None
        self.assertRaises(
            pf_exc.PortForwardingNotFound,
            self.pf_plugin.update_floatingip_port_forwarding,
            self.ctxt, 'pf_id', **pf_input)

    @mock.patch.object(pf_plugin.PortForwardingPlugin,
                       '_check_port_has_binding_floating_ip')
    @mock.patch.object(obj_base.NeutronDbObject, 'update_objects')
    @mock.patch.object(resources_rpc.ResourcesPushRpcApi, 'push')
    @mock.patch.object(pf_plugin.PortForwardingPlugin, '_check_router_match')
    @mock.patch.object(pf_plugin.PortForwardingPlugin,
                       '_find_a_router_for_fip_port_forwarding',
                       return_value='target_router_id')
    @mock.patch.object(router.FloatingIP, 'get_object')
    @mock.patch('neutron.objects.port_forwarding.PortForwarding')
    def test_create_floatingip_port_forwarding(
            self, mock_port_forwarding, mock_fip_get_object, mock_find_router,
            mock_check_router_match, mock_push_api, mock_update_objects,
            mock_check_bind_fip):
        # Update fip
        pf_input = {
            'port_forwarding':
                {'port_forwarding': {
                    'internal_ip_address': '1.1.1.1',
                    'floatingip_id': 'fip_id'}},
            'floatingip_id': 'fip_id'}
        pf_obj = mock.Mock()
        fip_obj = mock.Mock()
        mock_port_forwarding.return_value = pf_obj
        mock_fip_get_object.return_value = fip_obj
        fip_obj.router_id = ''
        fip_obj.fixed_port_id = ''
        self.pf_plugin.create_floatingip_port_forwarding(
            self.ctxt, **pf_input)
        mock_port_forwarding.assert_called_once_with(
            self.ctxt, **pf_input['port_forwarding']['port_forwarding'])
        self.assertTrue(mock_update_objects.called)
        self.assertTrue(pf_obj.create.called)
        mock_push_api.assert_called_once_with(
            self.ctxt, mock.ANY, rpc_events.CREATED)

        # Not update fip
        pf_obj.reset_mock()
        fip_obj.reset_mock()
        mock_port_forwarding.reset_mock()
        mock_update_objects.reset_mock()
        mock_push_api.reset_mock()
        mock_port_forwarding.return_value = pf_obj
        fip_obj.router_id = 'router_id'
        fip_obj.fixed_port_id = ''
        self.pf_plugin.create_floatingip_port_forwarding(
            self.ctxt, **pf_input)
        mock_port_forwarding.assert_called_once_with(
            self.ctxt, **pf_input['port_forwarding']['port_forwarding'])
        self.assertTrue(pf_obj.create.called)
        self.assertFalse(mock_update_objects.called)
        mock_push_api.assert_called_once_with(
            self.ctxt, mock.ANY, rpc_events.CREATED)

    @mock.patch.object(pf_plugin.PortForwardingPlugin,
                       '_check_port_has_binding_floating_ip')
    @mock.patch.object(pf_plugin.PortForwardingPlugin,
                       '_find_existing_port_forwarding')
    @mock.patch.object(pf_plugin.PortForwardingPlugin,
                       '_check_router_match')
    @mock.patch.object(pf_plugin.PortForwardingPlugin,
                       '_find_a_router_for_fip_port_forwarding',
                       return_value='target_router_id')
    @mock.patch.object(router.FloatingIP, 'get_object')
    @mock.patch('neutron.objects.port_forwarding.PortForwarding')
    def test_negative_create_floatingip_port_forwarding(
            self, mock_port_forwarding, mock_fip_get_object,
            mock_find_router,
            mock_check_router_match, mock_try_find_exist,
            mock_check_bind_fip):
        pf_input = {
            'port_forwarding': {
                'internal_ip_address': '1.1.1.1',
                'floatingip_id': 'fip_id'}}
        pf_obj = mock.Mock()
        fip_obj = mock.Mock()
        mock_port_forwarding.return_value = pf_obj
        mock_fip_get_object.return_value = fip_obj
        fip_obj.fixed_port_id = ''

        pf_obj.create.side_effect = obj_exc.NeutronDbObjectDuplicateEntry(
            mock.Mock(), mock.Mock())
        mock_try_find_exist.return_value = ('pf_obj', 'conflict_param')
        self.assertRaises(
            lib_exc.BadRequest,
            self.pf_plugin.create_floatingip_port_forwarding,
            self.ctxt, 'fip_id', pf_input)

    @mock.patch.object(pf_plugin.PortForwardingPlugin,
                       '_get_internal_ip_subnet')
    @mock.patch.object(l3_db.L3_NAT_dbonly_mixin, 'get_router_for_floatingip')
    @mock.patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_port')
    @mock.patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_subnet')
    def test_negative_find_a_router_for_fip_port_forwarding(
            self, mock_get_subnet, mock_get_port, mock_get_router,
            mock_get_ip_subnet):
        fip_obj = mock.Mock()
        pf_dict = {'internal_port_id': 'internal_neutron_port',
                   'internal_ip_address': '10.0.0.1'}
        port_dict = {'id': 'ID', 'fixed_ips': [{"subnet_id": "test-subnet-id",
                                                "ip_address": "10.0.0.1"}]}
        mock_get_port.return_value = port_dict
        mock_get_ip_subnet.return_value = None
        self.assertRaises(
            lib_exc.BadRequest,
            self.pf_plugin._find_a_router_for_fip_port_forwarding,
            self.ctxt, pf_dict, fip_obj)
        self.assertTrue(not mock_get_subnet.called)

        mock_get_ip_subnet.return_value = 'internal_subnet_id'

        mock_get_router.side_effect = (
            lib_l3_exc.ExternalGatewayForFloatingIPNotFound(
                external_network_id=mock.Mock(),
                subnet_id=mock.Mock(), port_id=mock.Mock()))
        self.assertRaises(
            lib_exc.BadRequest,
            self.pf_plugin._find_a_router_for_fip_port_forwarding,
            self.ctxt, pf_dict, fip_obj)
        self.assertTrue(mock_get_subnet.called)

        ipv6_port_dict = {'id': 'ID',
                          'fixed_ips': [{"subnet_id": "test-subnet-id",
                                         "ip_address": "1::1"}]}
        mock_get_port.return_value = ipv6_port_dict
        self.assertRaises(
            lib_exc.BadRequest,
            self.pf_plugin._find_a_router_for_fip_port_forwarding,
            self.ctxt, pf_dict, fip_obj)

    @mock.patch.object(port_forwarding.PortForwarding, 'get_objects')
    def test_negative_check_router_match(self, mock_pf_get_objects):
        pf_dict = {
            'internal_port_id': 'internal_neutron_port',
            'internal_ip_address': 'internal_fixed_ip',
            'internal_port': 'internal protocol port num'}
        fip_obj = mock.Mock()
        mock_pf_get_objects.return_value = ['Exist port forwardings']
        router_id = 'selected router id'
        self.assertRaises(lib_exc.BadRequest,
                          self.pf_plugin._check_router_match,
                          self.ctxt, fip_obj, router_id, pf_dict)

        mock_pf_get_objects.return_value = []
        self.assertRaises(lib_exc.BadRequest,
                          self.pf_plugin._check_router_match,
                          self.ctxt, fip_obj, router_id, pf_dict)

    @mock.patch.object(router.FloatingIP, 'get_objects')
    def test_create_floatingip_port_forwarding_port_in_use(
            self, mock_fip_get_objects):
        pf_input = {
            'port_forwarding':
                {'port_forwarding': {
                    'internal_ip_address': '1.1.1.1',
                    'internal_port_id': 'internal_neutron_port',
                    'floatingip_id': 'fip_id_1'}},
            'floatingip_id': 'fip_id_1'}
        fip_obj = mock.Mock(floating_ip_address="10.10.10.10")
        mock_fip_get_objects.return_value = [fip_obj]
        self.assertRaises(pf_exc.PortHasBindingFloatingIP,
                          self.pf_plugin.create_floatingip_port_forwarding,
                          self.ctxt, **pf_input)

    @mock.patch.object(router.FloatingIP, 'get_objects')
    def test_update_floatingip_port_forwarding_port_in_use(
            self, mock_fip_get_objects):
        pf_input = {
            'port_forwarding':
                {'port_forwarding': {
                    'internal_ip_address': '1.1.1.1',
                    'internal_port_id': 'internal_neutron_port',
                    'floatingip_id': 'fip_id_2'}}}
        fip_obj = mock.Mock(floating_ip_address="10.10.10.11")
        mock_fip_get_objects.return_value = [fip_obj]
        self.assertRaises(pf_exc.PortHasBindingFloatingIP,
                          self.pf_plugin.update_floatingip_port_forwarding,
                          self.ctxt, 'fake-pf-id', 'fip_id_2', **pf_input)
