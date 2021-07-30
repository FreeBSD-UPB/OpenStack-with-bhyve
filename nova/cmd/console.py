# Copyright (c) 2010 OpenStack Foundation
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

"""Starter script for Nova Console Proxy."""

import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts

from nova import config
from nova.console import rpcapi as console_rpcapi
from nova import objects
from nova import service
from nova import version

CONF = cfg.CONF
LOG = logging.getLogger('nova.console')


def main():
    config.parse_args(sys.argv)
    logging.setup(CONF, "nova")
    objects.register_all()
    gmr_opts.set_defaults(CONF)

    gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)

    LOG.warning('The nova-console service is deprecated as it is Xen '
                'specific, does not function properly in a multi-cell '
                'environment, and has effectively been replaced by noVNC '
                'and the nova-novncproxy service.')

    server = service.Service.create(binary='nova-console',
                                    topic=console_rpcapi.RPC_TOPIC)
    service.serve(server)
    service.wait()
