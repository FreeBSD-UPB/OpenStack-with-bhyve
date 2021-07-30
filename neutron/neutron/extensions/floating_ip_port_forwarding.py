# Copyright (c) 2018 OpenStack Foundation
# All rights reserved.
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

import abc
import itertools

from neutron_lib.api.definitions import floating_ip_port_forwarding as apidef
from neutron_lib.api import extensions as api_extensions
from neutron_lib.plugins import constants as plugin_consts
from neutron_lib.plugins import directory
from neutron_lib.services import base as service_base
import six

from neutron.api import extensions
from neutron.api.v2 import base
from neutron.api.v2 import resource_helper


class Floating_ip_port_forwarding(api_extensions.APIExtensionDescriptor):
    """Floating IP Port Forwarding API extension."""

    api_definition = apidef

    @classmethod
    def get_plugin_interface(cls):
        return PortForwardingPluginBase

    @classmethod
    def get_resources(cls):
        """Returns Ext Resources."""
        special_mappings = {'floatingips': 'floatingip'}
        plural_mappings = resource_helper.build_plural_mappings(
            special_mappings, itertools.chain(
                apidef.RESOURCE_ATTRIBUTE_MAP,
                apidef.SUB_RESOURCE_ATTRIBUTE_MAP))

        resources = resource_helper.build_resource_info(
                plural_mappings,
                apidef.RESOURCE_ATTRIBUTE_MAP,
                plugin_consts.PORTFORWARDING,
                translate_name=True,
                allow_bulk=True)

        plugin = directory.get_plugin(plugin_consts.PORTFORWARDING)

        parent = apidef.SUB_RESOURCE_ATTRIBUTE_MAP[
            apidef.COLLECTION_NAME].get('parent')
        params = apidef.SUB_RESOURCE_ATTRIBUTE_MAP[apidef.COLLECTION_NAME].get(
            'parameters')

        controller = base.create_resource(apidef.COLLECTION_NAME,
                                          apidef.RESOURCE_NAME,
                                          plugin, params,
                                          allow_bulk=True,
                                          parent=parent,
                                          allow_pagination=True,
                                          allow_sorting=True)

        resource = extensions.ResourceExtension(
            apidef.COLLECTION_NAME,
            controller, parent,
            attr_map=params)
        resources.append(resource)

        return resources


@six.add_metaclass(abc.ABCMeta)
class PortForwardingPluginBase(service_base.ServicePluginBase):

    path_prefix = apidef.API_PREFIX

    @classmethod
    def get_plugin_type(cls):
        return plugin_consts.PORTFORWARDING

    def get_plugin_description(self):
        return "Port Forwarding Service Plugin"

    @abc.abstractmethod
    def create_floatingip_port_forwarding(self, context, floatingip_id,
                                          port_forwarding):
        pass

    @abc.abstractmethod
    def update_floatingip_port_forwarding(self, context, id, floatingip_id,
                                          port_forwarding):
        pass

    @abc.abstractmethod
    def get_floatingip_port_forwarding(self, context, id, floatingip_id,
                                       fields=None):
        pass

    @abc.abstractmethod
    def get_floatingip_port_forwardings(self, context, floatingip_id=None,
                                        filters=None, fields=None, sorts=None,
                                        limit=None, marker=None,
                                        page_reverse=False):
        pass

    @abc.abstractmethod
    def delete_floatingip_port_forwarding(self, context, id, floatingip_id):
        pass
