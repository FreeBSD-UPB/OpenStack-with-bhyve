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

from oslo_versionedobjects import fields as obj_fields

from neutron.db.extra_dhcp_opt import models
from neutron.objects import base
from neutron.objects import common_types


@base.NeutronObjectRegistry.register
class ExtraDhcpOpt(base.NeutronDbObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    db_model = models.ExtraDhcpOpt

    fields = {
         'id': common_types.UUIDField(),
         'port_id': common_types.UUIDField(),
         'opt_name': obj_fields.StringField(),
         'opt_value': obj_fields.StringField(),
         'ip_version': obj_fields.IntegerField(),
    }

    fields_no_update = ['port_id']

    foreign_keys = {
        'Port': {'port_id': 'id'},
    }
