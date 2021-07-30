# Copyright (c) 2012 OpenStack Foundation
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

from oslo_log import log as logging

from nova.scheduler import filters

LOG = logging.getLogger(__name__)


class RetryFilter(filters.BaseHostFilter):
    """Filter out nodes that have already been attempted for scheduling
    purposes
    """

    # NOTE(danms): This does not affect _where_ an instance lands, so not
    # related to rebuild.
    RUN_ON_REBUILD = False

    def __init__(self):
        super(RetryFilter, self).__init__()
        LOG.warning('The RetryFilter is deprecated since the 20.0.0 Train '
                    'release. Since the 17.0.0 (Queens) release, the '
                    'scheduler has provided alternate hosts for rescheduling '
                    'so the scheduler does not need to be called during a '
                    'reschedule which makes the RetryFilter useless.')

    def host_passes(self, host_state, spec_obj):
        """Skip nodes that have already been attempted."""
        retry = spec_obj.retry
        if not retry:
            return True

        # TODO(sbauza): Once the HostState is actually a ComputeNode, we could
        # easily get this one...
        host = [host_state.host, host_state.nodename]
        # TODO(sbauza)... and we wouldn't need to primitive the hosts into
        # lists
        hosts = [[cn.host, cn.hypervisor_hostname] for cn in retry.hosts]

        passes = host not in hosts

        if not passes:
            LOG.info("Host %(host)s fails.  Previously tried hosts: "
                     "%(hosts)s", {'host': host, 'hosts': hosts})

        # Host passes if it's not in the list of previously attempted hosts:
        return passes
