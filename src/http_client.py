from galaxy.http import HttpClient

from consts import USER_AGENT

import aiohttp
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
        self.user = None
        self._cookie_jar = CookieJar()
        self._auth_lost_callback = None
        super().__init__(cookie_jar=self._cookie_jar)

    def get_credentials(self):
        creds = self.user
        creds['cookie_jar'] = pickle.dumps([cookie for cookie in self._cookie_jar]).hex()
        return creds

    def set_cookies_updated_callback(self, callback):
        self._cookie_jar.set_cookies_updated_callback(callback)

    def update_cookies(self, cookies):
        self._cookie_jar.update_cookies(cookies)

    def set_auth_lost_callback(self, callback):
        self._auth_lost_callback = callback

    def is_authenticated(self):
        return self.user is not None and self._auth_lost_callback is None

    # Side Note: The following method is meant to ensure that the access (bearer) token continues to remain relevant.
    async def do_request(self, method, url, *args, **kwargs):
        try:
            return await self.request(method, *args, **kwargs)
        except Exception as e:
            log.warning(f"WARNING: The request failed with exception {repr(e)}. Attempting to refresh credentials...")
            self.set_auth_lost_callback(True)
            await self.authenticate()
            return await self.request(method, *args, **kwargs)

    async def get_json_from_request_strict(self, url):
        headers = {
            "Authorization": f"Bearer {self.bearer}",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": USER_AGENT
        }
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

    async def refresh_credentials(self):
        try:
            await self.request("GET", "https://socialclub.rockstargames.com")
            new_bearer = await self.get_bearer_from_cookie_jar()
            return new_bearer
        except Exception as e:
            log.error("ERROR: The request to refresh credentials resulted in this exception: " + repr(e))
            raise

    async def authenticate(self):
        if self._auth_lost_callback:
            # We need to refresh the credentials.
            self.bearer = await self.refresh_credentials()
            self._auth_lost_callback = None
        else:
            self.bearer = await self.get_bearer_from_cookie_jar()
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
