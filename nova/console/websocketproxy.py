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

'''
Websocket proxy that is compatible with OpenStack Nova.
Leverages websockify.py by Joel Martin
'''

import copy
import socket
import sys

from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import importutils
import six
from six.moves import http_cookies as Cookie
import six.moves.urllib.parse as urlparse
import websockify

from nova.compute import rpcapi as compute_rpcapi
import nova.conf
from nova import context
from nova import exception
from nova.i18n import _
from nova import objects

# Location of WebSockifyServer class in websockify v0.9.0
websockifyserver = importutils.try_import('websockify.websockifyserver')

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class TenantSock(object):
    """A socket wrapper for communicating with the tenant.

    This class provides a socket-like interface to the internal
    websockify send/receive queue for the client connection to
    the tenant user. It is used with the security proxy classes.
    """

    def __init__(self, reqhandler):
        self.reqhandler = reqhandler
        self.queue = []

    def recv(self, cnt):
        # NB(sross): it's ok to block here because we know
        #            exactly the sequence of data arriving
        while len(self.queue) < cnt:
            # new_frames looks like ['abc', 'def']
            new_frames, closed = self.reqhandler.recv_frames()
            # flatten frames onto queue
            for frame in new_frames:
                # The socket returns (byte) strings in Python 2...
                if six.PY2:
                    self.queue.extend(frame)
                # ...and integers in Python 3. For the Python 3 case, we need
                # to convert these to characters using 'chr' and then, as this
                # returns unicode, convert the result to byte strings.
                else:
                    self.queue.extend(
                        [six.binary_type(chr(c), 'ascii') for c in frame])

            if closed:
                break

        popped = self.queue[0:cnt]
        del self.queue[0:cnt]
        return b''.join(popped)

    def sendall(self, data):
        self.reqhandler.send_frames([encodeutils.safe_encode(data)])

    def finish_up(self):
        self.reqhandler.send_frames([b''.join(self.queue)])

    def close(self):
        self.finish_up()
        self.reqhandler.send_close()


class NovaProxyRequestHandlerBase(object):
    def address_string(self):
        # NOTE(rpodolyaka): override the superclass implementation here and
        # explicitly disable the reverse DNS lookup, which might fail on some
        # deployments due to DNS configuration and break VNC access completely
        return str(self.client_address[0])

    def verify_origin_proto(self, connect_info, origin_proto):
        if 'access_url_base' not in connect_info:
            detail = _("No access_url_base in connect_info. "
                       "Cannot validate protocol")
            raise exception.ValidationError(detail=detail)

        expected_protos = [
            urlparse.urlparse(connect_info.access_url_base).scheme]
        # NOTE: For serial consoles the expected protocol could be ws or
        # wss which correspond to http and https respectively in terms of
        # security.
        if 'ws' in expected_protos:
            expected_protos.append('http')
        if 'wss' in expected_protos:
            expected_protos.append('https')

        return origin_proto in expected_protos

    def _check_console_port(self, ctxt, instance_uuid, port, console_type):

        try:
            instance = objects.Instance.get_by_uuid(ctxt, instance_uuid)
        except exception.InstanceNotFound:
            return

        # NOTE(melwitt): The port is expected to be a str for validation.
        return self.compute_rpcapi.validate_console_port(ctxt, instance,
                                                         str(port),
                                                         console_type)

    def _get_connect_info(self, ctxt, token):
        """Validate the token and get the connect info."""
        # NOTE(PaulMurray) ConsoleAuthToken.validate validates the token.
        # We call the compute manager directly to check the console port
        # is correct.
        connect_info = objects.ConsoleAuthToken.validate(ctxt, token)

        valid_port = self._check_console_port(
            ctxt, connect_info.instance_uuid, connect_info.port,
            connect_info.console_type)

        if not valid_port:
            raise exception.InvalidToken(token='***')

        return connect_info

    def new_websocket_client(self):
        """Called after a new WebSocket connection has been established."""
        # Reopen the eventlet hub to make sure we don't share an epoll
        # fd with parent and/or siblings, which would be bad
        from eventlet import hubs
        hubs.use_hub()

        # The nova expected behavior is to have token
        # passed to the method GET of the request
        parse = urlparse.urlparse(self.path)
        if parse.scheme not in ('http', 'https'):
            # From a bug in urlparse in Python < 2.7.4 we cannot support
            # special schemes (cf: http://bugs.python.org/issue9374)
            if sys.version_info < (2, 7, 4):
                raise exception.NovaException(
                    _("We do not support scheme '%s' under Python < 2.7.4, "
                      "please use http or https") % parse.scheme)

        query = parse.query
        token = urlparse.parse_qs(query).get("token", [""]).pop()
        if not token:
            # NoVNC uses it's own convention that forward token
            # from the request to a cookie header, we should check
            # also for this behavior
            hcookie = self.headers.get('cookie')
            if hcookie:
                cookie = Cookie.SimpleCookie()
                for hcookie_part in hcookie.split(';'):
                    hcookie_part = hcookie_part.lstrip()
                    try:
                        cookie.load(hcookie_part)
                    except Cookie.CookieError:
                        # NOTE(stgleb): Do not print out cookie content
                        # for security reasons.
                        LOG.warning('Found malformed cookie')
                    else:
                        if 'token' in cookie:
                            token = cookie['token'].value

        ctxt = context.get_admin_context()
        connect_info = self._get_connect_info(ctxt, token)

        # Verify Origin
        expected_origin_hostname = self.headers.get('Host')
        if ':' in expected_origin_hostname:
            e = expected_origin_hostname
            if '[' in e and ']' in e:
                expected_origin_hostname = e.split(']')[0][1:]
            else:
                expected_origin_hostname = e.split(':')[0]
        expected_origin_hostnames = CONF.console.allowed_origins
        expected_origin_hostnames.append(expected_origin_hostname)
        origin_url = self.headers.get('Origin')
        # missing origin header indicates non-browser client which is OK
        if origin_url is not None:
            origin = urlparse.urlparse(origin_url)
            origin_hostname = origin.hostname
            origin_scheme = origin.scheme
            # If the console connection was forwarded by a proxy (example:
            # haproxy), the original protocol could be contained in the
            # X-Forwarded-Proto header instead of the Origin header. Prefer the
            # forwarded protocol if it is present.
            forwarded_proto = self.headers.get('X-Forwarded-Proto')
            if forwarded_proto is not None:
                origin_scheme = forwarded_proto
            if origin_hostname == '' or origin_scheme == '':
                detail = _("Origin header not valid.")
                raise exception.ValidationError(detail=detail)
            if origin_hostname not in expected_origin_hostnames:
                detail = _("Origin header does not match this host.")
                raise exception.ValidationError(detail=detail)
            if not self.verify_origin_proto(connect_info, origin_scheme):
                detail = _("Origin header protocol does not match this host.")
                raise exception.ValidationError(detail=detail)

        sanitized_info = copy.copy(connect_info)
        sanitized_info.token = '***'
        self.msg(_('connect info: %s'), sanitized_info)

        host = connect_info.host
        port = connect_info.port

        # Connect to the target
        self.msg(_("connecting to: %(host)s:%(port)s") % {'host': host,
                                                          'port': port})
        tsock = self.socket(host, port, connect=True)

        # Handshake as necessary
        if 'internal_access_path' in connect_info:
            path = connect_info.internal_access_path
            if path:
                tsock.send(encodeutils.safe_encode(
                    'CONNECT %s HTTP/1.1\r\n\r\n' % path))
                end_token = "\r\n\r\n"
                while True:
                    data = tsock.recv(4096, socket.MSG_PEEK)
                    token_loc = data.find(end_token)
                    if token_loc != -1:
                        if data.split("\r\n")[0].find("200") == -1:
                            raise exception.InvalidConnectionInfo()
                        # remove the response from recv buffer
                        tsock.recv(token_loc + len(end_token))
                        break

        if self.server.security_proxy is not None:
            tenant_sock = TenantSock(self)

            try:
                tsock = self.server.security_proxy.connect(tenant_sock, tsock)
            except exception.SecurityProxyNegotiationFailed:
                LOG.exception("Unable to perform security proxying, shutting "
                              "down connection")
                tenant_sock.close()
                tsock.shutdown(socket.SHUT_RDWR)
                tsock.close()
                raise

            tenant_sock.finish_up()

        # Start proxying
        try:
            self.do_proxy(tsock)
        except Exception:
            if tsock:
                tsock.shutdown(socket.SHUT_RDWR)
                tsock.close()
                self.vmsg(_("%(host)s:%(port)s: "
                          "Websocket client or target closed") %
                          {'host': host, 'port': port})
            raise


class NovaProxyRequestHandler(NovaProxyRequestHandlerBase,
                              websockify.ProxyRequestHandler):
    def __init__(self, *args, **kwargs):
        self._compute_rpcapi = None
        websockify.ProxyRequestHandler.__init__(self, *args, **kwargs)

    @property
    def compute_rpcapi(self):
        # Lazy load the rpcapi/ComputeAPI upon first use for this connection.
        # This way, if we receive a TCP RST, we will not create a ComputeAPI
        # object we won't use.
        if not self._compute_rpcapi:
            self._compute_rpcapi = compute_rpcapi.ComputeAPI()
        return self._compute_rpcapi

    def socket(self, *args, **kwargs):
        # TODO(melwitt): The try_import and if-else condition can be removed
        # when we get to the point where we're requiring at least websockify
        # v.0.9.0 in our lower-constraints.
        if websockifyserver is not None:
            # In websockify v0.9.0, the 'socket' method moved to the
            # websockify.websockifyserver.WebSockifyServer class.
            return websockifyserver.WebSockifyServer.socket(*args, **kwargs)
        else:
            # Fall back to the websockify <= v0.8.0 'socket' method location.
            return websockify.WebSocketServer.socket(*args, **kwargs)


class NovaWebSocketProxy(websockify.WebSocketProxy):
    def __init__(self, *args, **kwargs):
        """:param security_proxy: instance of
            nova.console.securityproxy.base.SecurityProxy

        Create a new web socket proxy, optionally using the
        @security_proxy instance to negotiate security layer
        with the compute node.
        """
        self.security_proxy = kwargs.pop('security_proxy', None)
        super(NovaWebSocketProxy, self).__init__(*args, **kwargs)

    @staticmethod
    def get_logger():
        return LOG
