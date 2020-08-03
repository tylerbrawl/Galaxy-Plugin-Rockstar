from galaxy.http import create_client_session
from galaxy.api.errors import AuthenticationRequired, BackendError, InvalidCredentials, NetworkError
from galaxy.api.types import UserPresence
from galaxy.api.consts import PresenceState
from http.cookies import SimpleCookie

from consts import USER_AGENT, LOG_SENSITIVE_DATA, CONFIG_OPTIONS, get_time_passed, get_unix_epoch_time_from_date
from game_cache import get_game_title_id_from_google_tag_id, get_game_title_id_from_ugc_title_id, games_cache

import aiohttp
import asyncio
import dataclasses
import dateutil.tz
import datetime
import json
import logging as log
import pickle
import re
import urllib.parse

from html.parser import HTMLParser
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
        self._debug_always_refresh = CONFIG_OPTIONS['debug_always_refresh']
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
        self._current_sc_token = None
        self._first_auth = True
        self._refreshing = False
        # super().__init__(cookie_jar=self._cookie_jar)

    async def close(self):
        await self._current_session.close()

    def get_credentials(self):
        creds = self.user
        morsel_list = []
        for morsel in self._current_session.cookie_jar.__iter__():
            morsel_list.append(morsel)
        creds['cookie_jar'] = pickle.dumps(morsel_list).hex()
        creds['current_auth_token'] = self._current_auth_token
        creds['current_sc_token'] = self._current_sc_token
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
        self._current_session.cookie_jar.update_cookies({'ScAuthTokenData2020': token})

    def set_current_sc_token(self, token):
        self._current_sc_token = token
        self._current_session.cookie_jar.update_cookies({'BearerToken': token})

    def get_current_auth_token(self):
        return self._current_auth_token

    def get_current_sc_token(self):
        return self._current_sc_token

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
            headers["Authorization"] = f"Bearer {self._current_sc_token}"
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["User-Agent"] = USER_AGENT
        try:
            resp = await self._current_session.get(url, headers=headers)
            await self._update_cookies_from_response(resp)
            return await resp.json()
        except Exception as e:
            log.exception(f"WARNING: The request failed with exception {repr(e)}. Attempting to refresh credentials...")
            await self._refresh_credentials_social_club_light()
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

    async def _update_cookies_from_response(self, resp: aiohttp.ClientResponse, exclude=None):
        if exclude is None:
            exclude = []
        filtered_cookies = resp.cookies
        for key, morsel in filtered_cookies.items():
            if key not in exclude:
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_COOKIE_UPDATED: Found Cookie {key}: {str(morsel)}")
                self._current_session.cookie_jar.update_cookies({key: morsel})

    async def _get_user_json(self, message=None):
        try:
            old_auth = self._current_auth_token
            if LOG_SENSITIVE_DATA:
                log.debug(f"ROCKSTAR_OLD_AUTH: {old_auth}")
            else:
                log.debug(f"ROCKSTAR_OLD_AUTH: ***")
            headers = {
                "accept": "*/*",
                "cookie": await self.get_cookies_for_headers(),
                "referer": "https://www.rockstargames.com",
                "user-agent": USER_AGENT
            }
            resp = await self._current_session.get(r"https://www.rockstargames.com/graph.json?operationName=User&"
                                                   r"variables=%7B%22locale%22%3A%22en_us%22%7D&extensions=%7B%22"
                                                   r"persistedQuery%22%3A%7B%22version%22%3A1%2C%22sha256Hash%22%3A%22"
                                                   r"6aa5127bff85d7fc23ffc192c74bb2e38c3c855482b33b2395aa103a554e9241"
                                                   r"%22%7D%7D", headers=headers, allow_redirects=False)
            await self._update_cookies_from_response(resp)
            # aiohttp allows you to get a specified cookie from the previous response.
            filtered_cookies = resp.cookies
            if "TS019978c2" in filtered_cookies:
                ts_val = filtered_cookies['TS019978c2'].value
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_NEW_TS_COOKIE: {ts_val}")
                else:
                    log.debug("ROCKSTAR_NEW_TS_COOKIE: ***")
            if "ScAuthTokenData2020" in filtered_cookies:
                new_auth = filtered_cookies['ScAuthTokenData2020'].value
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_NEW_AUTH: {new_auth}")
                else:
                    log.debug(f"ROCKSTAR_NEW_AUTH: ***")
                self._current_auth_token = new_auth
                if LOG_SENSITIVE_DATA:
                    log.warning("ROCKSTAR_AUTH_CHANGE: The ScAuthTokenData2020 value has changed!")
                if self.user is not None:
                    self._store_credentials(self.get_credentials())
            else:
                # For security purposes, the ScAuthTokenData2020 value (whether hidden or not) is logged, regardless of
                # whether or not it has changed. If the logged outputs are similar between the two, it is harder to tell
                # if the value has really changed or not.
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_NEW_AUTH: {old_auth}")
                else:
                    log.debug(f"ROCKSTAR_NEW_AUTH: ***")
            return await resp.json()
        except Exception as e:
            if message is not None:
                log.warning(message)
            else:
                log.warning("ROCKSTAR_USER_JSON_WARNING: The request to get the user from the graph resulted in this"
                            " exception: " + repr(e) + ". Attempting to refresh credentials...")
            try:
                await self.refresh_credentials()
                return await self._get_user_json(message)
            except Exception:
                log.exception("ROCKSTAR_USER_JSON_ERROR: The request to get the user from the graph failed even after "
                              "attempting to refresh credentials. Revoking user authentication...")
                raise AuthenticationRequired

    async def _get_bearer(self):
        try:
            resp_json = await self._get_user_json()
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_USER_GRAPH_JSON: " + str(resp_json))

            cookie_json = json.loads(urllib.parse.unquote(self._current_auth_token))
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_AUTH_COOKIE: " + str(cookie_json))
            new_bearer = cookie_json["access_token"]
            self.bearer = new_bearer
            self.refresh = cookie_json["refresh_token"]
            return new_bearer
        except Exception as e:
            log.error("ERROR: The request to refresh credentials resulted in this exception: " + repr(e))
            raise

    async def _get_request_verification_token(self, url, referer):
        class RockstarHTMLParser(HTMLParser):
            rv_token = None

            def handle_starttag(self, tag, attrs):
                if tag == "input" and ('name', "__RequestVerificationToken") in attrs:
                    for attr, value in attrs:
                        if attr == "value":
                            self.rv_token = value
                            break

            def get_token(self):
                return self.rv_token

        while self._refreshing:
            await asyncio.sleep(1)
        headers = {
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,"
                       "application/signed-exchange;v=b3"),
            "Cookie": await self.get_cookies_for_headers(),
            "Referer": referer,
            "User-Agent": USER_AGENT
        }
        resp = await self._current_session.get(url, headers=headers)
        await self._update_cookies_from_response(resp)
        resp_text = await resp.text()
        parser = RockstarHTMLParser()
        parser.feed(resp_text)
        rv_token = parser.get_token()
        parser.close()
        return rv_token

    async def _get_google_tag_data(self):
        # To gain access to this information, we need to scrape a hidden input value called __RequestVerificationToken
        # located on the html file at https://socialclub.rockstargames.com/.
        rv_token = await self._get_request_verification_token("https://socialclub.rockstargames.com/",
                                                              "https://socialclub.rockstargames.com/")

        if LOG_SENSITIVE_DATA:
            log.debug(f"ROCKSTAR_SC_REQUEST_VERIFICATION_TOKEN: {rv_token}")

        headers = {
            "Cookie": await self.get_cookies_for_headers(),
            "RequestVerificationToken": rv_token,
            "User-Agent": USER_AGENT
        }
        url = f"https://socialclub.rockstargames.com/ajax/getGoogleTagManagerSetupData?_={int(time() * 1000)}"
        resp = await self._current_session.get(url, headers=headers)
        await self._update_cookies_from_response(resp)
        return await resp.json()

    async def get_played_games(self, callback=False):
        try:
            resp_json = await self._get_google_tag_data()
            if LOG_SENSITIVE_DATA:
                log.debug(f"ROCKSTAR_SC_TAG_DATA: {resp_json}")
            else:
                log.debug(f"ROCKSTAR_SC_TAG_DATA: ***")
            if resp_json['loginState'] == "false":
                raise AuthenticationRequired
            games_owned_string = resp_json['gamesOwned']
            owned_games = []
            for game in games_owned_string.split('|'):
                if game != "Launcher_PC":
                    title_id = get_game_title_id_from_google_tag_id(game)
                    if title_id:
                        owned_games.append(title_id)
            return owned_games
        except Exception:
            if not callback:
                try:
                    await self._refresh_credentials_social_club_light()
                    return await self.get_played_games(callback=True)
                except Exception as e:
                    log.exception("ROCKSTAR_PLAYED_GAMES_ERROR: The request to scrape the user's played games resulted "
                                  "in this exception: " + repr(e))
                    raise
            raise

    async def get_last_played_game(self, friend_name):
        headers = {
            "Authorization": f"Bearer {self._current_sc_token}",
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest"
        }
        try:
            resp = await self._current_session.get("https://scapi.rockstargames.com/profile/getprofile?nickname="
                                                   f"{friend_name}&maxFriends=3", headers=headers)
            await self._update_cookies_from_response(resp)
            resp_json = await resp.json()
        except AssertionError:
            await self._refresh_credentials_social_club_light()
            return await self.get_last_played_game(friend_name)
        try:
            # The last played game is always listed first in the ownedGames list.
            last_played_ugc = resp_json['accounts'][0]['rockstarAccount']['gamesOwned'][0]['name']
            title_id = get_game_title_id_from_ugc_title_id(last_played_ugc + "_PC")
            last_played_time = await get_unix_epoch_time_from_date(resp_json['accounts'][0]
                                                                                  ['rockstarAccount']['gamesOwned'][0]
                                                                                  ['lastSeen'])
            if LOG_SENSITIVE_DATA:
                log.debug(f"{friend_name}'s Last Played Game: "
                          f"{games_cache[title_id]['friendlyName'] if title_id else last_played_ugc}")
            return UserPresence(PresenceState.Online,
                                game_id=str(games_cache[title_id]['rosTitleId']) if title_id else last_played_ugc,
                                in_game_status=f"Last Played {await get_time_passed(last_played_time)}")
        except IndexError:
            # If a game is not found in the gamesOwned list, then the user has not played any games. In this case, we
            # cannot be certain of their presence status.
            if LOG_SENSITIVE_DATA:
                log.warning(f"ROCKSTAR_LAST_PLAYED_WARNING: The user {friend_name} has not played any games!")
            return UserPresence(PresenceState.Unknown)

    async def get_gta_online_stats(self, user_id, friend_name):
        class GTAOnlineStatParser(HTMLParser):
            char_rank = None
            char_title = None
            rank_internal_pos = None

            def handle_starttag(self, tag, attrs):
                if not self.rank_internal_pos and tag == "div" and len(attrs) > 0:
                    class_, name = attrs[0]
                    if not re.search(r"^rankHex right-grad .*", name):
                        return
                    self.rank_internal_pos = self.getpos()[0]

            def handle_data(self, data):
                if not self.rank_internal_pos:
                    return
                if not self.char_rank and self.getpos()[0] == (self.rank_internal_pos + 1):
                    self.char_rank = data
                elif not self.char_title and self.getpos()[0] == (self.rank_internal_pos + 2):
                    # There is a bug in the Social Club API where a user who is past rank 105 no longer has their title
                    # shown. However, they are still a "Kingpin."
                    if int(self.char_rank) >= 105:
                        self.char_title = "Kingpin"
                    else:
                        self.char_title = data

            def get_stats(self):
                return self.char_rank, self.char_title

        url = ("https://socialclub.rockstargames.com/games/gtav/career/overviewAjax?character=Freemode&"
               f"rockstarIds={user_id}&slot=Freemode&nickname={friend_name}&gamerHandle=&gamerTag=&category=Overview"
               f"&_={int(time() * 1000)}")
        headers = {
            'Accept': 'text/html, */*',
            'Cookie': await self.get_cookies_for_headers(),
            "RequestVerificationToken": await self._get_request_verification_token(
                "https://socialclub.rockstargames.com/games/gtav/pc/career/overview/gtaonline",
                "https://socialclub.rockstargames.com/games"),
            'User-Agent': USER_AGENT
        }
        while True:
            try:
                resp = await self._current_session.get(url, headers=headers)
                await self._update_cookies_from_response(resp)
                break
            except aiohttp.ClientResponseError as e:
                if e.status == 429:
                    await asyncio.sleep(5)
                else:
                    raise e
            except Exception:
                raise
        resp_text = await resp.text()
        parser = GTAOnlineStatParser()
        parser.feed(resp_text)
        rank, title = parser.get_stats()
        parser.close()
        if rank and title:
            log.debug(f"ROCKSTAR_GTA_ONLINE_STATS: [{friend_name}] Grand Theft Auto Online: Rank {rank} {title}")
            return UserPresence(PresenceState.Online,
                                game_id="11",
                                in_game_status=f"Grand Theft Auto Online: Rank {rank} {title}")
        else:
            if LOG_SENSITIVE_DATA:
                log.debug(f"ROCKSTAR_GTA_ONLINE_STATS_MISSING: {friend_name} (Rockstar ID: {user_id}) does not have "
                          f"any character stats for Grand Theft Auto Online. Returning default user presence...")
            return await self.get_last_played_game(friend_name)

    async def get_rdo_stats(self, user_id, friend_name):
        headers = {
            'Authorization': f'Bearer {self._current_sc_token}',
            'User-Agent': USER_AGENT,
            'X-Requested-With': 'XMLHttpRequest'
        }
        try:
            resp = await self._current_session.get("https://scapi.rockstargames.com/games/rdo/navigationData?platform=pc&"
                                                   f"rockstarId={user_id}", headers=headers)
            await self._update_cookies_from_response(resp)
            resp_json = await resp.json()
        except AssertionError:
            await self._refresh_credentials_social_club_light()
            return await self.get_rdo_stats(user_id, friend_name)
        try:
            char_name = resp_json['result']['onlineCharacterName']
            char_rank = resp_json['result']['onlineCharacterRank']
        except KeyError:
            if LOG_SENSITIVE_DATA:
                log.debug(f"ROCKSTAR_RED_DEAD_ONLINE_STATS_MISSING: {friend_name} (Rockstar ID: {user_id}) does not "
                          f"have any character stats for Red Dead Online. Returning default user presence...")
            return await self.get_last_played_game(friend_name)
        if LOG_SENSITIVE_DATA:
            log.debug(f"ROCKSTAR_RED_DEAD_ONLINE_STATS_PARTIAL: {friend_name} (Rockstar ID: {user_id}) has a character "
                      f"named {char_name}, who is at rank {str(char_rank)}.")

        # As an added bonus, we will find the user's preferred role (bounty hunter, collector, or trader). This is
        # determined by the acquired rank in each role.
        resp = await self._current_session.get("https://scapi.rockstargames.com/games/rdo/awards/progress?platform=pc&"
                                               f"rockstarId={user_id}", headers=headers)
        await self._update_cookies_from_response(resp)
        resp_json = await resp.json()
        ranks = {
            "Bounty Hunter": None,
            "Collector": None,
            "Trader": None
        }
        for goal in resp_json['challengeGoals']:
            if goal['id'] == "MPAC_Role_BountyHunter_001":
                ranks['Bounty Hunter'] = goal['goalValue']
            elif goal['id'] == "MPAC_Role_Collector_001":
                ranks['Collector'] = goal['goalValue']
            elif goal['id'] == "MPAC_Role_Trader_001":
                ranks['Trader'] = goal['goalValue']
            for rank, val in ranks.items():
                if not val:
                    break
            else:
                break
        max_rank = 0
        highest_rank = ""
        for rank, val in ranks.items():
            if val > max_rank:
                max_rank = val
                highest_rank = rank
            # If two roles have the same rank, then the character is considered to have a Hybrid role.
            elif val == max_rank and max_rank != 0:
                highest_rank = "Hybrid"
                break
        if LOG_SENSITIVE_DATA:
            log.debug(f"ROCKSTAR_RED_DEAD_ONLINE_STATS: [{friend_name}] Red Dead Online: {char_name} - Rank {char_rank}"
                      f" {highest_rank}")
        return UserPresence(PresenceState.Online,
                            game_id="13",
                            in_game_status=f"Red Dead Online: {char_name} - Rank {char_rank} {highest_rank}")

    def _get_rsso_cookie(self) -> (str, str):
        for morsel in self._current_session.cookie_jar.__iter__():
            if re.search("^rsso", morsel.key):
                rsso_name = morsel.key
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_RSSO_NAME: {rsso_name}")
                rsso_value = morsel.value
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_RSSO_VALUE: {rsso_value}")
                return rsso_name, rsso_value

    async def refresh_credentials(self):
        while self._refreshing:
            # If we are already refreshing the credentials, then no other refresh requests should be accepted.
            await asyncio.sleep(3)
        self._refreshing = True
        await self._refresh_credentials_base()
        await self._refresh_credentials_social_club()
        self._refreshing = False

    async def _refresh_credentials_base(self):
        # This request returns a new ScAuthTokenData2020 value, which is used as authentication for the base website of
        # https://www.rockstargames.com/. This value grants access to the get-user.json file found on that website,
        # which contains an access (bearer) token for https://www.rockstargames.com/ and
        # https://scapi.rockstargames.com/.

        # It seems like the Rockstar website connects to https://signin.rockstargames.com/connect/cors/check/rsg via a
        # POST request in order to re-authenticate the user. This request uses a fingerprint as form data.

        # This POST request then returns a message with a code, which is then sent as a request payload to
        # https://www.rockstargames.com/auth/login.json in the form of {code: "{code}"}. Note that {code} includes
        # its own set of quotation marks, so it looks like {code: ""{Numbers/Letters}""}.

        # Finally, this last request updates the cookies that are used for further authentication.
        try:
            url = "https://signin.rockstargames.com/connect/cors/check/rsg"
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Cookie": await self.get_cookies_for_headers(),
                "Content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Host": "signin.rockstargames.com",
                "Origin": "https://www.rockstargames.com",
                "Referer": "https://www.rockstargames.com/",
                "User-Agent": USER_AGENT,
                "X-Requested-With": "XMLHttpRequest"
            }
            data = {"fingerprint": self._fingerprint}
            refresh_resp = await self._current_session.post(url, data=data, headers=headers)
            await self._update_cookies_from_response(refresh_resp)
            refresh_code = await refresh_resp.text()
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_REFRESH_CODE: Got code " + refresh_code + "!")
            # We need to set the new refresh token here, if it is updated.
            try:
                self.set_refresh_token(refresh_resp.cookies['RMT'].value)
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
                log.debug(f"ROCKSTAR_OLD_AUTH_REFRESH: ***")
            url = ("https://www.rockstargames.com/graph.json?operationName=User&variables=%7B%22"
                   f"code%22%3A%22{refresh_code}%22%2C%22locale%22%3A%22en_us%22%7D&"
                   "extensions=%7B%22persistedQuery%22%3A%7B%22version%22%3A1%2C%22sha256Hash%22%3A%"
                   "226aa5127bff85d7fc23ffc192c74bb2e38c3c855482b33b2395aa103a554e9241%22%7D%7D")
            headers = {
                "Accept": "*/*",
                "Cookie": await self.get_cookies_for_headers(),
                "Content-type": "application/json",
                "Referer": "https://www.rockstargames.com/",
                "User-Agent": USER_AGENT
            }
            final_request = await self._current_session.get(url, headers=headers)
            await self._update_cookies_from_response(final_request)
            final_json = await final_request.json()
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_REFRESH_JSON: " + str(final_json))
            filtered = final_request.cookies
            new_auth = filtered['ScAuthTokenData2020'].value
            self._current_auth_token = new_auth
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_NEW_AUTH_REFRESH: " + new_auth)
            else:
                log.debug(f"ROCKSTAR_NEW_AUTH_REFRESH: ***")
            if old_auth != new_auth:
                log.debug("ROCKSTAR_REFRESH_SUCCESS: The user has been successfully re-authenticated!")
        except Exception as e:
            log.exception("ROCKSTAR_REFRESH_FAILURE: The attempt to re-authenticate the user has failed with the "
                          "exception " + repr(e) + ". Logging the user out...")
            self._refreshing = False
            raise InvalidCredentials

    async def _refresh_credentials_social_club_light(self):
        # If the user attempts to use the Social Club bearer token within ten hours of having received its latest
        # version, then they may simply make a POST request to
        # https://socialclub.rockstargames.com/connect/refreshaccess in order to get a new bearer token.
        self._refreshing = True
        old_auth = self._current_sc_token
        headers = {
            "Content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest"
        }
        data = f"accessToken={old_auth}"
        try:
            resp = await self._current_session.post("https://socialclub.rockstargames.com/connect/refreshaccess",
                                                    data=data, headers=headers, allow_redirects=True)
            await self._update_cookies_from_response(resp)
            filtered_cookies = resp.cookies
            if "BearerToken" in filtered_cookies:
                self._current_sc_token = filtered_cookies["BearerToken"].value
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_SC_BEARER_NEW: {self._current_sc_token}")
                else:
                    log.debug(f"ROCKSTAR_SC_BEARER_NEW: {self._current_sc_token[:5]}***{self._current_sc_token[-3:]}")
                if old_auth != self._current_sc_token:
                    log.debug("ROCKSTAR_SC_LIGHT_REFRESH_SUCCESS: The Social Club user was successfully "
                              "re-authenticated!")
                self._refreshing = False
            else:
                # If a request was made to get a new bearer token but a new token was not granted, then it is assumed
                # that the alternate longer method for refreshing the user's credentials is required.
                log.warning("ROCKSTAR_SC_LIGHT_REFRESH_FAILED: The light method for refreshing the Social Club "
                            "user's authentication has failed. Falling back to the strict refresh method...")
                self._refreshing = False
                await self.refresh_credentials()
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                log.warning("ROCKSTAR_SC_LIGHT_REFRESH_FAILED: The light method for refreshing the Social Club user's "
                            "authentication has failed. Falling back to the strict refresh method...")
                self._refreshing = False
                await self.refresh_credentials()

    async def _refresh_credentials_social_club(self):
        # There are instances where the bearer token provided by the get-user.json endpoint is insufficient (i.e.,
        # sending a message to a user or getting the tags from the Google Tag Manager). This requires a separate access
        # (bearer) token from the https://socialclub.rockstargames.com/ website.

        # To refresh the Social Club bearer token (hereafter referred to as the BearerToken), first make a GET request
        # to https://signin.rockstargames.com/connect/check/socialclub?returnUrl=%2FBlocker%2FAuthCheck&lang=en-US. Make
        # sure to supply the current cookies as a header. Also, this request sets a new TS01a305c4 cookie, so its value
        # should be updated.

        # Next, make a POST request to https://signin.rockstargames.com/api/connect/check/socialclub. For request
        # headers, Content-Type must be application/json, Cookie must be the current cookies, and X-Requested-With must
        # be XMLHttpRequest. This response returns a JSON containing a single key: redirectUrl, which corresponds to the
        # unique URL for the user to refresh their bearer token.

        # Lastly, make a GET request to the specified redirectUrl and set the request header X-Requested-With to
        # XMLHttpRequest. This request sets the updated value for the BearerToken cookie, allowing further requests to
        # the Social Club API to be made.
        try:
            old_auth = self._current_sc_token
            if LOG_SENSITIVE_DATA:
                log.debug(f"ROCKSTAR_SC_BEARER_OLD: {old_auth}")
            else:
                log.debug(f"ROCKSTAR_SC_BEARER_OLD: {old_auth[:5]}***{old_auth[-3:]}")
            url = ("https://signin.rockstargames.com/connect/check/socialclub?returnUrl=%2FBlocker%2FAuthCheck&lang=en-"
                   "US")
            headers = {
                "Cookie": await self.get_cookies_for_headers(),
                "User-Agent": USER_AGENT
            }
            resp = await self._current_session.get(url, headers=headers)
            await self._update_cookies_from_response(resp)

            url = "https://signin.rockstargames.com/api/connect/check/socialclub"
            rsso_name, rsso_value = self._get_rsso_cookie()
            headers = {
                "Content-Type": "application/json",
                # A 400 error is returned by lazily submitting all cookies, so we need to send only the cookies that
                # matter.
                "Cookie": f"RMT={self.get_refresh_token()};{rsso_name}={rsso_value}",
                "Referer": ("https://signin.rockstargames.com/connect/check/socialclub?returnUrl=%2FBlocker%2FAuthCheck"
                            "&lang=en-US"),
                "User-Agent": USER_AGENT,
                "X-Requested-With": "XMLHttpRequest"
            }
            data = {
                "fingerprint": self._fingerprint,
                "returnUrl": "/Blocker/AuthCheck"
            }
            # Using a context manager here will prevent the extra cookies from being sent.
            async with create_client_session() as s:
                resp = await s.post(url, json=data, headers=headers)
            await self._update_cookies_from_response(resp)
            filtered_cookies = resp.cookies
            if "TS01a305c4" in filtered_cookies:
                if LOG_SENSITIVE_DATA:
                    log.debug(f"ROCKSTAR_SC_TS01a305c4: {str(filtered_cookies['TS01a305c4'].value)}")
                else:
                    log.debug("ROCKSTAR_SC_TS01a305c4: ***")
            else:
                raise BackendError
            # We need to set the new refresh token here, if it is updated.
            try:
                self.set_refresh_token(resp.cookies['RMT'].value)
            except KeyError:
                if LOG_SENSITIVE_DATA:
                    log.debug("ROCKSTAR_RMT_MISSING: The RMT cookie is missing, presumably because the user has not "
                              "enabled two-factor authentication. Proceeding anyways...")
                self.set_refresh_token('')
            resp_json = await resp.json()
            url = resp_json["redirectUrl"]
            if LOG_SENSITIVE_DATA:
                log.debug(f"ROCKSTAR_SC_REDIRECT_URL: {url}")
            headers = {
                "Content-Type": "application/json",
                "Cookie": await self.get_cookies_for_headers(),
                "User-Agent": USER_AGENT,
                "X-Requested-With": "XMLHttpRequest"
            }
            resp = await self._current_session.get(url, headers=headers, allow_redirects=False)
            await self._update_cookies_from_response(resp)
            filtered_cookies = resp.cookies
            for key, morsel in filtered_cookies.items():
                if key == "BearerToken":
                    if LOG_SENSITIVE_DATA:
                        log.debug(f"ROCKSTAR_SC_BEARER_NEW: {morsel.value}")
                    else:
                        log.debug(f"ROCKSTAR_SC_BEARER_NEW: {morsel.value[:5]}***{morsel.value[-3:]}")
                    self._current_sc_token = morsel.value
                    if old_auth != self._current_sc_token:
                        log.debug("ROCKSTAR_SC_REFRESH_SUCCESS: The Social Club user has been successfully "
                                  "re-authenticated!")
                    break
        except aiohttp.ClientConnectorError:
            log.error(f"ROCKSTAR_PLUGIN_OFFLINE: The user is not online.")
            self._refreshing = False
            raise NetworkError
        except Exception as e:
            log.exception(f"ROCKSTAR_SC_REFRESH_FAILURE: The attempt to re-authenticate the user on the Social Club has"
                          f" failed with the exception {repr(e)}. Logging the user out...")
            self._refreshing = False
            raise InvalidCredentials

    async def authenticate(self):
        await self._refresh_credentials_social_club()
        if self._auth_lost_callback or self._debug_always_refresh:
            # We need to refresh the credentials.
            await self.refresh_credentials()
            self._auth_lost_callback = None
        try:
            self.bearer = await self._get_bearer()
        except Exception:
            raise InvalidCredentials
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
            await self._update_cookies_from_response(resp_user)
            resp_user_text = await resp_user.json()
        except Exception as e:
            log.exception("ERROR: There was a problem with getting the user information with the token. "
                          "Exception: " + repr(e))
            raise InvalidCredentials
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
        self.user = {"display_name": display_name, "rockstar_id": str(rockstar_id)}
        log.debug("ROCKSTAR_STORE_CREDENTIALS: Preparing to store credentials...")
        # log.debug(self.get_credentials()) - Reduce Console Spam (Enable this if you need to.)
        self._store_credentials(self.get_credentials())
        return self.user
