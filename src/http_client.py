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
        super().__init__(cookie_jar=self._cookie_jar)

    def get_credentials(self):
        creds = self.user
        creds['cookie_jar'] = pickle.dumps(self._current_session.cookies).hex()
        return creds

    def set_cookies_updated_callback(self, callback):
        self._cookie_jar.set_cookies_updated_callback(callback)

    def update_cookie(self, cookie_name, cookie_value):
        log.debug("Made It")
        self._current_session.cookies[cookie_name] = cookie_value

    def set_auth_lost_callback(self, callback):
        self._auth_lost_callback = callback

    def is_authenticated(self):
        return self.user is not None and self._auth_lost_callback is None

    def create_session(self, stored_credentials):
        if self._current_session is None:
            self._current_session = requests.Session()
            if stored_credentials is not None:
                self._current_session.cookies = pickle.loads(bytes.fromhex(stored_credentials['cookie_jar']))
            self._current_session.max_redirects = 300

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
            s.trust_env = False
            resp = s.get(url, headers=headers)
            return resp.json()
        except Exception as e:
            log.warning(f"WARNING: The request failed with exception {repr(e)}. Attempting to refresh credentials...")
            self.set_auth_lost_callback(True)
            await self.authenticate()
            return self.get_json_from_request_strict(url)

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

    def _create_fingerprint(self):
        # Just ignore this for now. There is no way we could fake the fingerprint with Requests.
        language = self._cookie_jar.__iter__()
        for morsel in self._cookie_jar.__iter__():
            if str(morsel.key) == "Culture":
                language = morsel.value
                break
        return ('{"fp":{"user_agent":"30f28f56d63e0c977e9967a4c18366f0","language":"' + language + '",'
                '"pixel_ratio":1.2395833730697632,"timezone_offset":' + str(self._utc_offset) + ',"session_storage":1,'
                '"local_storage":1,"indexed_db":1,"open_database":1,"cpu_class":"unknown","navigator_platform":'
                '"Win32","do_not_track":"1", "regular_plugins":"","canvas":"6ffefc940a1bc9b162bee2a51875f65b",'
                '"webgl":"37db41470e8329a2a047bc971c8595e9","adblock":false,"has_lied_os":false,'
                '"touch_support":"0;false;false","device_name":"Chrome on Windows",'
                '"js_fonts":"a7627c8c66c03d6782fb6f14c370514d"}}')

    async def _get_user_json(self, message=None):
        try:
            headers = {
                "cookie": await self.get_cookies_for_headers(),
                "referer": "https://www.rockstargames.com",
                "user-agent": USER_AGENT
            }
            resp = self._current_session.get(r"https://www.rockstargames.com/auth/get-user.json", headers=headers)
            # for key, value in self._current_session.cookies.get_dict().items():
            # self._cookie_jar.update_cookies({key: value})
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
        log.debug("ROCKSTAR_COOKIES: " + await self.get_cookies_for_headers())
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

        # NOTE: This implementation probably is not working correctly, since Requests does not support JavaScript.
        # The only implementation that I can think of would be to use Selenium and a headless browser, but that would
        # require the user to constantly update their browser driver as their browser gets updated.
        # Either that, or we do what was done with the Battle.net integration and fake the authentication after the
        # token expires (although that would almost certainly break features or lead to outdated cached information).
        working_dict = self._current_session.cookies.get_dict()
        old_auth_token = working_dict['ScAuthTokenData']
        log.debug("ROCKSTAR_OLD_AUTH: " + str(old_auth_token))
        headers = {
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,"
                       "application/signed-exchange;v=b3"),
            "Cookie": await self.get_cookies_for_headers(),
            "User-Agent": USER_AGENT
        }
        self._current_session.get("https://www.rockstargames.com", headers=headers)

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
