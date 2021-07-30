# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture


class TestAvailabilityZoneScheduling(
        test.TestCase, integrated_helpers.InstanceHelperMixin):

    def setUp(self):
        super(TestAvailabilityZoneScheduling, self).setUp()

        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.admin_api
        self.api.microversion = 'latest'

        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)

        self.start_service('conductor')
        self.start_service('scheduler')

        # Start two compute services in separate zones.
        self._start_host_in_zone('host1', 'zone1')
        self._start_host_in_zone('host2', 'zone2')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]['id']
        self.flavor2 = flavors[1]['id']

    def _start_host_in_zone(self, host, zone):
        # Start the nova-compute service.
        self.start_service('compute', host=host)
        # Create a host aggregate with a zone in which to put this host.
        aggregate_body = {
            "aggregate": {
                "name": zone,
                "availability_zone": zone
            }
        }
        aggregate = self.api.api_post(
            '/os-aggregates', aggregate_body).body['aggregate']
        # Now add the compute host to the aggregate.
        add_host_body = {
            "add_host": {
                "host": host
            }
        }
        self.api.api_post(
            '/os-aggregates/%s/action' % aggregate['id'], add_host_body)

    def _create_server(self, name):
        # Create a server, it doesn't matter which host it ends up in.
        server_body = self._build_minimal_create_server_request(
            self.api, name, image_uuid=fake_image.get_valid_image_id(),
            flavor_id=self.flavor1, networks='none')
        server = self.api.post_server({'server': server_body})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        original_host = server['OS-EXT-SRV-ATTR:host']
        # Assert the server has the AZ set (not None or 'nova').
        expected_zone = 'zone1' if original_host == 'host1' else 'zone2'
        self.assertEqual(expected_zone, server['OS-EXT-AZ:availability_zone'])
        return server

    def _assert_instance_az(self, server, expected_zone):
        # Check the API.
        self.assertEqual(expected_zone, server['OS-EXT-AZ:availability_zone'])
        # Check the DB.
        ctxt = context.get_admin_context()
        with context.target_cell(
                ctxt, self.cell_mappings[test.CELL1_NAME]) as cctxt:
            instance = objects.Instance.get_by_uuid(cctxt, server['id'])
            self.assertEqual(expected_zone, instance.availability_zone)

    def test_live_migrate_implicit_az(self):
        """Tests live migration of an instance with an implicit AZ.

        Before Pike, a server created without an explicit availability zone
        was assigned a default AZ based on the "default_schedule_zone" config
        option which defaults to None, which allows the instance to move
        freely between availability zones.

        With change I8d426f2635232ffc4b510548a905794ca88d7f99 in Pike, if the
        user does not request an availability zone, the
        instance.availability_zone field is set based on the host chosen by
        the scheduler. The default AZ for all nova-compute services is
        determined by the "default_availability_zone" config option which
        defaults to "nova".

        This test creates two nova-compute services in separate zones, creates
        a server without specifying an explicit zone, and then tries to live
        migrate the instance to the other compute which should succeed because
        the request spec does not include an explicit AZ, so the instance is
        still not restricted to its current zone even if it says it is in one.
        """
        server = self._create_server('test_live_migrate_implicit_az')
        original_host = server['OS-EXT-SRV-ATTR:host']

        # Attempt to live migrate the instance; again, we don't specify a host
        # because there are only two hosts so the scheduler would only be able
        # to pick the second host which is in a different zone.
        live_migrate_req = {
            'os-migrateLive': {
                'block_migration': 'auto',
                'host': None
            }
        }
        self.api.post_server_action(server['id'], live_migrate_req)

        # Poll the migration until it is done.
        migration = self._wait_for_migration_status(server, ['completed'])
        self.assertEqual('live-migration', migration['migration_type'])

        # Assert that the server did move. Note that we check both the API and
        # the database because the API will return the AZ from the host
        # aggregate if instance.host is not None.
        server = self.api.get_server(server['id'])
        expected_zone = 'zone2' if original_host == 'host1' else 'zone1'
        self._assert_instance_az(server, expected_zone)

    def test_resize_revert_across_azs(self):
        """Creates two compute service hosts in separate AZs. Creates a server
        without an explicit AZ so it lands in one AZ, and then resizes the
        server which moves it to the other AZ. Then the resize is reverted and
        asserts the server is shown as back in the original source host AZ.
        """
        server = self._create_server('test_resize_revert_across_azs')
        original_host = server['OS-EXT-SRV-ATTR:host']
        original_az = 'zone1' if original_host == 'host1' else 'zone2'

        # Resize the server which should move it to the other zone.
        self.api.post_server_action(
            server['id'], {'resize': {'flavorRef': self.flavor2}})
        server = self._wait_for_state_change(self.api, server, 'VERIFY_RESIZE')

        # Now the server should be in the other AZ.
        new_zone = 'zone2' if original_host == 'host1' else 'zone1'
        self._assert_instance_az(server, new_zone)

        # Revert the resize and the server should be back in the original AZ.
        self.api.post_server_action(server['id'], {'revertResize': None})
        server = self._wait_for_state_change(self.api, server, 'ACTIVE')
        self._assert_instance_az(server, original_az)
