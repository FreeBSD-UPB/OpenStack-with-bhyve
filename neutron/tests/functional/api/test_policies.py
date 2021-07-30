# Copyright (c) 2014 Red Hat, Inc.
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

import os.path

from neutron_lib.api import attributes
from neutron_lib import context
from neutron_lib import fixture

from neutron.api import extensions
from neutron.conf import policies
from neutron import policy
from neutron.tests.functional import base

TEST_PATH = os.path.dirname(os.path.abspath(__file__))


class APIPolicyTestCase(base.BaseLoggingTestCase):
    """Base class for API policy tests

    Tests for REST API policy checks. Ideally this would be done against an
    environment with an instantiated plugin, but there appears to be problems
    with instantiating a plugin against an sqlite environment and as yet, there
    is no precedent for running a functional test against an actual database
    backend.
    """

    api_version = "2.0"

    def setUp(self):
        super(APIPolicyTestCase, self).setUp()
        self.useFixture(fixture.APIDefinitionFixture())
        self.extension_path = os.path.abspath(os.path.join(
            TEST_PATH, "../../../extensions"))
        self.addCleanup(policy.reset)

    def _network_definition(self):
        return {'name': 'test_network',
                'ports': [],
                'subnets': [],
                'status': 'up',
                'admin_state_up': True,
                'shared': False,
                'tenant_id': 'admin',
                'id': 'test_network',
                'router:external': True}

    def _check_external_router_policy(self, context):
        return policy.check(context, 'get_network', self._network_definition())

    def test_premature_loading(self):
        """Test premature policy loading

        Verifies that loading policies by way of admin context before
        populating extensions and extending the resource map results in
        networks with router:external is true being invisible to regular
        tenants.
        """
        extension_manager = extensions.ExtensionManager(self.extension_path)
        admin_context = context.get_admin_context()
        tenant_context = context.Context('test_user', 'test_tenant_id', False)
        extension_manager.extend_resources(self.api_version,
                                           attributes.RESOURCES)
        self.assertTrue(self._check_external_router_policy(admin_context))
        self.assertFalse(self._check_external_router_policy(tenant_context))

    def test_proper_load_order(self):
        """Test proper policy load order

        Verifies that loading policies by way of admin context after
        populating extensions and extending the resource map results in
        networks with router:external are visible to regular tenants.
        """
        policy.reset()
        extension_manager = extensions.ExtensionManager(self.extension_path)
        extension_manager.extend_resources(self.api_version,
                                           attributes.RESOURCES)
        # TODO(amotoki): Consider this should be part of
        # neutron.policy.reset (or refresh), but as of now
        # this is only required for unit testing.
        policies.reload_default_policies()
        policy.init()
        admin_context = context.get_admin_context()
        tenant_context = context.Context('test_user', 'test_tenant_id', False)
        self.assertTrue(self._check_external_router_policy(admin_context))
        self.assertTrue(self._check_external_router_policy(tenant_context))
