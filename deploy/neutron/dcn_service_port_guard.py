"""Candidate Neutron guard for plugin-internal service-port mutations.

Not enabled by packaging. Release integration and full acceptance are required.
"""
import uuid

from neutron_lib import exceptions
from neutron_lib.callbacks import events, registry, resources
from neutron_lib.plugins import directory
from neutron_lib.services import base
from oslo_config import cfg


class ManagedPortForbidden(exceptions.NotAuthorized):
    message = 'Provider-managed service ports cannot be changed by project users.'


class ServicePortGuard(base.ServicePluginBase):
    """Enforce the network boundary below the port HTTP controller."""

    supported_extension_aliases = []

    def __init__(self, network_ids=None):
        if network_ids is None:
            cfg.CONF.register_opt(cfg.ListOpt('network_ids', default=[]),
                                  group='dcn_service_ports')
            network_ids = cfg.CONF.dcn_service_ports.network_ids
        if (not network_ids or len(set(network_ids)) != len(network_ids)
                or any(str(uuid.UUID(v)) != v for v in network_ids)):
            raise ValueError('Explicit canonical protected network UUIDs required')
        self.network_ids = frozenset(network_ids)
        for event in (events.BEFORE_CREATE, events.BEFORE_UPDATE,
                      events.BEFORE_DELETE):
            registry.subscribe(self._enforce, resources.PORT, event)

    def get_plugin_type(self):
        return 'DCN_SERVICE_PORT_GUARD'

    def get_plugin_description(self):
        return 'Provider-managed service-port mutation boundary'

    def _enforce(self, resource, event, trigger, payload=None):
        if payload is None:
            raise ManagedPortForbidden()
        context = payload.context
        # The original API policy remains in force. This callback only denies;
        # it does not authorize a request otherwise rejected by the API.
        if context.is_admin or 'service' in context.roles:
            return
        if event == events.BEFORE_CREATE:
            port = payload.states[0]
        elif event == events.BEFORE_UPDATE:
            port = payload.states[0]  # immutable original, not user patch
            changes = payload.states[1]
            # Allow rollback code to restore values already unchanged by our
            # rejected operation. This does not authorize a real mutation.
            if all(port.get(key) == value for key, value in changes.items()):
                return
        else:
            port = payload.metadata.get('port')
            if port is None:
                port = directory.get_plugin().get_port(
                    context.elevated(), payload.resource_id)
        if port['network_id'] in self.network_ids:
            raise ManagedPortForbidden()
