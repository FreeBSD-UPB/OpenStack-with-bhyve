# Copyright (c) 2019 Intel Corporation.
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

import copy
import itertools

from neutron_lib import constants
from neutron_lib.db import utils as db_utils
from neutron_lib import exceptions as n_exc
from oslo_versionedobjects import fields as obj_fields
from six.moves import range as six_range
from sqlalchemy import and_
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import sql

from neutron._i18n import _
from neutron.common import _constants as common_constants
from neutron.db.models import network_segment_range as range_model
from neutron.db.models.plugins.ml2 import geneveallocation as \
    geneve_alloc_model
from neutron.db.models.plugins.ml2 import gre_allocation_endpoints as \
    gre_alloc_model
from neutron.db.models.plugins.ml2 import vlanallocation as vlan_alloc_model
from neutron.db.models.plugins.ml2 import vxlanallocation as vxlan_alloc_model
from neutron.db.models import segment as segments_model
from neutron.db import models_v2
from neutron.objects import base
from neutron.objects import common_types


models_map = {
    constants.TYPE_VLAN: vlan_alloc_model.VlanAllocation,
    constants.TYPE_VXLAN: vxlan_alloc_model.VxlanAllocation,
    constants.TYPE_GRE: gre_alloc_model.GreAllocation,
    constants.TYPE_GENEVE: geneve_alloc_model.GeneveAllocation
}


@base.NeutronObjectRegistry.register
class NetworkSegmentRange(base.NeutronDbObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    db_model = range_model.NetworkSegmentRange

    primary_keys = ['id']

    fields = {
        'id': common_types.UUIDField(),
        'name': obj_fields.StringField(nullable=True),
        'default': obj_fields.BooleanField(nullable=False),
        'shared': obj_fields.BooleanField(nullable=False),
        'project_id': obj_fields.StringField(nullable=True),
        'network_type': common_types.NetworkSegmentRangeNetworkTypeEnumField(
            nullable=False),
        'physical_network': obj_fields.StringField(nullable=True),
        'minimum': obj_fields.IntegerField(nullable=True),
        'maximum': obj_fields.IntegerField(nullable=True)
    }

    def to_dict(self, fields=None):
        _dict = super(NetworkSegmentRange, self).to_dict()
        # extend the network segment range dict with `available` and `used`
        # fields
        _dict.update({'available': self._get_available_allocation()})
        _dict.update({'used': self._get_used_allocation_mapping()})
        # TODO(kailun): For tag mechanism. This will be removed in bug/1704137
        try:
            _dict['tags'] = [t.tag for t in self.db_obj.standard_attr.tags]
        except AttributeError:
            # AttrtibuteError can be raised when accessing self.db_obj
            # or self.db_obj.standard_attr
            pass
        # NOTE(ralonsoh): this workaround should be removed once the migration
        # from "tenant_id" to "project_id" is finished.
        _dict = db_utils.resource_fields(_dict, fields)
        _dict.pop('tenant_id', None)
        return _dict

    def _check_shared_project_id(self, action):
        if self.shared is False and not self.project_id:
            raise n_exc.ObjectActionError(
                action=action,
                reason='if NetworkSegmentRange is not shared, it must have a '
                       'project_id')

    def create(self):
        self._check_shared_project_id('create')
        super(NetworkSegmentRange, self).create()

    def update(self):
        self._check_shared_project_id('update')
        super(NetworkSegmentRange, self).update()

    def _get_allocation_model_details(self):
        model = models_map.get(self.network_type)
        if model is not None:
            alloc_segmentation_id = model.get_segmentation_id()
        else:
            msg = (_("network_type '%s' unknown for getting allocation "
                     "information") % self.network_type)
            raise n_exc.InvalidInput(error_message=msg)
        allocated = model.allocated

        return model, alloc_segmentation_id, allocated

    def _get_available_allocation(self):
        with self.db_context_reader(self.obj_context):
            model, alloc_segmentation_id, allocated = (
                self._get_allocation_model_details())

            query = self.obj_context.session.query(alloc_segmentation_id)
            query = query.filter(and_(
                alloc_segmentation_id >= self.minimum,
                alloc_segmentation_id <= self.maximum),
                not_(allocated))
            if self.network_type == constants.TYPE_VLAN:
                alloc_available = query.filter(
                    model.physical_network == self.physical_network).all()
            else:
                alloc_available = query.all()

            return [segmentation_id for (segmentation_id,) in alloc_available]

    def _get_used_allocation_mapping(self):
        with self.db_context_reader(self.obj_context):
            query = self.obj_context.session.query(
                segments_model.NetworkSegment.segmentation_id,
                models_v2.Network.project_id)
            alloc_used = (query.filter(and_(
                segments_model.NetworkSegment.network_type ==
                self.network_type,
                segments_model.NetworkSegment.physical_network ==
                self.physical_network,
                segments_model.NetworkSegment.segmentation_id >= self.minimum,
                segments_model.NetworkSegment.segmentation_id <= self.maximum))
                .filter(
                    segments_model.NetworkSegment.network_id ==
                    models_v2.Network.id)).all()
        return {segmentation_id: project_id
                for segmentation_id, project_id in alloc_used}

    @classmethod
    def _build_query_segments(cls, context, model, network_type, **filters):
        columns = set(dict(model.__table__.columns))
        model_filters = dict((k, filters[k])
                             for k in columns & set(filters.keys()))
        query = (context.session.query(model)
                 .filter_by(allocated=False, **model_filters).distinct())
        _and = and_(
            cls.db_model.network_type == network_type,
            model.physical_network == cls.db_model.physical_network if
            network_type == constants.TYPE_VLAN else sql.expression.true())
        return query.join(range_model.NetworkSegmentRange, _and)

    @classmethod
    def get_segments_for_project(cls, context, model, network_type,
                                 model_segmentation_id, **filters):
        _filters = copy.deepcopy(filters)
        project_id = _filters.pop('project_id', None)
        if not project_id:
            return []

        with cls.db_context_reader(context):
            query = cls._build_query_segments(context, model, network_type,
                                              **_filters)
            query = query.filter(and_(
                model_segmentation_id >= cls.db_model.minimum,
                model_segmentation_id <= cls.db_model.maximum,
                cls.db_model.project_id == project_id))
            return query.limit(common_constants.IDPOOL_SELECT_SIZE).all()

    @classmethod
    def get_segments_shared(cls, context, model, network_type,
                            model_segmentation_id, **filters):
        _filters = copy.deepcopy(filters)
        project_id = _filters.pop('project_id', None)
        with cls.db_context_reader(context):
            # Retrieve all network segment ranges shared.
            shared_ranges = context.session.query(cls.db_model).filter(
                and_(cls.db_model.network_type == network_type,
                     cls.db_model.shared == sql.expression.true()))
            if network_type == constants.TYPE_VLAN:
                shared_ranges.filter(cls.db_model.physical_network ==
                                     _filters['physical_network'])
            segment_ids = set([])
            for shared_range in shared_ranges.all():
                segment_ids.update(set(six_range(shared_range.minimum,
                                                 shared_range.maximum + 1)))
            if not segment_ids:
                return []

            # Retrieve other project segment ID ranges (not own project, not
            # default range).
            other_project_ranges = context.session.query(cls.db_model).filter(
                and_(cls.db_model.project_id != project_id,
                     cls.db_model.project_id.isnot(None),
                     cls.db_model.network_type == network_type))
            if network_type == constants.TYPE_VLAN:
                other_project_ranges = other_project_ranges.filter(
                    cls.db_model.physical_network ==
                    _filters['physical_network'])

            for other_project_range in other_project_ranges.all():
                _set = set(six_range(other_project_range.minimum,
                                     other_project_range.maximum + 1))
                segment_ids.difference_update(_set)

            # NOTE(ralonsoh): https://stackoverflow.com/questions/4628333/
            # converting-a-list-of-integers-into-range-in-python
            segment_ranges = [
                [t[0][1], t[-1][1]] for t in
                (tuple(g[1]) for g in itertools.groupby(
                    enumerate(segment_ids),
                    key=lambda enum_seg: enum_seg[1] - enum_seg[0]))]

            # Retrieve all segments belonging to the default range except those
            # assigned to other projects.
            query = cls._build_query_segments(context, model, network_type,
                                              **_filters)
            clauses = [and_(model_segmentation_id >= _range[0],
                            model_segmentation_id <= _range[1])
                       for _range in segment_ranges]
            query = query.filter(or_(*clauses))
            return query.limit(common_constants.IDPOOL_SELECT_SIZE).all()
