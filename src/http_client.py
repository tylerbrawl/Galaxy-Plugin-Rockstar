from galaxy.http import HttpClient

from consts import USER_AGENT

import aiohttp
import dateutil.tz
import datetime
import logging as log
import pickle
import requests
import traceback
from yarl import URL


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


class AuthenticatedHttpClient(HttpClient):
    def __init__(self, store_credentials):
        self._store_credentials = store_credentials
        self.bearer = None
        self.refresh = None
        self.user = None
        local_time_zone = dateutil.tz.tzlocal()
        self._utc_offset = local_time_zone.utcoffset(datetime.datetime.now(local_time_zone)).total_seconds() / 60
        self._current_session = None
        self._cookie_jar = CookieJar()
        self._cookie_jar_ros = CookieJar()
        self._auth_lost_callback = None
        self._current_auth_token = None
        self._first_auth = True
        super().__init__(cookie_jar=self._cookie_jar)

    def get_credentials(self):
        creds = self.user
        # It might seem strange to store the entire session object in hexadecimal, rather than just the session's
        # cookies. However, keeping the session object intact is necessary in order to allow ScAuthTokenData to be
        # successfully authenticated. My guess is that the ScAuthTokenData uses some form of browser fingerprinting,
        # as using a value from Chrome on Firefox returned an error. Likewise, creating a new session object, rather
        # than reimplementing the old session object, returns an error when using a correct ScAuthTokenData value, even
        # if the two sessions have equivalent cookies.
        creds['session_object'] = pickle.dumps(self._current_session).hex()
        creds['current_auth_token'] = self._current_auth_token
        return creds

    def set_cookies_updated_callback(self, callback):
        self._cookie_jar.set_cookies_updated_callback(callback)

    def update_cookie(self, cookie):
        del self._current_session.cookies[cookie['name']]
        self._current_session.cookies.set(**cookie)

    def set_auth_lost_callback(self, callback):
        self._auth_lost_callback = callback

    def is_authenticated(self):
        return self.user is not None and self._auth_lost_callback is None

    def set_current_auth_token(self, token):
        self._current_auth_token = token

    def get_current_auth_token(self):
        return self._current_auth_token

    def get_named_cookie(self, cookie_name):
        return self._current_session.cookies[cookie_name]

    def create_session(self, stored_credentials):
        if stored_credentials is None:
            self._current_session = requests.Session()
            self._current_session.max_redirects = 300
        elif self._current_session is None:
            self._current_session = pickle.loads(bytes.fromhex(stored_credentials['session_object']))
            self._current_session.cookies.clear()

    # Side Note: The following method is meant to ensure that the access (bearer) token continues to remain relevant.
    async def do_request(self, method, *args, **kwargs):
        try:
            return await self.request(method, *args, **kwargs)
        except Exception as e:
            log.warning(f"WARNING: The request failed with exception {repr(e)}. Attempting to refresh credentials...")
            self.set_auth_lost_callback(True)
            await self.authenticate()
            return await self.request(method, *args, **kwargs)

    async def get_json_from_request_strict(self, url, include_default_headers=True, additional_headers=None):
        headers = additional_headers if additional_headers is not None else {}
        if include_default_headers:
            headers["Authorization"] = f"Bearer {self.bearer}"
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["User-Agent"] = USER_AGENT
        try:
            s = requests.Session()
            resp = s.get(url, headers=headers)
            return resp.json()
        except Exception as e:
            log.warning(f"WARNING: The request failed with exception {repr(e)}. Attempting to refresh credentials...")
            self.set_auth_lost_callback(True)
            await self.authenticate()
            return await self.get_json_from_request_strict(url, include_default_headers, additional_headers)

    async def get_bearer_from_cookie_jar(self):
        morsel_list = self._cookie_jar.__iter__()
        cookies = {}
        for morsel in morsel_list:
            cookies[morsel.key] = morsel.value
        log.debug(cookies)
        return cookies['BearerToken']

    async def get_cookies_for_headers(self):
        cookie_string = ""
        for key, value in self._current_session.cookies.get_dict().items():
            cookie_string += "" + str(key) + "=" + str(value) + ";"
            # log.debug("ROCKSTAR_CURR_COOKIE: " + cookie_string)
        return cookie_string[:len(cookie_string) - 1]

    async def _get_user_json(self, message=None):
        try:
            old_auth = self._current_session.cookies['ScAuthTokenData']
            log.debug("ROCKSTAR_OLD_AUTH: " + str(old_auth))
            headers = {
                "accept": "application/json, text/plain, */*",
                "connection": "keep-alive",
                "cookie": "ScAuthTokenData=" + self._current_auth_token,
                "host": "www.rockstargames.com",
                "referer": "https://www.rockstargames.com",
                "user-agent": USER_AGENT
            }
            resp = self._current_session.get(r"https://www.rockstargames.com/auth/get-user.json", headers=headers,
                                             allow_redirects=False, timeout=5)
            new_auth = self._current_session.cookies['ScAuthTokenData']
            log.debug("ROCKSTAR_NEW_AUTH: " + str(new_auth))
            self._current_auth_token = new_auth
            if new_auth != old_auth:
                log.warning("ROCKSTAR_AUTH_CHANGE: The ScAuthTokenData value has changed!")
                if self.user is not None:
                    self._store_credentials(self.get_credentials())
            return resp.json()
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
        # Perhaps the below idea is over-complicating things. What if we just connect to https://www.rockstargames.com
        # and let this request update the cookies? The below requests are made automatically by the normal browser.
        # Although they are not implemented, the below requests will be kept as documentation in case they are indeed
        # needed.

        # It seems like the Rockstar website connects to https://signin.rockstargames.com/connect/cors/check/rsg via a
        # POST request in order to re-authenticate the user. This request uses a fingerprint as form data.

        # This POST request then returns a message with a code, which is then sent as a request payload to
        # https://www.rockstargames.com/auth/login.json in the form or {code: "{code}"}. Note that {code} includes
        # its own set of quotation marks, so it looks like {code: ""{Numbers/Letters}""}.

        # Finally, this last request updates the cookies that are used for further authentication.

        # NOTE: This implementation is not working correctly, since Requests does not support JavaScript.
        # The only implementation that I can think of would be to use Selenium and a headless browser, but that would
        # require the user to constantly update their browser driver as their browser gets updated.
        # Either that, or we do what was done with the Battle.net integration and fake the authentication after the
        # token expires (although that would almost certainly break features or lead to outdated cached information).
        pass

    async def authenticate(self):
        if self._auth_lost_callback:
            # We need to refresh the credentials.
            await self.refresh_credentials()
            self._auth_lost_callback = None
        self.bearer = await self._get_bearer()
        log.debug("ROCKSTAR_HTTP_CHECK: Got bearer token: " + self.bearer)

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
            s = requests.Session()
            s.trust_env = False
            resp_user = s.get(url, headers=headers)
            resp_user_text = resp_user.json()
        except Exception as e:
            log.error(
                "ERROR: There was a problem with getting the user information with the token. Exception: " + repr(e))
            traceback.print_exc()
            raise
        log.debug(resp_user_text)
        working_dict = resp_user_text['accounts'][0]['rockstarAccount']  # The returned json is a nightmare.
        display_name = working_dict['displayName']
        rockstar_id = working_dict['rockstarId']
        log.debug("ROCKSTAR_HTTP_CHECK: Got display name: " + display_name + " / Got Rockstar ID: " + str(rockstar_id))
        self.user = {"display_name": display_name, "rockstar_id": rockstar_id}
        log.debug("ROCKSTAR_STORE_CREDENTIALS: Preparing to store credentials...")
        # log.debug(self.get_credentials()) - Reduce Console Spam (Enable this if you need to.)
        self._store_credentials(self.get_credentials())
        return self.user
