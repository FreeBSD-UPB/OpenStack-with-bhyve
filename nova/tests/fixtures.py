# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Fixtures for Nova tests."""
from __future__ import absolute_import

import collections
from contextlib import contextmanager
import copy
import logging as std_logging
import os
import random
import warnings

import fixtures
import futurist
from keystoneauth1 import adapter as ksa_adap
import mock
from neutronclient.common import exceptions as neutron_client_exc
from openstack import service_description
import os_resource_classes as orc
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_messaging import conffixture as messaging_conffixture
from oslo_privsep import daemon as privsep_daemon
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel
from oslo_utils import uuidutils
from requests import adapters
from sqlalchemy import exc as sqla_exc
from wsgi_intercept import interceptor

from nova.api.openstack.compute import tenant_networks
from nova.api.openstack import wsgi_app
from nova.api import wsgi
from nova.compute import multi_cell_list
from nova.compute import rpcapi as compute_rpcapi
from nova import context
from nova.db import migration
from nova.db.sqlalchemy import api as session
from nova import exception
from nova.network import model as network_model
from nova.network.neutronv2 import constants as neutron_constants
from nova import objects
from nova.objects import base as obj_base
from nova.objects import service as service_obj
import nova.privsep
from nova import quota as nova_quota
from nova import rpc
from nova.scheduler import weights
from nova import service
from nova.tests.functional.api import client
from nova.tests.unit import fake_requests

_TRUE_VALUES = ('True', 'true', '1', 'yes')

CONF = cfg.CONF
DB_SCHEMA = {'main': "", 'api': ""}
SESSION_CONFIGURED = False

LOG = logging.getLogger(__name__)


class ServiceFixture(fixtures.Fixture):
    """Run a service as a test fixture."""

    def __init__(self, name, host=None, cell=None, **kwargs):
        name = name
        # If not otherwise specified, the host will default to the
        # name of the service. Some things like aggregates care that
        # this is stable.
        host = host or name
        kwargs.setdefault('host', host)
        kwargs.setdefault('binary', 'nova-%s' % name)
        self.cell = cell
        self.kwargs = kwargs

    def setUp(self):
        super(ServiceFixture, self).setUp()
        self.ctxt = context.get_admin_context()
        if self.cell:
            context.set_target_cell(self.ctxt, self.cell)

        # NOTE(mikal): we don't have root to manipulate iptables, so just
        # zero that bit out.
        self.useFixture(fixtures.MockPatch(
            'nova.network.linux_net.IptablesManager._apply'))

        with mock.patch('nova.context.get_admin_context',
                        return_value=self.ctxt):
            self.service = service.Service.create(**self.kwargs)
            self.service.start()
        self.addCleanup(self.service.kill)


class NullHandler(std_logging.Handler):
    """custom default NullHandler to attempt to format the record.

    Used in conjunction with
    log_fixture.get_logging_handle_error_fixture to detect formatting errors in
    debug level logs without saving the logs.
    """
    def handle(self, record):
        self.format(record)

    def emit(self, record):
        pass

    def createLock(self):
        self.lock = None


class StandardLogging(fixtures.Fixture):
    """Setup Logging redirection for tests.

    There are a number of things we want to handle with logging in tests:

    * Redirect the logging to somewhere that we can test or dump it later.

    * Ensure that as many DEBUG messages as possible are actually
       executed, to ensure they are actually syntactically valid (they
       often have not been).

    * Ensure that we create useful output for tests that doesn't
      overwhelm the testing system (which means we can't capture the
      100 MB of debug logging on every run).

    To do this we create a logger fixture at the root level, which
    defaults to INFO and create a Null Logger at DEBUG which lets
    us execute log messages at DEBUG but not keep the output.

    To support local debugging OS_DEBUG=True can be set in the
    environment, which will print out the full debug logging.

    There are also a set of overrides for particularly verbose
    modules to be even less than INFO.

    """

    def setUp(self):
        super(StandardLogging, self).setUp()

        # set root logger to debug
        root = std_logging.getLogger()
        root.setLevel(std_logging.DEBUG)

        # supports collecting debug level for local runs
        if os.environ.get('OS_DEBUG') in _TRUE_VALUES:
            level = std_logging.DEBUG
        else:
            level = std_logging.INFO

        # Collect logs
        fs = '%(asctime)s %(levelname)s [%(name)s] %(message)s'
        self.logger = self.useFixture(
            fixtures.FakeLogger(format=fs, level=None))
        # TODO(sdague): why can't we send level through the fake
        # logger? Tests prove that it breaks, but it's worth getting
        # to the bottom of.
        root.handlers[0].setLevel(level)

        if level > std_logging.DEBUG:
            # Just attempt to format debug level logs, but don't save them
            handler = NullHandler()
            self.useFixture(fixtures.LogHandler(handler, nuke_handlers=False))
            handler.setLevel(std_logging.DEBUG)

            # Don't log every single DB migration step
            std_logging.getLogger(
                'migrate.versioning.api').setLevel(std_logging.WARNING)

        # At times we end up calling back into main() functions in
        # testing. This has the possibility of calling logging.setup
        # again, which completely unwinds the logging capture we've
        # created here. Once we've setup the logging the way we want,
        # disable the ability for the test to change this.
        def fake_logging_setup(*args):
            pass

        self.useFixture(
            fixtures.MonkeyPatch('oslo_log.log.setup', fake_logging_setup))

    def delete_stored_logs(self):
        # NOTE(gibi): this depends on the internals of the fixtures.FakeLogger.
        # This could be enhanced once the PR
        # https://github.com/testing-cabal/fixtures/pull/42 merges
        self.logger._output.truncate(0)


class OutputStreamCapture(fixtures.Fixture):
    """Capture output streams during tests.

    This fixture captures errant printing to stderr / stdout during
    the tests and lets us see those streams at the end of the test
    runs instead. Useful to see what was happening during failed
    tests.
    """
    def setUp(self):
        super(OutputStreamCapture, self).setUp()
        if os.environ.get('OS_STDOUT_CAPTURE') in _TRUE_VALUES:
            self.out = self.useFixture(fixtures.StringStream('stdout'))
            self.useFixture(
                fixtures.MonkeyPatch('sys.stdout', self.out.stream))
        if os.environ.get('OS_STDERR_CAPTURE') in _TRUE_VALUES:
            self.err = self.useFixture(fixtures.StringStream('stderr'))
            self.useFixture(
                fixtures.MonkeyPatch('sys.stderr', self.err.stream))

    @property
    def stderr(self):
        return self.err._details["stderr"].as_text()

    @property
    def stdout(self):
        return self.out._details["stdout"].as_text()


class Timeout(fixtures.Fixture):
    """Setup per test timeouts.

    In order to avoid test deadlocks we support setting up a test
    timeout parameter read from the environment. In almost all
    cases where the timeout is reached this means a deadlock.

    A class level TIMEOUT_SCALING_FACTOR also exists, which allows
    extremely long tests to specify they need more time.
    """

    def __init__(self, timeout, scaling=1):
        super(Timeout, self).__init__()
        try:
            self.test_timeout = int(timeout)
        except ValueError:
            # If timeout value is invalid do not set a timeout.
            self.test_timeout = 0
        if scaling >= 1:
            self.test_timeout *= scaling
        else:
            raise ValueError('scaling value must be >= 1')

    def setUp(self):
        super(Timeout, self).setUp()
        if self.test_timeout > 0:
            self.useFixture(fixtures.Timeout(self.test_timeout, gentle=True))


class DatabasePoisonFixture(fixtures.Fixture):
    def setUp(self):
        super(DatabasePoisonFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'oslo_db.sqlalchemy.enginefacade._TransactionFactory.'
            '_create_session',
            self._poison_configure))

    def _poison_configure(self, *a, **k):
        # If you encounter this error, you might be tempted to just not
        # inherit from NoDBTestCase. Bug #1568414 fixed a few hundred of these
        # errors, and not once was that the correct solution. Instead,
        # consider some of the following tips (when applicable):
        #
        # - mock at the object layer rather than the db layer, for example:
        #       nova.objects.instance.Instance.get
        #            vs.
        #       nova.db.instance_get
        #
        # - mock at the api layer rather than the object layer, for example:
        #       nova.api.openstack.common.get_instance
        #           vs.
        #       nova.objects.instance.Instance.get
        #
        # - mock code that requires the database but is otherwise tangential
        #   to the code you're testing (for example: EventReporterStub)
        #
        # - peruse some of the other database poison warning fixes here:
        #   https://review.opendev.org/#/q/topic:bug/1568414
        raise Exception('This test uses methods that set internal oslo_db '
                        'state, but it does not claim to use the database. '
                        'This will conflict with the setup of tests that '
                        'do use the database and cause failures later.')


class SingleCellSimple(fixtures.Fixture):
    """Setup the simplest cells environment possible

    This should be used when you do not care about multiple cells,
    or having a "real" environment for tests that should not care.
    This will give you a single cell, and map any and all accesses
    to that cell (even things that would go to cell0).

    If you need to distinguish between cell0 and cellN, then you
    should use the CellDatabases fixture.

    If instances should appear to still be in scheduling state, pass
    instances_created=False to init.
    """

    def __init__(self, instances_created=True):
        self.instances_created = instances_created

    def setUp(self):
        super(SingleCellSimple, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.CellMappingList._get_all_from_db',
            self._fake_cell_list))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.CellMappingList._get_by_project_id_from_db',
            self._fake_cell_list))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.CellMapping._get_by_uuid_from_db',
            self._fake_cell_get))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.HostMapping._get_by_host_from_db',
            self._fake_hostmapping_get))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.InstanceMapping._get_by_instance_uuid_from_db',
            self._fake_instancemapping_get))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.InstanceMappingList._get_by_instance_uuids_from_db',
            self._fake_instancemapping_get_uuids))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.InstanceMapping._save_in_db',
            self._fake_instancemapping_get_save))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.target_cell',
            self._fake_target_cell))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.set_target_cell',
            lambda c, m: None))

    def _fake_hostmapping_get(self, *args):
        return {'id': 1,
                'updated_at': None,
                'created_at': None,
                'host': 'host1',
                'cell_mapping': self._fake_cell_list()[0]}

    def _fake_instancemapping_get_common(self, instance_uuid):
        return {
            'id': 1,
            'updated_at': None,
            'created_at': None,
            'instance_uuid': instance_uuid,
            'cell_id': (self.instances_created and 1 or None),
            'project_id': 'project',
            'cell_mapping': (
                self.instances_created and self._fake_cell_get() or None),
        }

    def _fake_instancemapping_get_save(self, *args):
        return self._fake_instancemapping_get_common(args[-2])

    def _fake_instancemapping_get(self, *args):
        return self._fake_instancemapping_get_common(args[-1])

    def _fake_instancemapping_get_uuids(self, *args):
        return [self._fake_instancemapping_get(uuid)
                for uuid in args[-1]]

    def _fake_cell_get(self, *args):
        return self._fake_cell_list()[0]

    def _fake_cell_list(self, *args):
        return [{'id': 1,
                 'updated_at': None,
                 'created_at': None,
                 'uuid': uuidsentinel.cell1,
                 'name': 'onlycell',
                 'transport_url': 'fake://nowhere/',
                 'database_connection': 'sqlite:///',
                 'disabled': False}]

    @contextmanager
    def _fake_target_cell(self, context, target_cell):
        # NOTE(danms): Just pass through the context without actually
        # targeting anything.
        yield context


class CheatingSerializer(rpc.RequestContextSerializer):
    """A messaging.RequestContextSerializer that helps with cells.

    Our normal serializer does not pass in the context like db_connection
    and mq_connection, for good reason. We don't really want/need to
    force a remote RPC server to use our values for this. However,
    during unit and functional tests, since we're all in the same
    process, we want cell-targeted RPC calls to preserve these values.
    Unless we had per-service config and database layer state for
    the fake services we start, this is a reasonable cheat.
    """
    def serialize_context(self, context):
        """Serialize context with the db_connection inside."""
        values = super(CheatingSerializer, self).serialize_context(context)
        values['db_connection'] = context.db_connection
        values['mq_connection'] = context.mq_connection
        return values

    def deserialize_context(self, values):
        """Deserialize context and honor db_connection if present."""
        ctxt = super(CheatingSerializer, self).deserialize_context(values)
        ctxt.db_connection = values.pop('db_connection', None)
        ctxt.mq_connection = values.pop('mq_connection', None)
        return ctxt


class CellDatabases(fixtures.Fixture):
    """Create per-cell databases for testing.

    How to use::

      fix = CellDatabases()
      fix.add_cell_database('connection1')
      fix.add_cell_database('connection2', default=True)
      self.useFixture(fix)

    Passing default=True tells the fixture which database should
    be given to code that doesn't target a specific cell.
    """
    def __init__(self):
        self._ctxt_mgrs = {}
        self._last_ctxt_mgr = None
        self._default_ctxt_mgr = None

        # NOTE(danms): Use a ReaderWriterLock to synchronize our
        # global database muckery here. If we change global db state
        # to point to a cell, we need to take an exclusive lock to
        # prevent any other calls to get_context_manager() until we
        # reset to the default.
        self._cell_lock = lockutils.ReaderWriterLock()

    def _cache_schema(self, connection_str):
        # NOTE(melwitt): See the regular Database fixture for why
        # we do this.
        global DB_SCHEMA
        if not DB_SCHEMA['main']:
            ctxt_mgr = self._ctxt_mgrs[connection_str]
            engine = ctxt_mgr.writer.get_engine()
            conn = engine.connect()
            migration.db_sync(database='main')
            DB_SCHEMA['main'] = "".join(line for line
                                        in conn.connection.iterdump())
            engine.dispose()

    @contextmanager
    def _wrap_target_cell(self, context, cell_mapping):
        # NOTE(danms): This method is responsible for switching global
        # database state in a safe way such that code that doesn't
        # know anything about cell targeting (i.e. compute node code)
        # can continue to operate when called from something that has
        # targeted a specific cell. In order to make this safe from a
        # dining-philosopher-style deadlock, we need to be able to
        # support multiple threads talking to the same cell at the
        # same time and potentially recursion within the same thread
        # from code that would otherwise be running on separate nodes
        # in real life, but where we're actually recursing in the
        # tests.
        #
        # The basic logic here is:
        #  1. Grab a reader lock to see if the state is already pointing at
        #     the cell we want. If it is, we can yield and return without
        #     altering the global state further. The read lock ensures that
        #     global state won't change underneath us, and multiple threads
        #     can be working at the same time, as long as they are looking
        #     for the same cell.
        #  2. If we do need to change the global state, grab a writer lock
        #     to make that change, which assumes that nothing else is looking
        #     at a cell right now. We do only non-schedulable things while
        #     holding that lock to avoid the deadlock mentioned above.
        #  3. We then re-lock with a reader lock just as step #1 above and
        #     yield to do the actual work. We can do schedulable things
        #     here and not exclude other threads from making progress.
        #     If an exception is raised, we capture that and save it.
        #  4. If we changed state in #2, we need to change it back. So we grab
        #     a writer lock again and do that.
        #  5. Finally, if an exception was raised in #3 while state was
        #     changed, we raise it to the caller.

        if cell_mapping:
            desired = self._ctxt_mgrs[cell_mapping.database_connection]
        else:
            desired = self._default_ctxt_mgr

        with self._cell_lock.read_lock():
            if self._last_ctxt_mgr == desired:
                with self._real_target_cell(context, cell_mapping) as c:
                    yield c
                    return

        raised_exc = None

        with self._cell_lock.write_lock():
            if cell_mapping is not None:
                # This assumes the next local DB access is the same cell that
                # was targeted last time.
                self._last_ctxt_mgr = desired

        with self._cell_lock.read_lock():
            if self._last_ctxt_mgr != desired:
                # NOTE(danms): This is unlikely to happen, but it's possible
                # another waiting writer changed the state between us letting
                # it go and re-acquiring as a reader. If lockutils supported
                # upgrading and downgrading locks, this wouldn't be a problem.
                # Regardless, assert that it is still as we left it here
                # so we don't hit the wrong cell. If this becomes a problem,
                # we just need to retry the write section above until we land
                # here with the cell we want.
                raise RuntimeError('Global DB state changed underneath us')

            try:
                with self._real_target_cell(context, cell_mapping) as ccontext:
                    yield ccontext
            except Exception as exc:
                raised_exc = exc

        with self._cell_lock.write_lock():
            # Once we have returned from the context, we need
            # to restore the default context manager for any
            # subsequent calls
            self._last_ctxt_mgr = self._default_ctxt_mgr

        if raised_exc:
            raise raised_exc

    def _wrap_create_context_manager(self, connection=None):
        ctxt_mgr = self._ctxt_mgrs[connection]
        return ctxt_mgr

    def _wrap_get_context_manager(self, context):
        try:
            # If already targeted, we can proceed without a lock
            if context.db_connection:
                return context.db_connection
        except AttributeError:
            # Unit tests with None, FakeContext, etc
            pass

        # NOTE(melwitt): This is a hack to try to deal with
        # local accesses i.e. non target_cell accesses.
        with self._cell_lock.read_lock():
            # FIXME(mriedem): This is actually misleading and means we don't
            # catch things like bug 1717000 where a context should be targeted
            # to a cell but it's not, and the fixture here just returns the
            # last targeted context that was used.
            return self._last_ctxt_mgr

    def _wrap_get_server(self, target, endpoints, serializer=None):
        """Mirror rpc.get_server() but with our special sauce."""
        serializer = CheatingSerializer(serializer)
        return messaging.get_rpc_server(rpc.TRANSPORT,
                                        target,
                                        endpoints,
                                        executor='eventlet',
                                        serializer=serializer)

    def _wrap_get_client(self, target, version_cap=None, serializer=None,
                         call_monitor_timeout=None):
        """Mirror rpc.get_client() but with our special sauce."""
        serializer = CheatingSerializer(serializer)
        return messaging.RPCClient(rpc.TRANSPORT,
                                   target,
                                   version_cap=version_cap,
                                   serializer=serializer,
                                   call_monitor_timeout=call_monitor_timeout)

    def add_cell_database(self, connection_str, default=False):
        """Add a cell database to the fixture.

        :param connection_str: An identifier used to represent the connection
        string for this database. It should match the database_connection field
        in the corresponding CellMapping.
        """

        # NOTE(danms): Create a new context manager for the cell, which
        # will house the sqlite:// connection for this cell's in-memory
        # database. Store/index it by the connection string, which is
        # how we identify cells in CellMapping.
        ctxt_mgr = session.create_context_manager()
        self._ctxt_mgrs[connection_str] = ctxt_mgr

        # NOTE(melwitt): The first DB access through service start is
        # local so this initializes _last_ctxt_mgr for that and needs
        # to be a compute cell.
        self._last_ctxt_mgr = ctxt_mgr

        # NOTE(danms): Record which context manager should be the default
        # so we can restore it when we return from target-cell contexts.
        # If none has been provided yet, store the current one in case
        # no default is ever specified.
        if self._default_ctxt_mgr is None or default:
            self._default_ctxt_mgr = ctxt_mgr

        def get_context_manager(context):
            return ctxt_mgr

        # NOTE(danms): This is a temporary MonkeyPatch just to get
        # a new database created with the schema we need and the
        # context manager for it stashed.
        with fixtures.MonkeyPatch(
                'nova.db.sqlalchemy.api.get_context_manager',
                get_context_manager):
            self._cache_schema(connection_str)
            engine = ctxt_mgr.writer.get_engine()
            engine.dispose()
            conn = engine.connect()
            conn.connection.executescript(DB_SCHEMA['main'])

    def setUp(self):
        super(CellDatabases, self).setUp()
        self.addCleanup(self.cleanup)
        self._real_target_cell = context.target_cell

        # NOTE(danms): These context managers are in place for the
        # duration of the test (unlike the temporary ones above) and
        # provide the actual "runtime" switching of connections for us.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.db.sqlalchemy.api.create_context_manager',
            self._wrap_create_context_manager))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.db.sqlalchemy.api.get_context_manager',
            self._wrap_get_context_manager))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.target_cell',
            self._wrap_target_cell))

        self.useFixture(fixtures.MonkeyPatch(
            'nova.rpc.get_server',
            self._wrap_get_server))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.rpc.get_client',
            self._wrap_get_client))

    def cleanup(self):
        for ctxt_mgr in self._ctxt_mgrs.values():
            engine = ctxt_mgr.writer.get_engine()
            engine.dispose()


class Database(fixtures.Fixture):
    def __init__(self, database='main', connection=None):
        """Create a database fixture.

        :param database: The type of database, 'main', or 'api'
        :param connection: The connection string to use
        """
        super(Database, self).__init__()
        # NOTE(pkholkin): oslo_db.enginefacade is configured in tests the same
        # way as it is done for any other service that uses db
        global SESSION_CONFIGURED
        if not SESSION_CONFIGURED:
            session.configure(CONF)
            SESSION_CONFIGURED = True
        self.database = database
        if database == 'main':
            if connection is not None:
                ctxt_mgr = session.create_context_manager(
                        connection=connection)
                self.get_engine = ctxt_mgr.writer.get_engine
            else:
                self.get_engine = session.get_engine
        elif database == 'api':
            self.get_engine = session.get_api_engine

    def _cache_schema(self):
        global DB_SCHEMA
        if not DB_SCHEMA[self.database]:
            engine = self.get_engine()
            conn = engine.connect()
            migration.db_sync(database=self.database)
            DB_SCHEMA[self.database] = "".join(line for line
                                               in conn.connection.iterdump())
            engine.dispose()

    def cleanup(self):
        engine = self.get_engine()
        engine.dispose()

    def reset(self):
        self._cache_schema()
        engine = self.get_engine()
        engine.dispose()
        conn = engine.connect()
        conn.connection.executescript(DB_SCHEMA[self.database])

    def setUp(self):
        super(Database, self).setUp()
        self.reset()
        self.addCleanup(self.cleanup)


class DatabaseAtVersion(fixtures.Fixture):
    def __init__(self, version, database='main'):
        """Create a database fixture.

        :param version: Max version to sync to (or None for current)
        :param database: The type of database, 'main', 'api'
        """
        super(DatabaseAtVersion, self).__init__()
        self.database = database
        self.version = version
        if database == 'main':
            self.get_engine = session.get_engine
        elif database == 'api':
            self.get_engine = session.get_api_engine

    def cleanup(self):
        engine = self.get_engine()
        engine.dispose()

    def reset(self):
        engine = self.get_engine()
        engine.dispose()
        engine.connect()
        migration.db_sync(version=self.version, database=self.database)

    def setUp(self):
        super(DatabaseAtVersion, self).setUp()
        self.reset()
        self.addCleanup(self.cleanup)


class DefaultFlavorsFixture(fixtures.Fixture):
    def setUp(self):
        super(DefaultFlavorsFixture, self).setUp()
        ctxt = context.get_admin_context()
        defaults = {'rxtx_factor': 1.0, 'disabled': False, 'is_public': True,
                    'ephemeral_gb': 0, 'swap': 0}
        extra_specs = {
            "hw:numa_nodes": "1"
        }
        default_flavors = [
            objects.Flavor(context=ctxt, memory_mb=512, vcpus=1,
                           root_gb=1, flavorid='1', name='m1.tiny',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=2048, vcpus=1,
                           root_gb=20, flavorid='2', name='m1.small',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=4096, vcpus=2,
                           root_gb=40, flavorid='3', name='m1.medium',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=8192, vcpus=4,
                           root_gb=80, flavorid='4', name='m1.large',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=16384, vcpus=8,
                           root_gb=160, flavorid='5', name='m1.xlarge',
                           **defaults),
            objects.Flavor(context=ctxt, memory_mb=512, vcpus=1,
                           root_gb=1, flavorid='6', name='m1.tiny.specs',
                           extra_specs=extra_specs, **defaults),
            ]
        for flavor in default_flavors:
            flavor.create()


class RPCFixture(fixtures.Fixture):
    def __init__(self, *exmods):
        super(RPCFixture, self).__init__()
        self.exmods = []
        self.exmods.extend(exmods)
        self._buses = {}

    def _fake_create_transport(self, url):
        # FIXME(danms): Right now, collapse all connections
        # to a single bus. This is how our tests expect things
        # to work. When the tests are fixed, this fixture can
        # support simulating multiple independent buses, and this
        # hack should be removed.
        url = None

        # NOTE(danms): This will be called with a non-None url by
        # cells-aware code that is requesting to contact something on
        # one of the many transports we're multplexing here.
        if url not in self._buses:
            exmods = rpc.get_allowed_exmods()
            self._buses[url] = messaging.get_rpc_transport(
                CONF,
                url=url,
                allowed_remote_exmods=exmods)
        return self._buses[url]

    def setUp(self):
        super(RPCFixture, self).setUp()
        self.addCleanup(rpc.cleanup)
        rpc.add_extra_exmods(*self.exmods)
        self.addCleanup(rpc.clear_extra_exmods)
        self.messaging_conf = messaging_conffixture.ConfFixture(CONF)
        self.messaging_conf.transport_url = 'fake:/'
        self.useFixture(self.messaging_conf)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.rpc.create_transport', self._fake_create_transport))
        # NOTE(danms): Execute the init with get_transport_url() as None,
        # instead of the parsed TransportURL(None) so that we can cache
        # it as it will be called later if the default is requested by
        # one of our mq-switching methods.
        with mock.patch('nova.rpc.get_transport_url') as mock_gtu:
            mock_gtu.return_value = None
            rpc.init(CONF)

        def cleanup_in_flight_rpc_messages():
            messaging._drivers.impl_fake.FakeExchangeManager._exchanges = {}

        self.addCleanup(cleanup_in_flight_rpc_messages)


class WarningsFixture(fixtures.Fixture):
    """Filters out warnings during test runs."""

    def setUp(self):
        super(WarningsFixture, self).setUp()
        # NOTE(sdague): Make deprecation warnings only happen once. Otherwise
        # this gets kind of crazy given the way that upstream python libs use
        # this.
        warnings.simplefilter("once", DeprecationWarning)
        warnings.filterwarnings('ignore',
                                message='With-statements now directly support'
                                        ' multiple context managers')
        # NOTE(sdague): nova does not use pkg_resources directly, this
        # is all very long standing deprecations about other tools
        # using it. None of this is useful to Nova development.
        warnings.filterwarnings('ignore',
            module='pkg_resources')
        # NOTE(sdague): this remains an unresolved item around the way
        # forward on is_admin, the deprecation is definitely really premature.
        warnings.filterwarnings('ignore',
            message='Policy enforcement is depending on the value of is_admin.'
                    ' This key is deprecated. Please update your policy '
                    'file to use the standard policy values.')
        # NOTE(sdague): mox3 is on life support, don't really care
        # about any deprecations coming from it
        warnings.filterwarnings('ignore',
            module='mox3.mox')
        # NOTE(gibi): we can remove this once we get rid of Mox in nova
        warnings.filterwarnings('ignore', message="Using class 'MoxStubout'")
        # NOTE(mriedem): Ignore scope check UserWarnings from oslo.policy.
        warnings.filterwarnings('ignore',
                                message="Policy .* failed scope check",
                                category=UserWarning)

        # NOTE(gibi): The UUIDFields emits a warning if the value is not a
        # valid UUID. Let's escalate that to an exception in the test to
        # prevent adding violations.
        warnings.filterwarnings('error', message=".*invalid UUID.*")

        # NOTE(mriedem): Avoid adding anything which tries to convert an
        # object to a primitive which jsonutils.to_primitive() does not know
        # how to handle (or isn't given a fallback callback).
        warnings.filterwarnings(
            'error',
            message="Cannot convert <oslo_db.sqlalchemy.enginefacade"
                    "._Default object at ",
            category=UserWarning)

        warnings.filterwarnings(
            'error', message='Evaluating non-mapped column expression',
            category=sqla_exc.SAWarning)

        # TODO(jangutter): Change (or remove) this to an error during the Train
        # cycle when the os-vif port profile is no longer used.
        warnings.filterwarnings(
            'ignore', message=".* 'VIFPortProfileOVSRepresentor' .* "
            "is deprecated", category=PendingDeprecationWarning)

        # TODO(mriedem): Change (or remove) this DeprecationWarning once
        # https://bugs.launchpad.net/sqlalchemy-migrate/+bug/1814288 is fixed.
        warnings.filterwarnings(
            'ignore', message=r'inspect.getargspec\(\) is deprecated',
            category=DeprecationWarning,
            module='migrate.versioning.script.py')

        # TODO(stephenfin): Remove once we bump our sqlalchemy-migrate version
        # to whatever is released early in Ussuri and includes change
        # I319785d7dd83ffe2c6e651a2494b073becc84684
        warnings.filterwarnings(
            'ignore', message='The Engine.contextual_connect.*',
            category=sqla_exc.SADeprecationWarning,
            module='migrate.changeset.databases.visitor')

        self.addCleanup(warnings.resetwarnings)


class ConfPatcher(fixtures.Fixture):
    """Fixture to patch and restore global CONF.

    This also resets overrides for everything that is patched during
    it's teardown.

    """

    def __init__(self, **kwargs):
        """Constructor

        :params group: if specified all config options apply to that group.

        :params **kwargs: the rest of the kwargs are processed as a
        set of key/value pairs to be set as configuration override.

        """
        super(ConfPatcher, self).__init__()
        self.group = kwargs.pop('group', None)
        self.args = kwargs

    def setUp(self):
        super(ConfPatcher, self).setUp()
        for k, v in self.args.items():
            self.addCleanup(CONF.clear_override, k, self.group)
            CONF.set_override(k, v, self.group)


class OSAPIFixture(fixtures.Fixture):
    """Create an OS API server as a fixture.

    This spawns an OS API server as a fixture in a new greenthread in
    the current test. The fixture has a .api parameter with is a
    simple rest client that can communicate with it.

    This fixture is extremely useful for testing REST responses
    through the WSGI stack easily in functional tests.

    Usage:

        api = self.useFixture(fixtures.OSAPIFixture()).api
        resp = api.api_request('/someurl')
        self.assertEqual(200, resp.status_code)
        resp = api.api_request('/otherurl', method='POST', body='{foo}')

    The resp is a requests library response. Common attributes that
    you'll want to use are:

    - resp.status_code - integer HTTP status code returned by the request
    - resp.content - the body of the response
    - resp.headers - dictionary of HTTP headers returned

    """

    def __init__(self, api_version='v2',
                 project_id='6f70656e737461636b20342065766572'):
        """Constructor

        :param api_version: the API version that we're interested in
        using. Currently this expects 'v2' or 'v2.1' as possible
        options.
        :param project_id: the project id to use on the API.

        """
        super(OSAPIFixture, self).__init__()
        self.api_version = api_version
        self.project_id = project_id

    def setUp(self):
        super(OSAPIFixture, self).setUp()
        # A unique hostname for the wsgi-intercept.
        hostname = uuidsentinel.osapi_host
        port = 80
        service_name = 'osapi_compute'
        endpoint = 'http://%s:%s/' % (hostname, port)
        conf_overrides = {
            'osapi_compute_listen': hostname,
            'osapi_compute_listen_port': port,
            'debug': True,
        }
        self.useFixture(ConfPatcher(**conf_overrides))

        # Turn off manipulation of socket_options in TCPKeepAliveAdapter
        # to keep wsgi-intercept happy. Replace it with the method
        # from its superclass.
        self.useFixture(fixtures.MonkeyPatch(
                'keystoneauth1.session.TCPKeepAliveAdapter.init_poolmanager',
                adapters.HTTPAdapter.init_poolmanager))

        loader = wsgi.Loader().load_app(service_name)
        app = lambda: loader

        # re-use service setup code from wsgi_app to register
        # service, which is looked for in some tests
        wsgi_app._setup_service(CONF.host, service_name)
        intercept = interceptor.RequestsInterceptor(app, url=endpoint)
        intercept.install_intercept()
        self.addCleanup(intercept.uninstall_intercept)

        self.auth_url = 'http://%(host)s:%(port)s/%(api_version)s' % ({
            'host': hostname, 'port': port, 'api_version': self.api_version})
        self.api = client.TestOpenStackClient('fake', 'fake', self.auth_url,
                                              self.project_id)
        self.admin_api = client.TestOpenStackClient(
            'admin', 'admin', self.auth_url, self.project_id)
        # Provide a way to access the wsgi application to tests using
        # the fixture.
        self.app = app


class OSMetadataServer(fixtures.Fixture):
    """Create an OS Metadata API server as a fixture.

    This spawns an OS Metadata API server as a fixture in a new
    greenthread in the current test.

    TODO(sdague): ideally for testing we'd have something like the
    test client which acts like requests, but connects any of the
    interactions needed.

    """
    def setUp(self):
        super(OSMetadataServer, self).setUp()
        # in order to run these in tests we need to bind only to local
        # host, and dynamically allocate ports
        conf_overrides = {
            'metadata_listen': '127.0.0.1',
            'metadata_listen_port': 0,
            'debug': True
        }
        self.useFixture(ConfPatcher(**conf_overrides))

        # NOTE(mikal): we don't have root to manipulate iptables, so just
        # zero that bit out.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.network.linux_net.IptablesManager._apply',
            lambda _: None))

        self.metadata = service.WSGIService("metadata")
        self.metadata.start()
        self.addCleanup(self.metadata.stop)
        self.md_url = "http://%s:%s/" % (
            conf_overrides['metadata_listen'],
            self.metadata.port)


class PoisonFunctions(fixtures.Fixture):
    """Poison functions so they explode if we touch them.

    When running under a non full stack test harness there are parts
    of the code that you don't want to go anywhere near. These include
    things like code that spins up extra threads, which just
    introduces races.

    """

    def setUp(self):
        super(PoisonFunctions, self).setUp()

        # The nova libvirt driver starts an event thread which only
        # causes trouble in tests. Make sure that if tests don't
        # properly patch it the test explodes.

        def evloop(*args, **kwargs):
            import sys
            warnings.warn("Forgot to disable libvirt event thread")
            sys.exit(1)

        # Don't poison the function if it's already mocked
        import nova.virt.libvirt.host
        if not isinstance(nova.virt.libvirt.host.Host._init_events, mock.Mock):
            self.useFixture(fixtures.MockPatch(
                'nova.virt.libvirt.host.Host._init_events',
                side_effect=evloop))


class IndirectionAPIFixture(fixtures.Fixture):
    """Patch and restore the global NovaObject indirection api."""

    def __init__(self, indirection_api):
        """Constructor

        :param indirection_api: the indirection API to be used for tests.

        """
        super(IndirectionAPIFixture, self).__init__()
        self.indirection_api = indirection_api

    def cleanup(self):
        obj_base.NovaObject.indirection_api = self.orig_indirection_api

    def setUp(self):
        super(IndirectionAPIFixture, self).setUp()
        self.orig_indirection_api = obj_base.NovaObject.indirection_api
        obj_base.NovaObject.indirection_api = self.indirection_api
        self.addCleanup(self.cleanup)


class _FakeGreenThread(object):
    def __init__(self, func, *args, **kwargs):
        self._result = func(*args, **kwargs)

    def cancel(self, *args, **kwargs):
        # This method doesn't make sense for a synchronous call, it's just
        # defined to satisfy the interface.
        pass

    def kill(self, *args, **kwargs):
        # This method doesn't make sense for a synchronous call, it's just
        # defined to satisfy the interface.
        pass

    def link(self, func, *args, **kwargs):
        func(self, *args, **kwargs)

    def unlink(self, func, *args, **kwargs):
        # This method doesn't make sense for a synchronous call, it's just
        # defined to satisfy the interface.
        pass

    def wait(self):
        return self._result


class SpawnIsSynchronousFixture(fixtures.Fixture):
    """Patch and restore the spawn_n utility method to be synchronous"""

    def setUp(self):
        super(SpawnIsSynchronousFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.utils.spawn_n', _FakeGreenThread))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.utils.spawn', _FakeGreenThread))


class _FakeExecutor(futurist.SynchronousExecutor):
    def __init__(self, *args, **kwargs):
        # Ignore kwargs (example: max_workers) that SynchronousExecutor
        # does not support.
        super(_FakeExecutor, self).__init__()


class SynchronousThreadPoolExecutorFixture(fixtures.Fixture):
    """Make GreenThreadPoolExecutor synchronous.

    Replace the GreenThreadPoolExecutor with the SynchronousExecutor.
    """
    def setUp(self):
        super(SynchronousThreadPoolExecutorFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'futurist.GreenThreadPoolExecutor', _FakeExecutor))


class BannedDBSchemaOperations(fixtures.Fixture):
    """Ban some operations for migrations"""
    def __init__(self, banned_resources=None):
        super(BannedDBSchemaOperations, self).__init__()
        self._banned_resources = banned_resources or []

    @staticmethod
    def _explode(resource, op):
        raise exception.DBNotAllowed(
            'Operation %s.%s() is not allowed in a database migration' % (
                resource, op))

    def setUp(self):
        super(BannedDBSchemaOperations, self).setUp()
        for thing in self._banned_resources:
            self.useFixture(fixtures.MonkeyPatch(
                'sqlalchemy.%s.drop' % thing,
                lambda *a, **k: self._explode(thing, 'drop')))
            self.useFixture(fixtures.MonkeyPatch(
                'sqlalchemy.%s.alter' % thing,
                lambda *a, **k: self._explode(thing, 'alter')))


class ForbidNewLegacyNotificationFixture(fixtures.Fixture):
    """Make sure the test fails if new legacy notification is added"""
    def __init__(self):
        super(ForbidNewLegacyNotificationFixture, self).__init__()
        self.notifier = rpc.LegacyValidatingNotifier

    def setUp(self):
        super(ForbidNewLegacyNotificationFixture, self).setUp()
        self.notifier.fatal = True

        # allow the special test value used in
        # nova.tests.unit.test_notifications.NotificationsTestCase
        self.notifier.allowed_legacy_notification_event_types.append(
                '_decorated_function')

        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.notifier.fatal = False
        self.notifier.allowed_legacy_notification_event_types.remove(
                '_decorated_function')


class AllServicesCurrent(fixtures.Fixture):
    def setUp(self):
        super(AllServicesCurrent, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.Service.get_minimum_version_multi',
            self._fake_minimum))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.service.get_minimum_version_all_cells',
            lambda *a, **k: service_obj.SERVICE_VERSION))
        compute_rpcapi.LAST_VERSION = None

    def _fake_minimum(self, *args, **kwargs):
        return service_obj.SERVICE_VERSION


class RegisterNetworkQuota(fixtures.Fixture):
    def setUp(self):
        super(RegisterNetworkQuota, self).setUp()
        # Quota resource registration modifies the global QUOTAS engine, so
        # this fixture registers and unregisters network quota for a test.
        tenant_networks._register_network_quota()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        nova_quota.QUOTAS._resources.pop('networks', None)


class NeutronFixture(fixtures.Fixture):
    """A fixture to boot instances with neutron ports"""

    # the default project_id in OsaAPIFixtures
    tenant_id = '6f70656e737461636b20342065766572'
    network_1 = {
        'status': 'ACTIVE',
        'subnets': [],
        'name': 'private-network',
        'admin_state_up': True,
        'tenant_id': tenant_id,
        'id': '3cb9bc59-5699-4588-a4b1-b87f96708bc6',
        'shared': False,
    }
    subnet_1 = {
        'name': 'private-subnet',
        'enable_dhcp': True,
        'network_id': network_1['id'],
        'tenant_id': tenant_id,
        'dns_nameservers': [],
        'allocation_pools': [
            {
                'start': '192.168.1.1',
                'end': '192.168.1.254'
            }
        ],
        'host_routes': [],
        'ip_version': 4,
        'gateway_ip': '192.168.1.1',
        'cidr': '192.168.1.1/24',
        'id': 'f8a6e8f8-c2ec-497c-9f23-da9616de54ef'
    }
    network_1['subnets'] = [subnet_1['id']]

    port_1 = {
        'id': 'ce531f90-199f-48c0-816c-13e38010b442',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': 'fa:16:3e:4c:2c:30',
        'fixed_ips': [
            {
                # The IP on this port must be a prefix of the IP on port_2 to
                # test listing servers with an ip filter regex.
                'ip_address': '192.168.1.3',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        'binding:vif_type': 'ovs'
    }

    port_2 = {
        'id': '88dae9fa-0dc6-49e3-8c29-3abc41e99ac9',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '00:0c:29:0d:11:74',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.30',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        'binding:vif_type': 'ovs'
    }

    port_with_resource_request = {
        'id': '2f2613ce-95a9-490a-b3c4-5f1c28c1f886',
        'network_id': network_1['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c3',
        'fixed_ips': [
            {
                'ip_address': '192.168.1.42',
                'subnet_id': subnet_1['id']
            }
        ],
        'tenant_id': tenant_id,
        neutron_constants.RESOURCE_REQUEST: {
            "resources": {
                    orc.NET_BW_IGR_KILOBIT_PER_SEC: 1000,
                    orc.NET_BW_EGR_KILOBIT_PER_SEC: 1000},
            "required": ["CUSTOM_PHYSNET2", "CUSTOM_VNIC_TYPE_NORMAL"]
        }
    }

    network_2 = {
        'status': 'ACTIVE',
        'subnets': [],
        'name': 'private-network',
        'admin_state_up': True,
        'tenant_id': tenant_id,
        'id': '1b70879f-fd00-411e-8ea9-143e7820e61d',
        'shared': False,
        'provider:physical_network': 'physnet2',
        "provider:network_type": "vlan",
    }

    subnet_2 = {
        'name': 'private-subnet',
        'enable_dhcp': True,
        'network_id': network_2['id'],
        'tenant_id': tenant_id,
        'dns_nameservers': [],
        'allocation_pools': [
            {
                'start': '192.168.13.1',
                'end': '192.168.1.254'
            }
        ],
        'host_routes': [],
        'ip_version': 4,
        'gateway_ip': '192.168.1.1',
        'cidr': '192.168.1.1/24',
        'id': 'c7ca1baf-f536-4849-89fe-9671318375ff'
    }
    network_2['subnets'] = [subnet_2['id']]

    sriov_port = {
        'id': '5460ee0c-ffbb-4e45-8d58-37bfceabd084',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c4',
        'fixed_ips': [
            {
                'ip_address': '192.168.13.2',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        neutron_constants.RESOURCE_REQUEST: {},
        'binding:vnic_type': 'direct',
    }

    port_with_sriov_resource_request = {
        'id': '7059503b-a648-40fd-a561-5ca769304bee',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c5',
        # Do neutron really adds fixed_ips to an direct vnic_type port?
        'fixed_ips': [
            {
                'ip_address': '192.168.13.3',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        neutron_constants.RESOURCE_REQUEST: {
            "resources": {
                orc.NET_BW_IGR_KILOBIT_PER_SEC: 10000,
                orc.NET_BW_EGR_KILOBIT_PER_SEC: 10000},
            "required": ["CUSTOM_PHYSNET2", "CUSTOM_VNIC_TYPE_DIRECT"]
        },
        'binding:vnic_type': 'direct',
    }

    port_macvtap_with_resource_request = {
        'id': 'cbb9707f-3559-4675-a973-4ea89c747f02',
        'network_id': network_2['id'],
        'admin_state_up': True,
        'status': 'ACTIVE',
        'mac_address': '52:54:00:1e:59:c6',
        # Do neutron really adds fixed_ips to an direct vnic_type port?
        'fixed_ips': [
            {
                'ip_address': '192.168.13.4',
                'subnet_id': subnet_2['id']
            }
        ],
        'tenant_id': tenant_id,
        neutron_constants.RESOURCE_REQUEST: {
            "resources": {
                orc.NET_BW_IGR_KILOBIT_PER_SEC: 10000,
                orc.NET_BW_EGR_KILOBIT_PER_SEC: 10000},
            "required": ["CUSTOM_PHYSNET2", "CUSTOM_VNIC_TYPE_MACVTAP"]
        },
        'binding:vnic_type': 'macvtap',
    }

    nw_info = [{
        "profile": {},
        "ovs_interfaceid": "b71f1699-42be-4515-930a-f3ef01f94aa7",
        "preserve_on_delete": False,
        "network": {
            "bridge": "br-int",
            "subnets": [{
                "ips": [{
                    "meta": {},
                    "version": 4,
                    "type": "fixed",
                    "floating_ips": [],
                    "address": "10.0.0.4"
                }],
                "version": 4,
                "meta": {},
                "dns": [],
                "routes": [],
                "cidr": "10.0.0.0/26",
                "gateway": {
                    "meta": {},
                    "version": 4,
                    "type": "gateway",
                    "address": "10.0.0.1"
                }
            }],
            "meta": {
                "injected": False,
                "tenant_id": tenant_id,
                "mtu": 1500
            },
            "id": "e1882e38-38c2-4239-ade7-35d644cb963a",
            "label": "public"
        },
        "devname": "tapb71f1699-42",
        "vnic_type": "normal",
        "qbh_params": None,
        "meta": {},
        "details": {
            "port_filter": True,
            "ovs_hybrid_plug": True
        },
        "address": "fa:16:3e:47:94:4a",
        "active": True,
        "type": "ovs",
        "id": "b71f1699-42be-4515-930a-f3ef01f94aa7",
        "qbg_params": None
    }]

    def __init__(self, test):
        super(NeutronFixture, self).__init__()
        self.test = test
        # The fixture allows port update so we need to deepcopy the class
        # variables to avoid test case interference.
        self._ports = {
            # NOTE(gibi)The port_with_sriov_resource_request cannot be added
            # globally in this fixture as it adds a second network that makes
            # auto allocation based test to fail due to ambiguous networks.
            NeutronFixture.port_1['id']: copy.deepcopy(NeutronFixture.port_1),
            NeutronFixture.port_with_resource_request['id']:
                copy.deepcopy(NeutronFixture.port_with_resource_request)
        }

        # The fixture does not allow network update so we don't have to
        # deepcopy here
        self._networks = {
            NeutronFixture.network_1['id']: NeutronFixture.network_1
        }
        # The fixture does not allow network update so we don't have to
        # deepcopy here
        self._subnets = {
            NeutronFixture.subnet_1['id']: NeutronFixture.subnet_1
        }

    def setUp(self):
        super(NeutronFixture, self).setUp()

        self.test.stub_out(
            'nova.network.neutronv2.api.API.setup_networks_on_host',
            lambda *args, **kwargs: None)
        self.test.stub_out(
            'nova.network.neutronv2.api.API.migrate_instance_start',
            lambda *args, **kwargs: None)
        self.test.stub_out(
            'nova.network.neutronv2.api.API.add_fixed_ip_to_instance',
            lambda *args, **kwargs: network_model.NetworkInfo.hydrate(
                NeutronFixture.nw_info))
        self.test.stub_out(
            'nova.network.neutronv2.api.API.remove_fixed_ip_from_instance',
            lambda *args, **kwargs: network_model.NetworkInfo.hydrate(
                NeutronFixture.nw_info))
        self.test.stub_out(
            'nova.network.security_group.neutron_driver.SecurityGroupAPI.'
            'get_instances_security_groups_bindings',
            lambda *args, **kwargs: {})

        # Stub out port binding APIs which go through a KSA client Adapter
        # rather than python-neutronclient.
        self.test.stub_out(
            'nova.network.neutronv2.api._get_ksa_client',
            lambda *args, **kwargs: mock.Mock(
                spec=ksa_adap.Adapter))
        self.test.stub_out(
            'nova.network.neutronv2.api.API._create_port_binding',
            self.fake_create_port_binding)
        self.test.stub_out(
            'nova.network.neutronv2.api.API._delete_port_binding',
            self.fake_delete_port_binding)

        self.test.stub_out('nova.network.neutronv2.api.get_client',
                           self._get_client)

    def _get_client(self, context, admin=False):
        # NOTE(gibi): This is a hack. As we return the same fixture for each
        # get_client call there is no way to later know that a call came
        # through which client. We store the parameters of the last get_client
        # call. Later we should return a new client object from this call that
        # is wrapping the fixture and this client can remember how it was
        # initialized.

        # This logic is copied from nova.network.neutronv2.api._get_auth_plugin
        self.is_admin_client = (admin or
                                (context.is_admin and not context.auth_token))
        return self

    @staticmethod
    def fake_create_port_binding(context, client, port_id, data):
        # TODO(mriedem): Make this smarter by keeping track of our bindings
        # per port so we can reflect the status accurately.
        return fake_requests.FakeResponse(200, content=jsonutils.dumps(data))

    @staticmethod
    def fake_delete_port_binding(context, client, port_id, host):
        # TODO(mriedem): Make this smarter by keeping track of our bindings
        # per port so we can reflect the status accurately.
        return fake_requests.FakeResponse(204)

    def _get_first_id_match(self, id, list):
        filtered_list = [p for p in list if p['id'] == id]
        if len(filtered_list) > 0:
            return filtered_list[0]
        else:
            return None

    def list_extensions(self, *args, **kwargs):
        return {
            'extensions': [
                {
                    # Copied from neutron-lib portbindings_extended.py
                    "updated": "2017-07-17T10:00:00-00:00",
                    "name": neutron_constants.PORT_BINDING_EXTENDED,
                    "links": [],
                    "alias": "binding-extended",
                    "description": "Expose port bindings of a virtual port to "
                                   "external application"
                }
            ]
        }

    def show_port(self, port_id, **_params):
        if port_id not in self._ports:
            raise exception.PortNotFound(port_id=port_id)
        return {'port': copy.deepcopy(self._ports[port_id])}

    def delete_port(self, port_id, **_params):
        if port_id in self._ports:
            del self._ports[port_id]

    def show_network(self, network_id, **_params):
        if network_id not in self._networks:
            raise neutron_client_exc.NetworkNotFoundClient()
        return {'network': copy.deepcopy(self._networks[network_id])}

    def list_networks(self, retrieve_all=True, **_params):
        networks = self._networks.values()
        if 'id' in _params:
            networks = [x for x in networks if x['id'] in _params['id']]
            _params.pop('id')
        networks = [n for n in networks
                    if all(n.get(opt) == _params[opt] for opt in _params)]
        return {'networks': copy.deepcopy(networks)}

    def list_ports(self, retrieve_all=True, **_params):
        # If 'fields' is passed we need to strip that out since it will mess
        # up the filtering as 'fields' is not a filter parameter.
        _params.pop('fields', None)
        ports = [p for p in self._ports.values()
                 if all(p.get(opt) == _params[opt] for opt in _params)]
        if not self.is_admin_client:
            # Neutron returns None instead of the real resource_request if
            # the ports are queried by a non-admin. So simulate this behavior
            # here
            for port in ports:
                if 'resource_request' in port:
                    port['resource_request'] = None

        return {'ports': copy.deepcopy(ports)}

    def list_subnets(self, retrieve_all=True, **_params):
        # NOTE(gibi): The fixture does not support filtering for subnets
        return {'subnets': copy.deepcopy(list(self._subnets.values()))}

    def list_floatingips(self, retrieve_all=True, **_params):
        return {'floatingips': []}

    def create_port(self, body=None):
        # Note(gibi): Some of the test expects that a pre-defined port is
        # created. This is port_2. So if that port is not created yet then
        # that is the one created here.
        if NeutronFixture.port_2['id'] not in self._ports:
            new_port = copy.deepcopy(NeutronFixture.port_2)
        else:
            # If port_2 is already created then create a new port based on
            # the request body, the port_2 as a template, and assign new
            # port_id and mac_address for the new port
            new_port = copy.deepcopy(body)
            new_port.update(copy.deepcopy(NeutronFixture.port_2))
            # we need truly random uuids instead of named sentinels as some
            # tests needs more than 3 ports
            new_port.update({
                'id': str(uuidutils.generate_uuid()),
                'mac_address': '00:' + ':'.join(
                    ['%02x' % random.randint(0, 255) for _ in range(5)]),
            })
        self._ports[new_port['id']] = new_port
        # we need to copy again what we return as nova might modify the
        # returned port locally and we don't want that it effects the port in
        # the self._ports dict.
        return {'port': copy.deepcopy(new_port)}

    def update_port(self, port_id, body=None):
        port = self._ports[port_id]
        # We need to deepcopy here as well as the body can have a nested dict
        # which can be modified by the caller after this update_port call
        port.update(copy.deepcopy(body['port']))
        return {'port': copy.deepcopy(port)}

    def show_quota(self, project_id):
        # unlimited quota
        return {'quota': {'port': -1}}


class _NoopConductor(object):
    def __getattr__(self, key):
        def _noop_rpc(*args, **kwargs):
            return None
        return _noop_rpc


class NoopConductorFixture(fixtures.Fixture):
    """Stub out the conductor API to do nothing"""

    def setUp(self):
        super(NoopConductorFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.conductor.ComputeTaskAPI', _NoopConductor))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.conductor.API', _NoopConductor))


class EventReporterStub(fixtures.Fixture):

    def setUp(self):
        super(EventReporterStub, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.compute.utils.EventReporter',
            lambda *args, **kwargs: mock.MagicMock()))


class CinderFixture(fixtures.Fixture):
    """A fixture to volume operations with the new Cinder attach/detach API"""

    # the default project_id in OSAPIFixtures
    tenant_id = '6f70656e737461636b20342065766572'

    SWAP_OLD_VOL = 'a07f71dc-8151-4e7d-a0cc-cd24a3f11113'
    SWAP_NEW_VOL = '227cc671-f30b-4488-96fd-7d0bf13648d8'
    SWAP_ERR_OLD_VOL = '828419fa-3efb-4533-b458-4267ca5fe9b1'
    SWAP_ERR_NEW_VOL = '9c6d9c2d-7a8f-4c80-938d-3bf062b8d489'
    SWAP_ERR_ATTACH_ID = '4a3cd440-b9c2-11e1-afa6-0800200c9a66'
    MULTIATTACH_VOL = '4757d51f-54eb-4442-8684-3399a6431f67'

    # This represents a bootable image-backed volume to test
    # boot-from-volume scenarios.
    IMAGE_BACKED_VOL = '6ca404f3-d844-4169-bb96-bc792f37de98'
    # This represents a bootable image-backed volume with required traits
    # as part of volume image metadata
    IMAGE_WITH_TRAITS_BACKED_VOL = '6194fc02-c60e-4a01-a8e5-600798208b5f'

    def __init__(self, test, az='nova'):
        """Initialize this instance of the CinderFixture.

        :param test: The TestCase using this fixture.
        :param az: The availability zone to return in volume GET responses.
            Defaults to "nova" since that is the default we would see
            from Cinder's storage_availability_zone config option.
        """
        super(CinderFixture, self).__init__()
        self.test = test
        self.swap_volume_instance_uuid = None
        self.swap_volume_instance_error_uuid = None
        self.attachment_error_id = None
        self.az = az
        # A dict, keyed by volume id, to a dict, keyed by attachment id,
        # with keys:
        # - id: the attachment id
        # - instance_uuid: uuid of the instance attached to the volume
        # - connector: host connector dict; None if not connected
        # Note that a volume can have multiple attachments even without
        # multi-attach, as some flows create a blank 'reservation' attachment
        # before deleting another attachment. However, a non-multiattach volume
        # can only have at most one attachment with a host connector at a time.
        self.volume_to_attachment = collections.defaultdict(dict)

    def volume_ids_for_instance(self, instance_uuid):
        for volume_id, attachments in self.volume_to_attachment.items():
            for attachment in attachments.values():
                if attachment['instance_uuid'] == instance_uuid:
                    # we might have multiple volumes attached to this instance
                    # so yield rather than return
                    yield volume_id
                    break

    def setUp(self):
        super(CinderFixture, self).setUp()

        def fake_get(self_api, context, volume_id, microversion=None):
            # Check for the special swap volumes.
            attachments = self.volume_to_attachment[volume_id]

            if volume_id in (self.SWAP_OLD_VOL,
                             self.SWAP_ERR_OLD_VOL):
                volume = {
                             'status': 'available',
                             'display_name': 'TEST1',
                             'attach_status': 'detached',
                             'id': volume_id,
                             'multiattach': False,
                             'size': 1
                         }
                if ((self.swap_volume_instance_uuid and
                     volume_id == self.SWAP_OLD_VOL) or
                    (self.swap_volume_instance_error_uuid and
                     volume_id == self.SWAP_ERR_OLD_VOL)):
                    instance_uuid = (self.swap_volume_instance_uuid
                        if volume_id == self.SWAP_OLD_VOL
                        else self.swap_volume_instance_error_uuid)

                    if attachments:
                        attachment = list(attachments.values())[0]

                        volume.update({
                            'status': 'in-use',
                            'attachments': {
                                instance_uuid: {
                                    'mountpoint': '/dev/vdb',
                                    'attachment_id': attachment['id']
                                }
                            },
                            'attach_status': 'attached'
                        })
                    return volume

            # Check to see if the volume is attached.
            if attachments:
                # The volume is attached.
                attachment = list(attachments.values())[0]
                volume = {
                    'status': 'in-use',
                    'display_name': volume_id,
                    'attach_status': 'attached',
                    'id': volume_id,
                    'multiattach': volume_id == self.MULTIATTACH_VOL,
                    'size': 1,
                    'attachments': {
                        attachment['instance_uuid']: {
                            'attachment_id': attachment['id'],
                            'mountpoint': '/dev/vdb'
                        }
                    }
                }
            else:
                # This is a test that does not care about the actual details.
                volume = {
                    'status': 'available',
                    'display_name': 'TEST2',
                    'attach_status': 'detached',
                    'id': volume_id,
                    'multiattach': volume_id == self.MULTIATTACH_VOL,
                    'size': 1
                }

            if 'availability_zone' not in volume:
                volume['availability_zone'] = self.az

            # Check for our special image-backed volume.
            if volume_id in (self.IMAGE_BACKED_VOL,
                             self.IMAGE_WITH_TRAITS_BACKED_VOL):
                # Make it a bootable volume.
                volume['bootable'] = True
                if volume_id == self.IMAGE_BACKED_VOL:
                    # Add the image_id metadata.
                    volume['volume_image_metadata'] = {
                        # There would normally be more image metadata in here.
                        'image_id': '155d900f-4e14-4e4c-a73d-069cbf4541e6'
                    }
                elif volume_id == self.IMAGE_WITH_TRAITS_BACKED_VOL:
                    # Add the image_id metadata with traits.
                    volume['volume_image_metadata'] = {
                        'image_id': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                        "trait:HW_CPU_X86_SGX": "required",
                    }

            return volume

        def fake_migrate_volume_completion(_self, context, old_volume_id,
                                           new_volume_id, error):
            return {'save_volume_id': new_volume_id}

        def _find_attachment(attachment_id):
            """Find attachment corresponding to ``attachment_id``.

            Returns:
                A tuple of the volume ID, an attachment dict
                for the given attachment ID, and a dict (keyed by attachment
                id) of attachment dicts for the volume.
            """
            for volume_id, attachments in self.volume_to_attachment.items():
                for attachment in attachments.values():
                    if attachment_id == attachment['id']:
                        return volume_id, attachment, attachments
            raise exception.VolumeAttachmentNotFound(
                attachment_id=attachment_id)

        def fake_attachment_create(_self, context, volume_id, instance_uuid,
                                   connector=None, mountpoint=None):
            attachment_id = uuidutils.generate_uuid()
            if self.attachment_error_id is not None:
                attachment_id = self.attachment_error_id
            attachment = {'id': attachment_id, 'connection_info': {'data': {}}}
            self.volume_to_attachment[volume_id][attachment_id] = {
                'id': attachment_id,
                'instance_uuid': instance_uuid,
                'connector': connector}
            LOG.info('Created attachment %s for volume %s. Total '
                     'attachments for volume: %d', attachment_id, volume_id,
                     len(self.volume_to_attachment[volume_id]))

            return attachment

        def fake_attachment_delete(_self, context, attachment_id):
            # 'attachment' is a tuple defining a attachment-instance mapping
            volume_id, attachment, attachments = (
                _find_attachment(attachment_id))
            del attachments[attachment_id]
            LOG.info('Deleted attachment %s for volume %s. Total attachments '
                     'for volume: %d', attachment_id, volume_id,
                     len(attachments))

        def fake_attachment_update(_self, context, attachment_id, connector,
                                   mountpoint=None):
            # Ensure the attachment exists
            volume_id, attachment, attachments = (
                _find_attachment(attachment_id))
            # Cinder will only allow one "connected" attachment per
            # non-multiattach volume at a time.
            if volume_id != self.MULTIATTACH_VOL:
                for _attachment in attachments.values():
                    if _attachment['connector'] is not None:
                        raise exception.InvalidInput(
                            'Volume %s is already connected with attachment '
                            '%s on host %s' % (volume_id, _attachment['id'],
                            _attachment['connector'].get('host')))
            attachment['connector'] = connector
            LOG.info('Updating volume attachment: %s', attachment_id)
            attachment_ref = {'driver_volume_type': 'fake_type',
                              'id': attachment_id,
                              'connection_info': {'data':
                                                  {'foo': 'bar',
                                                   'target_lun': '1'}}}
            if attachment_id == self.SWAP_ERR_ATTACH_ID:
                # This intentionally triggers a TypeError for the
                # instance.volume_swap.error versioned notification tests.
                attachment_ref = {'connection_info': ()}
            return attachment_ref

        def fake_attachment_get(_self, context, attachment_id):
            # Ensure the attachment exists
            _find_attachment(attachment_id)
            attachment_ref = {'driver_volume_type': 'fake_type',
                              'id': attachment_id,
                              'connection_info': {'data':
                                                  {'foo': 'bar',
                                                   'target_lun': '1'}}}
            return attachment_ref

        def fake_get_all_volume_types(*args, **kwargs):
            return [{
                # This is used in the 2.67 API sample test.
                'id': '5f9204ec-3e94-4f27-9beb-fe7bb73b6eb9',
                'name': 'lvm-1'
            }]

        def fake_attachment_complete(_self, _context, attachment_id):
            # Ensure the attachment exists
            _find_attachment(attachment_id)
            LOG.info('Completing volume attachment: %s', attachment_id)

        self.test.stub_out('nova.volume.cinder.API.attachment_create',
                           fake_attachment_create)
        self.test.stub_out('nova.volume.cinder.API.attachment_delete',
                           fake_attachment_delete)
        self.test.stub_out('nova.volume.cinder.API.attachment_update',
                           fake_attachment_update)
        self.test.stub_out('nova.volume.cinder.API.attachment_complete',
                           fake_attachment_complete)
        self.test.stub_out('nova.volume.cinder.API.attachment_get',
                           fake_attachment_get)
        self.test.stub_out('nova.volume.cinder.API.begin_detaching',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.get',
                           fake_get)
        self.test.stub_out(
            'nova.volume.cinder.API.migrate_volume_completion',
            fake_migrate_volume_completion)
        self.test.stub_out('nova.volume.cinder.API.roll_detaching',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.is_microversion_supported',
                           lambda ctxt, microversion: None)
        self.test.stub_out('nova.volume.cinder.API.check_attached',
                           lambda *args, **kwargs: None)
        self.test.stub_out('nova.volume.cinder.API.get_all_volume_types',
                           fake_get_all_volume_types)


class UnHelperfulClientChannel(privsep_daemon._ClientChannel):
    def __init__(self, context):
        raise Exception('You have attempted to start a privsep helper. '
                        'This is not allowed in the gate, and '
                        'indicates a failure to have mocked your tests.')


class PrivsepNoHelperFixture(fixtures.Fixture):
    """A fixture to catch failures to mock privsep's rootwrap helper.

    If you fail to mock away a privsep'd method in a unit test, then
    you may well end up accidentally running the privsep rootwrap
    helper. This will fail in the gate, but it fails in a way which
    doesn't identify which test is missing a mock. Instead, we
    raise an exception so that you at least know where you've missed
    something.
    """

    def setUp(self):
        super(PrivsepNoHelperFixture, self).setUp()

        self.useFixture(fixtures.MonkeyPatch(
            'oslo_privsep.daemon.RootwrapClientChannel',
            UnHelperfulClientChannel))


class PrivsepFixture(fixtures.Fixture):
    """Disable real privsep checking so we can test the guts of methods
    decorated with sys_admin_pctxt.
    """
    def setUp(self):
        super(PrivsepFixture, self).setUp()
        self.useFixture(fixtures.MockPatchObject(
            nova.privsep.sys_admin_pctxt, 'client_mode', False))


class NoopQuotaDriverFixture(fixtures.Fixture):
    """A fixture to run tests using the NoopQuotaDriver.

    We can't simply set self.flags to the NoopQuotaDriver in tests to use the
    NoopQuotaDriver because the QuotaEngine object is global. Concurrently
    running tests will fail intermittently because they might get the
    NoopQuotaDriver globally when they expected the default DbQuotaDriver
    behavior. So instead, we can patch the _driver property of the QuotaEngine
    class on a per-test basis.
    """

    def setUp(self):
        super(NoopQuotaDriverFixture, self).setUp()
        self.useFixture(fixtures.MonkeyPatch('nova.quota.QuotaEngine._driver',
                        nova_quota.NoopQuotaDriver()))
        # Set the config option just so that code checking for the presence of
        # the NoopQuotaDriver setting will see it as expected.
        # For some reason, this does *not* work when TestCase.flags is used.
        # When using self.flags, the concurrent test failures returned.
        CONF.set_override('driver', 'nova.quota.NoopQuotaDriver', 'quota')
        self.addCleanup(CONF.clear_override, 'driver', 'quota')


class DownCellFixture(fixtures.Fixture):
    """A fixture to simulate when a cell is down either due to error or timeout

    This fixture will stub out the scatter_gather_cells routine and target_cell
    used in various cells-related API operations like listing/showing server
    details to return a ``oslo_db.exception.DBError`` per cell in the results.
    Therefore it is best used with a test scenario like this:

    1. Create a server successfully.
    2. Using the fixture, list/show servers. Depending on the microversion
       used, the API should either return minimal results or by default skip
       the results from down cells.

    Example usage::

        with nova_fixtures.DownCellFixture():
            # List servers with down cells.
            self.api.get_servers()
            # Show a server in a down cell.
            self.api.get_server(server['id'])
            # List services with down cells.
            self.admin_api.api_get('/os-services')
    """
    def __init__(self, down_cell_mappings=None):
        self.down_cell_mappings = down_cell_mappings

    def setUp(self):
        super(DownCellFixture, self).setUp()

        def stub_scatter_gather_cells(ctxt, cell_mappings, timeout, fn, *args,
                                      **kwargs):
            # Return a dict with an entry per cell mapping where the results
            # are some kind of exception.
            up_cell_mappings = objects.CellMappingList()
            if not self.down_cell_mappings:
                # User has not passed any down cells explicitly, so all cells
                # are considered as down cells.
                self.down_cell_mappings = cell_mappings
            else:
                # User has passed down cell mappings, so the rest of the cells
                # should be up meaning we should return the right results.
                # We assume that down cells will be a subset of the
                # cell_mappings.
                down_cell_uuids = [cell.uuid
                    for cell in self.down_cell_mappings]
                up_cell_mappings.objects = [cell
                    for cell in cell_mappings
                        if cell.uuid not in down_cell_uuids]

            def wrap(cell_uuid, thing):
                # We should embed the cell_uuid into the context before
                # wrapping since its used to calcualte the cells_timed_out and
                # cells_failed properties in the object.
                ctxt.cell_uuid = cell_uuid
                return multi_cell_list.RecordWrapper(ctxt, sort_ctx, thing)

            if fn is multi_cell_list.query_wrapper:
                # If the function called through scatter-gather utility is the
                # multi_cell_list.query_wrapper, we should wrap the exception
                # object into the multi_cell_list.RecordWrapper. This is
                # because unlike the other functions where the exception object
                # is returned directly, the query_wrapper wraps this into the
                # RecordWrapper object format. So if we do not wrap it will
                # blow up at the point of generating results from heapq further
                # down the stack.
                sort_ctx = multi_cell_list.RecordSortContext([], [])
                ret1 = {
                    cell_mapping.uuid: [wrap(cell_mapping.uuid,
                        db_exc.DBError())]
                    for cell_mapping in self.down_cell_mappings
                }
            else:
                ret1 = {
                    cell_mapping.uuid: db_exc.DBError()
                    for cell_mapping in self.down_cell_mappings
                }
            ret2 = {}
            for cell in up_cell_mappings:
                ctxt.cell_uuid = cell.uuid
                cctxt = context.RequestContext.from_dict(ctxt.to_dict())
                context.set_target_cell(cctxt, cell)
                result = fn(cctxt, *args, **kwargs)
                ret2[cell.uuid] = result
            return dict(list(ret1.items()) + list(ret2.items()))

        @contextmanager
        def stub_target_cell(ctxt, cell_mapping):
            # This is to give the freedom to simulate down cells for each
            # individual cell targeted function calls.
            if not self.down_cell_mappings:
                # User has not passed any down cells explicitly, so all cells
                # are considered as down cells.
                self.down_cell_mappings = [cell_mapping]
                raise db_exc.DBError()
            else:
                # if down_cell_mappings are passed, then check if this cell
                # is down or up.
                down_cell_uuids = [cell.uuid
                    for cell in self.down_cell_mappings]
                if cell_mapping.uuid in down_cell_uuids:
                    # its a down cell raise the exception straight away
                    raise db_exc.DBError()
                else:
                    # its an up cell, so yield its context
                    cctxt = context.RequestContext.from_dict(ctxt.to_dict())
                    context.set_target_cell(cctxt, cell_mapping)
                    yield cctxt

        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.scatter_gather_cells', stub_scatter_gather_cells))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.context.target_cell', stub_target_cell))


class AvailabilityZoneFixture(fixtures.Fixture):
    """Fixture to stub out the nova.availability_zones module

    The list of ``zones`` provided to the fixture are what get returned from
    ``get_availability_zones``.

    ``get_instance_availability_zone`` will return the availability_zone
    requested when creating a server otherwise the instance.availabilty_zone
    or default_availability_zone is returned.
    """
    def __init__(self, zones):
        self.zones = zones

    def setUp(self):
        super(AvailabilityZoneFixture, self).setUp()

        def fake_get_availability_zones(
                ctxt, hostapi, get_only_available=False,
                with_hosts=False, enabled_services=None):
            # A 2-item tuple is returned if get_only_available=False.
            if not get_only_available:
                return self.zones, []
            return self.zones
        self.useFixture(fixtures.MonkeyPatch(
            'nova.availability_zones.get_availability_zones',
            fake_get_availability_zones))

        def fake_get_instance_availability_zone(ctxt, instance):
            # If the server was created with a specific AZ, return it.
            reqspec = objects.RequestSpec.get_by_instance_uuid(
                ctxt, instance.uuid)
            requested_az = reqspec.availability_zone
            if requested_az:
                return requested_az
            # Otherwise return the instance.availability_zone if set else
            # the default AZ.
            return instance.availability_zone or CONF.default_availability_zone
        self.useFixture(fixtures.MonkeyPatch(
            'nova.availability_zones.get_instance_availability_zone',
            fake_get_instance_availability_zone))


class KSAFixture(fixtures.Fixture):
    """Lets us initialize an openstack.connection.Connection by stubbing the
    auth plugin.
    """
    def setUp(self):
        super(KSAFixture, self).setUp()
        self.mock_load_auth = self.useFixture(fixtures.MockPatch(
            'keystoneauth1.loading.load_auth_from_conf_options')).mock
        self.mock_load_sess = self.useFixture(fixtures.MockPatch(
            'keystoneauth1.loading.load_session_from_conf_options')).mock
        # For convenience, an attribute for the "Session" itself
        self.mock_session = self.mock_load_sess.return_value


class OpenStackSDKFixture(fixtures.Fixture):
    # This satisfies tests that happen to run through get_sdk_adapter but don't
    # care about the adapter itself (default mocks are fine).
    # TODO(efried): Get rid of this and use fixtures from openstacksdk once
    # https://storyboard.openstack.org/#!/story/2005475 is resolved.
    def setUp(self):
        super(OpenStackSDKFixture, self).setUp()
        self.useFixture(fixtures.MockPatch(
            'openstack.proxy.Proxy.get_endpoint'))
        real_make_proxy = service_description.ServiceDescription._make_proxy
        _stub_service_types = {'placement'}

        def fake_make_proxy(self, instance):
            if self.service_type in _stub_service_types:
                return instance.config.get_session_client(
                    self.service_type,
                    allow_version_hack=True,
                )
            return real_make_proxy(self, instance)
        self.useFixture(fixtures.MockPatchObject(
            service_description.ServiceDescription, '_make_proxy',
            fake_make_proxy))


class HostNameWeigher(weights.BaseHostWeigher):
    """Weigher to make the scheduler host selection deterministic.

    Note that this weigher is supposed to be used via
    HostNameWeigherFixture and will fail to instantiate if used without that
    fixture.
    """

    def __init__(self):
        self.weights = self.get_weights()

    def get_weights(self):
        raise NotImplemented()

    def _weigh_object(self, host_state, weight_properties):
        # Any unspecified host gets no weight.
        return self.weights.get(host_state.host, 0)


class HostNameWeigherFixture(fixtures.Fixture):
    """Fixture to make the scheduler host selection deterministic.

    Note that this fixture needs to be used before the scheduler service is
    started as it changes the scheduler configuration.
    """

    def __init__(self, weights=None):
        """Create the fixture
        :param weights: A dict of weights keyed by host names. Defaulted to
            {'host1': 100, 'host2': 50, 'host3': 10}"
        """
        if weights:
            self.weights = weights
        else:
            # default weights good for most of the functional tests
            self.weights = {'host1': 100, 'host2': 50, 'host3': 10}

    def setUp(self):
        super(HostNameWeigherFixture, self).setUp()
        # Make sure that when the scheduler instantiate the HostNameWeigher it
        # is initialized with the weights that is configured in this fixture
        self.useFixture(fixtures.MockPatchObject(
            HostNameWeigher, 'get_weights', return_value=self.weights))
        # Make sure that the scheduler loads the HostNameWeigher and only that
        self.useFixture(ConfPatcher(
            weight_classes=[__name__ + '.HostNameWeigher'],
            group='filter_scheduler'))
