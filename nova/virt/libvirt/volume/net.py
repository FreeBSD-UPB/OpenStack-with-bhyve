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

import nova.conf
from nova.virt.libvirt.volume import volume as libvirt_volume


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class LibvirtNetVolumeDriver(libvirt_volume.LibvirtBaseVolumeDriver):
    """Driver to attach Network volumes to libvirt."""
    def __init__(self, host):
        super(LibvirtNetVolumeDriver,
              self).__init__(host, is_block_dev=False)

    def _set_auth_config_rbd(self, conf, netdisk_properties):
        # The rbd volume driver in cinder sets auth_enabled if the rbd_user is
        # set in cinder. The rbd auth values from the cinder connection take
        # precedence over any local nova config values in case the cinder ceph
        # backend is configured differently than the nova rbd ephemeral storage
        # configuration.
        auth_enabled = netdisk_properties.get('auth_enabled')
        if auth_enabled:
            conf.auth_username = netdisk_properties['auth_username']
            # We started preferring Cinder config for rbd auth values starting
            # in Ocata, but if we have a guest connection from before that when
            # secret_uuid wasn't configured in Cinder, we need to fallback to
            # get it from local nova.conf.
            if netdisk_properties['secret_uuid'] is not None:
                conf.auth_secret_uuid = netdisk_properties['secret_uuid']
            else:
                # If we're using the rbd_secret_uuid from nova.conf we need to
                # use the rbd_user from nova.conf as well.
                LOG.debug('Falling back to Nova configuration for RBD auth '
                          'secret_uuid and username values.')
                conf.auth_username = CONF.libvirt.rbd_user
                conf.auth_secret_uuid = CONF.libvirt.rbd_secret_uuid
            # secret_type is always hard-coded to 'ceph' in cinder
            conf.auth_secret_type = netdisk_properties['secret_type']
        elif CONF.libvirt.rbd_secret_uuid:
            # Anyone relying on falling back to nova config is probably having
            # this work accidentally and we'll remove that support in the
            # future.
            # NOTE(mriedem): We'll have to be extra careful about this in case
            # the reason we got here is due to an old volume connection created
            # before we started preferring the Cinder settings in Ocata.
            LOG.warning('Falling back to Nova configuration values for '
                        'RBD authentication. Cinder should be configured '
                        'for auth with Ceph volumes. This fallback will '
                        'be dropped in a future release.')
            # use the nova config values
            conf.auth_username = CONF.libvirt.rbd_user
            conf.auth_secret_uuid = CONF.libvirt.rbd_secret_uuid
            # secret_type is always hard-coded to 'ceph' in cinder
            conf.auth_secret_type = netdisk_properties['secret_type']

    def get_config(self, connection_info, disk_info):
        """Returns xml for libvirt."""
        conf = super(LibvirtNetVolumeDriver,
                     self).get_config(connection_info, disk_info)

        netdisk_properties = connection_info['data']
        conf.source_type = "network"
        conf.source_protocol = connection_info['driver_volume_type']
        conf.source_name = netdisk_properties.get('name')
        conf.source_hosts = netdisk_properties.get('hosts', [])
        conf.source_ports = netdisk_properties.get('ports', [])
        if conf.source_protocol == 'rbd':
            self._set_auth_config_rbd(conf, netdisk_properties)
        return conf

    def extend_volume(self, connection_info, instance, requested_size):
        # There is nothing to do for network volumes. Cinder already extended
        # the volume and there is no local block device which needs to be
        # refreshed.
        return requested_size
