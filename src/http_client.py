from galaxy.http import create_client_session
from http.cookies import SimpleCookie

from consts import USER_AGENT, LOG_SENSITIVE_DATA

import aiohttp
import dataclasses
import dateutil.tz
import datetime
import logging as log
import pickle
import re
import traceback

from time import time
from yarl import URL


@dataclasses.dataclass
class Token(object):
    _token = None
    _expires = None

    def set_token(self, token, expiration):
        self._token, self._expires = token, expiration

    def get_token(self):
        return self._token

    def get_expiration(self):
        return self._expires

    @property
    def expired(self):
        return self._expires <= time()


class CookieJar(aiohttp.CookieJar):
    def __init__(self):
        super().__init__()
        self._cookies_updated_callback = None

    def set_cookies_updated_callback(self, callback):
        self._cookies_updated_callback = callback

    def update_cookies(self, cookies, url=URL()):
        super().update_cookies(cookies, url)
        if cookies and self._cookies_updated_callback:
            self._cookies_updated_callback(list(self))

    # aiohttp.CookieJar provides no method for deleting a specific cookie, so we need to create our own methods for
    # this. We also need to create our own method for getting a specific cookie.

    def remove_cookie(self, remove_name, domain="signin.rockstargames.com"):
        for key, morsel in self._cookies[domain].items():
            if remove_name == morsel.key:
                del self._cookies[domain][key]
                return
        log.debug("ROCKSTAR_REMOVE_COOKIE_ERROR: The cookie " + remove_name + " from domain " + domain +
                  " does not exist!")

    def remove_cookie_regex(self, remove_regex, domain="signin.rockstargames.com"):
        for key, morsel in self._cookies[domain].items():
            if re.search(remove_regex, morsel.key):
                del self._cookies[domain][key]
                return
        log.debug("ROCKSTAR_REMOVE_COOKIE_REGEX_ERROR: There is no cookie from domain " + domain + " that matches the "
                  "regular expression " + remove_regex + "!")

    def get(self, cookie_name, domain="signin.rockstargames.com"):
        for key, morsel in self._cookies[domain].items():
            if cookie_name == morsel.key:
                return self._cookies[domain][key].value
        log.debug("ROCKSTAR_GET_COOKIE_ERROR: The cookie " + cookie_name + " from domain " + domain +
                  " does not exist!")
        return ''


class BackendClient:
    def __init__(self, store_credentials):
        self._debug_always_refresh = False  # Set this to True if you are debugging ScAuthTokenData refreshing.
        self._store_credentials = store_credentials
        self.bearer = None
        # The refresh token here is the RMT cookie. The other refresh token is the rsso cookie. The RMT cookie is blank
        # for users not using two-factor authentication.
        self.refresh_token = Token()
        self._fingerprint = None
        self.user = None
        local_time_zone = dateutil.tz.tzlocal()
        self._utc_offset = local_time_zone.utcoffset(datetime.datetime.now(local_time_zone)).total_seconds() / 60
        self._current_session = None
        self._auth_lost_callback = None
        self._current_auth_token = None
        self._first_auth = True
        # super().__init__(cookie_jar=self._cookie_jar)

    async def close(self):
        await self._current_session.close()

    def get_credentials(self):
        creds = self.user
        # It might seem strange to store the entire session object in hexadecimal, rather than just the session's
        # cookies. However, keeping the session object intact is necessary in order to allow ScAuthTokenData to be
        # successfully authenticated. My guess is that the ScAuthTokenData uses some form of browser fingerprinting,
        # as using a value from Chrome on Firefox returned an error. Likewise, creating a new session object, rather
        # than reimplementing the old session object, returns an error when using a correct ScAuthTokenData value, even
        # if the two sessions have equivalent cookies.
        morsel_list = []
        for morsel in self._current_session.cookie_jar.__iter__():
            morsel_list.append(morsel)
        creds['cookie_jar'] = pickle.dumps(morsel_list).hex()
        creds['current_auth_token'] = self._current_auth_token
        creds['refresh_token'] = pickle.dumps(self.refresh_token).hex()
        creds['fingerprint'] = self._fingerprint
        return creds

    def set_cookies_updated_callback(self, callback):
        self._current_session.cookie_jar.set_cookies_updated_callback(callback)

    def update_cookie(self, cookie):
        # I believe that the cookie beginning with rsso gets a different name occasionally, so we need to delete the old
        # rsso cookie using regular expressions if we want to ensure that the refresh token can continue to be obtained.

        if re.search("^rsso", cookie['name']):
            self._current_session.cookie_jar.remove_cookie_regex("^rsso")
        cookie_object = SimpleCookie()
        cookie_object[cookie['name']] = cookie['value']
        cookie_object[cookie['name']]['domain'] = cookie['domain']
        cookie_object[cookie['name']]['path'] = cookie['path']
        self._current_session.cookie_jar.update_cookies(cookie_object)

    def set_auth_lost_callback(self, callback):
        self._auth_lost_callback = callback

    def is_authenticated(self):
        return self.user is not None and self._auth_lost_callback is None

    def set_current_auth_token(self, token):
        self._current_auth_token = token
        self._current_session.cookie_jar.update_cookies({'ScAuthTokenData': token})

    def get_current_auth_token(self):
        return self._current_auth_token

    def get_named_cookie(self, cookie_name):
        return self._current_session.cookies[cookie_name]

    def get_rockstar_id(self):
        return self.user["rockstar_id"]

    def set_refresh_token(self, token):
        expiration_time = time() + (3600 * 24 * 365 * 20)
        self.refresh_token.set_token(token, expiration_time)
        self._current_session.cookie_jar.update_cookies({"RMT": token})

    def set_refresh_token_absolute(self, token):
        self.refresh_token = token

    def get_refresh_token(self):
        if self.refresh_token.expired:
            log.debug("ROCKSTAR_REFRESH_EXPIRED: The refresh token has expired!")
            self.refresh_token.set_token(None, None)
        return self.refresh_token.get_token()

    def set_fingerprint(self, fingerprint):
        self._fingerprint = fingerprint

    def is_fingerprint_defined(self):
        return self._fingerprint is not None

    def create_session(self, stored_credentials):
        self._current_session = create_client_session(cookie_jar=CookieJar())
        self._current_session.max_redirects = 300
        if stored_credentials is not None:
            morsel_list = pickle.loads(bytes.fromhex(stored_credentials['cookie_jar']))
            for morsel in morsel_list:
                cookie_object = SimpleCookie()
                cookie_object[morsel.key] = morsel.value
                cookie_object[morsel.key]['domain'] = morsel['domain']
                cookie_object[morsel.key]['path'] = morsel['path']
                self._current_session.cookie_jar.update_cookies(cookie_object)

    async def get_json_from_request_strict(self, url, include_default_headers=True, additional_headers=None):
        headers = additional_headers if additional_headers is not None else {}
        if include_default_headers:
            headers["Authorization"] = f"Bearer {await self._get_bearer()}"
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["User-Agent"] = USER_AGENT
        try:
            resp = await self._current_session.get(url, headers=headers)
            return await resp.json()
        except Exception as e:
            log.exception(f"WARNING: The request failed with exception {repr(e)}. Attempting to refresh credentials...")
            self.set_auth_lost_callback(True)
            await self.authenticate()
            return await self.get_json_from_request_strict(url, include_default_headers, additional_headers)

    async def get_bearer_from_cookie_jar(self):
        morsel_list = self._current_session.cookie_jar.__iter__()
        cookies = {}
        for morsel in morsel_list:
            cookies[morsel.key] = morsel.value
        log.debug(cookies)
        return cookies['BearerToken']

    async def get_cookies_for_headers(self):
        cookie_string = ""
        for morsel in self._current_session.cookie_jar.__iter__():
            cookie_string += "" + str(morsel.key) + "=" + str(morsel.value) + ";"
            # log.debug("ROCKSTAR_CURR_COOKIE: " + cookie_string)
        return cookie_string[:len(cookie_string) - 1]

    async def _get_user_json(self, message=None):
        try:
            old_auth = self._current_auth_token
            if LOG_SENSITIVE_DATA:
                log.debug(f"ROCKSTAR_OLD_AUTH: {old_auth}")
            else:
                log.debug(f"ROCKSTAR_OLD_AUTH: {str(old_auth)[:5]}***{str(old_auth[-3:])}")
            headers = {
                "accept": "application/json, text/plain, */*",
                "connection": "keep-alive",
                "cookie": "ScAuthTokenData=" + old_auth,
                "host": "www.rockstargames.com",
                "referer": "https://www.rockstargames.com",
                "user-agent": USER_AGENT
            }
            resp = await self._current_session.get(r"https://www.rockstargames.com/auth/get-user.json", headers=headers,
                                                   allow_redirects=False)
            # aiohttp allows you to get a specified cookie from the previous response.
            filtered_cookies = resp.cookies
            if "ScAuthTokenData" in filtered_cookies:
                new_auth = filtered_cookies['ScAuthTokenData'].value
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_NEW_AUTH: {new_auth}")
                else:
                    log.debug(f"ROCKSTAR_NEW_AUTH: {str(new_auth)[:5]}***{str(new_auth[-3:])}")
                self._current_auth_token = new_auth
                if LOG_SENSITIVE_DATA:
                    log.warning("ROCKSTAR_AUTH_CHANGE: The ScAuthTokenData value has changed!")
                self._current_session.cookie_jar.update_cookies({'ScAuthTokenData': new_auth})
                if self.user is not None:
                    self._store_credentials(self.get_credentials())
            else:
                # For security purposes, the ScAuthTokenData value (whether hidden or not) is logged, regardless of
                # whether or not it has changed. If the logged outputs are similar between the two, it is harder to tell
                # if the value has really changed or not.
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_NEW_AUTH: {old_auth}")
                else:
                    log.debug(f"ROCKSTAR_NEW_AUTH: {str(old_auth)[:5]}***{str(old_auth)[-3:]}")
            return await resp.json()
        except Exception as e:
            if message is not None:
                log.error(message)
            else:
                log.error("ROCKSTAR_USER_JSON_ERROR: The request to get the get-user.json file resulted in this"
                          " exception: " + repr(e))
            traceback.print_exc()
            raise

    async def _get_bearer(self):
        try:
            resp_json = await self._get_user_json()
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_AUTH_JSON: " + str(resp_json))
            new_bearer = resp_json["user"]["auth_token"]["access_token"]
            self.bearer = new_bearer
            self.refresh = resp_json["user"]["auth_token"]["refresh_token"]
            return new_bearer
        except Exception as e:
            log.error("ERROR: The request to refresh credentials resulted in this exception: " + repr(e))
            raise

    async def get_played_games(self):
        try:
            resp_json = await self._get_user_json()
            return_list = []
            played_games = resp_json["user"]["games_played"]
            for game in played_games:
                if game["platform"] == "PC":
                    return_list.append(game["id"])
            return return_list
        except Exception as e:
            log.error("ROCKSTAR_PLAYED_GAMES_ERROR: The request to scrape the user's played games resulted in "
                      "this exception: " + repr(e))
            raise

    async def refresh_credentials(self):
        # It seems like the Rockstar website connects to https://signin.rockstargames.com/connect/cors/check/rsg via a
        # POST request in order to re-authenticate the user. This request uses a fingerprint as form data.

        # This POST request then returns a message with a code, which is then sent as a request payload to
        # https://www.rockstargames.com/auth/login.json in the form of {code: "{code}"}. Note that {code} includes
        # its own set of quotation marks, so it looks like {code: ""{Numbers/Letters}""}.

        # Finally, this last request updates the cookies that are used for further authentication.
        try:
            url = "https://signin.rockstargames.com/connect/cors/check/rsg"
            rsso_name = None
            rsso_value = None
            for morsel in self._current_session.cookie_jar.__iter__():
                if re.search("^rsso", morsel.key):
                    rsso_name = morsel.key
                    if LOG_SENSITIVE_DATA:
                        log.debug(f"ROCKSTAR_RSSO_NAME: {rsso_name}")
                    rsso_value = morsel.value
                    if LOG_SENSITIVE_DATA:
                        log.debug(f"ROCKSTAR_RSSO_VALUE: {rsso_value}")
                    break
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Cookie": "RMT=" + self.get_refresh_token() + "; " + rsso_name + "=" + rsso_value,
                "Content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Host": "signin.rockstargames.com",
                "Origin": "https://www.rockstargames.com",
                "User-Agent": USER_AGENT,
                "X-Requested-With": "XMLHttpRequest"
            }
            data = {"fingerprint": self._fingerprint}
            refresh_resp = await self._current_session.post(url, data=data, headers=headers)
            refresh_code = await refresh_resp.text()
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_REFRESH_CODE: Got code " + refresh_code + "!")
            # We need to set the new refresh token here, if it is updated.
            try:
                self.set_refresh_token(refresh_resp.cookies['RMT'].value)
                self._current_session.cookie_jar.update_cookies({'RMT': refresh_resp.cookies['RMT'].value})
            except KeyError:
                if LOG_SENSITIVE_DATA:
                    log.debug("ROCKSTAR_RMT_MISSING: The RMT cookie is missing, presumably because the user has not "
                              "enabled two-factor authentication. Proceeding anyways...")
                self.set_refresh_token('')
            old_auth = self._current_auth_token
            self._current_auth_token = None
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_OLD_AUTH_REFRESH: " + old_auth)
            else:
                log.debug(f"ROCKSTAR_OLD_AUTH_REFRESH: {old_auth[:5]}***{old_auth[-3:]}")
            url = "https://www.rockstargames.com/auth/login.json"
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Cookie": "TS019978c2=" + self._current_session.cookie_jar.get('TS019978c2',
                                                                               domain='support.rockstargames.com'),
                "Content-type": "application/json",
                "Host": "www.rockstargames.com",
                "Referer": "https://www.rockstargames.com/",
                "User-Agent": USER_AGENT
            }
            data = {"code": refresh_code}
            final_request = await self._current_session.post(url, json=data, headers=headers)
            final_json = await final_request.json()
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_REFRESH_JSON: " + str(final_json))
            filtered = final_request.cookies
            new_auth = filtered['ScAuthTokenData'].value
            self._current_session.cookie_jar.update_cookies({'ScAuthTokenData': new_auth})
            self._current_session.cookie_jar.update_cookies({'TS019978c2': filtered['TS019978c2'].value})
            self._current_auth_token = new_auth
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_NEW_AUTH_REFRESH: " + new_auth)
            else:
                log.debug(f"ROCKSTAR_NEW_AUTH_REFRESH: {new_auth[:5]}***{new_auth[-3:]}")
            if old_auth != new_auth:
                log.debug("ROCKSTAR_REFRESH_SUCCESS: The user has been successfully re-authenticated!")
        except Exception as e:
            log.debug("ROCKSTAR_REFRESH_FAILURE: The attempt to re-authenticate the user has failed with the exception "
                      + repr(e) + ". Logging the user out...")
            traceback.print_exc()
            raise

    async def authenticate(self):
        if self._auth_lost_callback or self._debug_always_refresh:
            # We need to refresh the credentials.
            await self.refresh_credentials()
            self._auth_lost_callback = None
        self.bearer = await self._get_bearer()
        if LOG_SENSITIVE_DATA:
            log.debug("ROCKSTAR_HTTP_CHECK: Got bearer token: " + self.bearer)
        else:
            log.debug(f"ROCKSTAR_HTTP_CHECK: Got bearer token: {self.bearer[:5]}***{self.bearer[-3:]}")

        # With the bearer token, we can now access the profile information.

        url = "https://scapi.rockstargames.com/profile/getbasicprofile"
        headers = {
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,"
                       "application/signed-exchange;application/json;v=b3"),
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US, en;q=0.9",
            "Authorization": f"Bearer {self.bearer}",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "dnt": "1",
            "Host": "scapi.rockstargames.com",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": USER_AGENT
        }
        try:
            resp_user = await self._current_session.get(url, headers=headers)
            resp_user_text = await resp_user.json()
        except Exception as e:
            log.error(
                "ERROR: There was a problem with getting the user information with the token. Exception: " + repr(e))
            traceback.print_exc()
            raise
        if LOG_SENSITIVE_DATA:
            log.debug(resp_user_text)
        working_dict = resp_user_text['accounts'][0]['rockstarAccount']  # The returned json is a nightmare.
        display_name = working_dict['displayName']
        rockstar_id = working_dict['rockstarId']
        if LOG_SENSITIVE_DATA:
            log.debug("ROCKSTAR_HTTP_CHECK: Got display name: " + display_name + " / Got Rockstar ID: " +
                      str(rockstar_id))
        else:
            log.debug(f"ROCKSTAR_HTTP_CHECK: Got display name: {display_name[:1]}*** / Got Rockstar ID: ***")
        self.user = {"display_name": display_name, "rockstar_id": rockstar_id}
        log.debug("ROCKSTAR_STORE_CREDENTIALS: Preparing to store credentials...")
        # log.debug(self.get_credentials()) - Reduce Console Spam (Enable this if you need to.)
        self._store_credentials(self.get_credentials())
        return self.user
