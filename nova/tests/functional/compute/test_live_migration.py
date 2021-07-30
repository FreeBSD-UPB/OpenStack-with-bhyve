# Copyright 2018 Red Hat, Inc.
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

from oslo_utils.fixture import uuidsentinel as uuids

from nova import exception
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier


class FakeCinderError(object):
    """Poor man's Mock because we're stubbing out and not mock.patching. Stubs
    out attachment_delete. We keep a raise and call count to simulate a single
    volume error while being able to assert that we still got called for all
    of an instance's volumes.
    """

    def __init__(self):
        self.raise_count = 0
        self.call_count = 0

    def __call__(self, *args, **kwargs):
        self.call_count += 1
        if self.raise_count == 0:
            self.raise_count += 1
            raise exception.CinderConnectionFailed(reason='Fake Cinder error')


class LiveMigrationCinderFailure(integrated_helpers._IntegratedTestBase,
                                 integrated_helpers.InstanceHelperMixin):
    api_major_version = 'v2.1'
    microversion = 'latest'
    USE_NEUTRON = True

    def setUp(self):
        super(LiveMigrationCinderFailure, self).setUp()
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)
        # Start a second compte node (the first one was started for us by
        # _IntegratedTestBase. set_nodes() is needed to avoid duplicate
        # nodenames. See comments in test_bug_1702454.py.
        self.compute2 = self.start_service('compute', host='host2')

    def test_live_migrate_attachment_delete_fails(self):
        self.useFixture(nova_fixtures.CinderFixture(self))
        server = self.api.post_server({
            'server': {
                'flavorRef': 1,
                'imageRef': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'name': 'live-migrate-attachment-delete-fail-test',
                'networks': 'none',
                'block_device_mapping_v2': [
                    {'boot_index': 0,
                     'uuid': uuids.broken_volume,
                     'source_type': 'volume',
                     'destination_type': 'volume'},
                    {'boot_index': 1,
                     'uuid': uuids.working_volume,
                     'source_type': 'volume',
                     'destination_type': 'volume'}]}})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')

        source = server['OS-EXT-SRV-ATTR:host']
        if source == self.compute.host:
            dest = self.compute2.host
        else:
            dest = self.compute.host

        post = {
            'os-migrateLive': {
                'host': dest,
                'block_migration': False,
            }
        }
        stub_attachment_delete = FakeCinderError()
        self.stub_out('nova.volume.cinder.API.attachment_delete',
                      stub_attachment_delete)
        self.api.post_server_action(server['id'], post)
        self._wait_for_server_parameter(self.api, server,
                                        {'OS-EXT-SRV-ATTR:host': dest,
                                         'status': 'ACTIVE'})
        self.assertEqual(2, stub_attachment_delete.call_count)
        self.assertEqual(1, stub_attachment_delete.raise_count)
