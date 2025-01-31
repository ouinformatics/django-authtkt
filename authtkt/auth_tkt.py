import datetime
from codecs import utf_8_decode
from codecs import utf_8_encode
import os
import time

from paste.request import get_cookies
from paste.auth import auth_tkt

_NOW_TESTING = None  # unit tests can replace
def _now():  #pragma NO COVERAGE
    if _NOW_TESTING is not None:
        return _NOW_TESTING
    return datetime.datetime.now()

class AuthTktCookiePlugin(object):

    userid_type_decoders = {
        'int':int,
        'unicode':lambda x: utf_8_decode(x)[0],
        }

    userid_type_encoders = {
        int: ('int', str),
        long: ('int', str),
        unicode: ('unicode', lambda x: utf_8_encode(x)[0]),
        }

    def __init__(self, secret, cookie_name='auth_tkt',
                 secure=False, include_ip=False,
                 timeout=None, reissue_time=None, userid_checker=None):
        self.secret = secret
        self.cookie_name = cookie_name
        self.include_ip = include_ip
        self.secure = secure
        if timeout and ( (not reissue_time) or (reissue_time > timeout) ):
            raise ValueError('When timeout is specified, reissue_time must '
                             'be set to a lower value')
        self.timeout = timeout
        self.reissue_time = reissue_time
        self.userid_checker = userid_checker

    # IIdentifier
    def identify(self, environ):
        cookies = get_cookies(environ)
        cookie = cookies.get(self.cookie_name)

        if cookie is None or not cookie.value:
            return None

        if self.include_ip:
            remote_addr = environ['REMOTE_ADDR']
        else:
            remote_addr = '0.0.0.0'

        try:
            timestamp, userid, tokens, user_data = auth_tkt.parse_ticket(
                self.secret, cookie.value, remote_addr)
        except auth_tkt.BadTicket:
            return None

        if self.timeout and ( (timestamp + self.timeout) < time.time() ):
            return None

        userid_typename = 'userid_type:'
        user_data_info = user_data.split('|')
        for datum in filter(None, user_data_info):
            if datum.startswith(userid_typename):
                userid_type = datum[len(userid_typename):]
                decoder = self.userid_type_decoders.get(userid_type)
                if decoder:
                    userid = decoder(userid)

        environ['REMOTE_USER_TOKENS'] = tokens
        environ['REMOTE_USER_DATA'] = user_data
        environ['AUTH_TYPE'] = 'cookie'

        identity = {}
        identity['timestamp'] = timestamp
        identity['repoze.who.plugins.auth_tkt.userid'] = userid
        identity['tokens'] = tokens
        identity['userdata'] = user_data
        return identity

    # IIdentifier
    def forget(self, environ, identity):
        # return a set of expires Set-Cookie headers
        return self._get_cookies(environ, 'INVALID', 0)

    # IIdentifier
    def remember(self, environ, identity):
        if self.include_ip:
            remote_addr = environ['REMOTE_ADDR']
        else:
            remote_addr = '0.0.0.0'

        cookies = get_cookies(environ)
        old_cookie = cookies.get(self.cookie_name)
        existing = cookies.get(self.cookie_name)
        old_cookie_value = getattr(existing, 'value', None)
        max_age = identity.get('max_age', None)

        timestamp, userid, tokens, userdata = None, '', (), ''

        if old_cookie_value:
            try:
                timestamp,userid,tokens,userdata = auth_tkt.parse_ticket(
                    self.secret, old_cookie_value, remote_addr)
            except auth_tkt.BadTicket:
                pass
        tokens = tuple(tokens)

        who_userid = identity['repoze.who.userid']
        who_tokens = tuple(identity.get('tokens', ()))
        who_userdata = identity.get('userdata', '')

        encoding_data = self.userid_type_encoders.get(type(who_userid))
        if encoding_data:
            encoding, encoder = encoding_data
            who_userid = encoder(who_userid)
            who_userdata = 'userid_type:%s' % encoding

        old_data = (userid, tokens, userdata)
        new_data = (who_userid, who_tokens, who_userdata)

        if old_data != new_data or (self.reissue_time and
                ( (timestamp + self.reissue_time) < time.time() )):
            ticket = auth_tkt.AuthTicket(
                self.secret,
                who_userid,
                remote_addr,
                tokens=who_tokens,
                user_data=who_userdata,
                cookie_name=self.cookie_name,
                secure=self.secure)
            new_cookie_value = ticket.cookie_value()

            cur_domain = environ.get('HTTP_HOST', environ.get('SERVER_NAME'))
            wild_domain = cur_domain[cur_domain.find('.'):]
            #wild_domain = '.' + cur_domain
            if old_cookie_value != new_cookie_value:
                # return a set of Set-Cookie headers
                return self._get_cookies(environ, new_cookie_value, max_age)

    # IAuthenticator
    def authenticate(self, environ, identity):
        userid = identity.get('repoze.who.plugins.auth_tkt.userid')
        if userid is None:
            return None
        if self.userid_checker and not self.userid_checker(userid):
            return None
        identity['repoze.who.userid'] = userid
        return userid

    def _get_cookies(self, environ, value, max_age=None):
        if max_age is not None:
            max_age = int(max_age)
            later = _now() + datetime.timedelta(seconds=max_age)
            # Wdy, DD-Mon-YY HH:MM:SS GMT
            expires = later.strftime('%a, %d %b %Y %H:%M:%S')
            # the Expires header is *required* at least for IE7 (IE7 does
            # not respect Max-Age)
            max_age = "; Max-Age=%s; Expires=%s" % (max_age, expires)
        else:
            max_age = ''

        secure = ''
        if self.secure:
            secure = '; secure; HttpOnly'

        cur_domain = environ.get('HTTP_HOST', environ.get('SERVER_NAME'))
        #wild_domain = '.' + cur_domain
        wild_domain = cur_domain[cur_domain.find('.'):]
        cookies = [
            ('Set-Cookie', '%s="%s"; Path=/%s%s' % (
            self.cookie_name, value, max_age, secure)),
            ('Set-Cookie', '%s="%s"; Path=/; Domain=%s%s%s' % (
            self.cookie_name, value, cur_domain, max_age, secure)),
            ('Set-Cookie', '%s="%s"; Path=/; Domain=%s%s%s' % (
            self.cookie_name, value, wild_domain, max_age, secure))
            ]
        return cookies

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__,
                            id(self)) #pragma NO COVERAGE

