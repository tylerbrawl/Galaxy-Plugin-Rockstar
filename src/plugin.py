from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.consts import Platform, PresenceState
from galaxy.api.types import NextStep, Authentication, Game, LocalGame, LocalGameState, UserInfo, Achievement, \
    GameTime, UserPresence
from galaxy.api.errors import InvalidCredentials, AuthenticationRequired, NetworkError, UnknownError

from file_read_backwards import FileReadBackwards
from time import time
from typing import List, Any
import asyncio
import dataclasses
import datetime
import logging as log
import os
import pickle
import re
import sys
import webbrowser

from consts import AUTH_PARAMS, NoGamesInLogException, NoLogFoundException, IS_WINDOWS, LOG_SENSITIVE_DATA, \
    ARE_ACHIEVEMENTS_IMPLEMENTED, CONFIG_OPTIONS, get_unix_epoch_time_from_date
from game_cache import games_cache, get_game_title_id_from_ros_title_id, get_achievement_id_from_ros_title_id
from http_client import BackendClient
from version import __version__

if IS_WINDOWS:
    import ctypes.wintypes
    from local import LocalClient, check_if_process_exists


@dataclasses.dataclass
class RunningGameInfo(object):
    _pid = None
    _start_time = None

    def set_info(self, pid):
        self._pid = pid
        self._start_time = datetime.datetime.now().timestamp()

    def get_pid(self):
        return self._pid

    def clear_pid(self):
        self._pid = None

    def get_start_time(self):
        return self._start_time

    def update_start_time(self):
        self._start_time = datetime.datetime.now().timestamp()


class RockstarPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(Platform.Rockstar, __version__, reader, writer, token)
        self.games_cache = games_cache
        self._http_client = BackendClient(self.store_credentials)
        self._local_client = None
        self.total_games_cache = self.create_total_games_cache()
        self._all_achievements_cache = {}
        self.friends_cache = []
        self.presence_cache = {}
        self.owned_games_cache = []
        self.last_online_game_check = time() - 300
        self.local_games_cache = {}
        self.game_time_cache = {}
        self.running_games_info_list = {}
        self.game_is_loading = True
        self.checking_for_new_games = False
        self.updating_game_statuses = False
        self.buffer = None
        if IS_WINDOWS:
            self._local_client = LocalClient()
            self.buffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, self.buffer)
            self.documents_location = self.buffer.value

    def is_authenticated(self):
        return self._http_client.is_authenticated()

    @staticmethod
    def loads_js(file):
        with open(os.path.abspath(os.path.join(__file__, '..', 'js', file)), 'r') as f:
            return f.read()

    def handshake_complete(self):
        game_time_cache_in_persistent_cache = False
        for key, value in self.persistent_cache.items():
            if "achievements_" in key:
                log.debug("ROCKSTAR_CACHE_IMPORT: Importing " + key + " from persistent cache...")
                self._all_achievements_cache[key] = pickle.loads(bytes.fromhex(value))
            elif key == "game_time_cache":
                self.game_time_cache = pickle.loads(bytes.fromhex(value))
                game_time_cache_in_persistent_cache = True
        if IS_WINDOWS and not game_time_cache_in_persistent_cache:
            # The game time cache was not found in the persistent cache, so the plugin will instead attempt to get the
            # cache from the user's file stored on their disk.
            file_location = os.path.join(self.documents_location, "RockstarPlayTimeCache.txt")
            try:
                file = open(file_location, "r")
                for line in file.readlines():
                    if line[:1] != "#":
                        log.debug("ROCKSTAR_LOCAL_GAME_TIME_FROM_FILE: " + str(pickle.loads(bytes.fromhex(line))))
                        self.game_time_cache = pickle.loads(bytes.fromhex(line))
                        break
                if not self.game_time_cache:
                    log.warning("ROCKSTAR_NO_GAME_TIME: The user's played time could not be found in neither the "
                                "persistent cache nor the designated local file. Let's hope that the user is new...")
            except FileNotFoundError:
                log.warning("ROCKSTAR_NO_GAME_TIME: The user's played time could not be found in neither the persistent"
                            " cache nor the designated local file. Let's hope that the user is new...")

    async def authenticate(self, stored_credentials=None):
        try:
            self._http_client.create_session(stored_credentials)
        except KeyError:
            log.error("ROCKSTAR_OLD_LOG_IN: The user has likely previously logged into the plugin with a version less "
                      "than v0.3, and their credentials might be corrupted. Forcing a log-out...")
            raise InvalidCredentials()
        if not stored_credentials:
            # We will create the fingerprint JavaScript dictionary here.
            fingerprint_js = {
                r'https://www.rockstargames.com/': [
                    self.loads_js("fingerprint2.js"),
                    self.loads_js("HashGen.js"),
                    self.loads_js("GenerateFingerprint.js")
                ]
            }
            return NextStep("web_session", AUTH_PARAMS, js=fingerprint_js)
        try:
            log.info("INFO: The credentials were successfully obtained.")
            if LOG_SENSITIVE_DATA:
                cookies = pickle.loads(bytes.fromhex(stored_credentials['cookie_jar']))
                log.debug("ROCKSTAR_COOKIES_FROM_HEX: " + str(cookies))  # sensitive data hidden by default
            # for cookie in cookies:
            #   self._http_client.update_cookies({cookie.name: cookie.value})
            self._http_client.set_current_auth_token(stored_credentials['current_auth_token'])
            self._http_client.set_current_sc_token(stored_credentials['current_sc_token'])
            self._http_client.set_refresh_token_absolute(
                pickle.loads(bytes.fromhex(stored_credentials['refresh_token'])))
            self._http_client.set_fingerprint(stored_credentials['fingerprint'])
            log.info("INFO: The stored credentials were successfully parsed. Beginning authentication...")
            user = await self._http_client.authenticate()
            return Authentication(user_id=user['rockstar_id'], user_name=user['display_name'])
        except (NetworkError, UnknownError):
            raise
        except Exception as e:
            log.warning("ROCKSTAR_AUTH_WARNING: The exception " + repr(e) + " was thrown, presumably because of "
                        "outdated credentials. Attempting to get new credentials...")
            self._http_client.set_auth_lost_callback(True)
            try:
                user = await self._http_client.authenticate()
                return Authentication(user_id=user['rockstar_id'], user_name=user['display_name'])
            except Exception as e:
                log.error("ROCKSTAR_AUTH_FAILURE: Something went terribly wrong with the re-authentication. " + repr(e))
                log.exception("ROCKSTAR_STACK_TRACE")
                raise InvalidCredentials

    async def pass_login_credentials(self, step, credentials, cookies):
        if LOG_SENSITIVE_DATA:
            log.debug("ROCKSTAR_COOKIE_LIST: " + str(cookies))
        for cookie in cookies:
            if cookie['name'] == "ScAuthTokenData":
                self._http_client.set_current_auth_token(cookie['value'])
            if cookie['name'] == "BearerToken":
                self._http_client.set_current_sc_token(cookie['value'])
            if cookie['name'] == "RMT":
                if cookie['value'] != "":
                    if LOG_SENSITIVE_DATA:
                        log.debug("ROCKSTAR_REMEMBER_ME: Got RMT: " + cookie['value'])
                    else:
                        log.debug("ROCKSRAR_REMEMBER_ME: Got RMT: ***")  # Only asterisks are shown here for consistency
                        # with the output when the user has a blank RMT from multi-factor authentication.
                    self._http_client.set_refresh_token(cookie['value'])
                else:
                    if LOG_SENSITIVE_DATA:
                        log.debug("ROCKSTAR_REMEMBER_ME: Got RMT: [Blank!]")
                    else:
                        log.debug("ROCKSTAR_REMEMBER_ME: Got RMT: ***")
                    self._http_client.set_refresh_token('')
            if cookie['name'] == "fingerprint":
                if LOG_SENSITIVE_DATA:
                    log.debug("ROCKSTAR_FINGERPRINT: Got fingerprint: " + cookie['value'].replace("$", ";"))
                else:
                    log.debug("ROCKSTAR_FINGERPRINT: Got fingerprint: ***")
                self._http_client.set_fingerprint(cookie['value'].replace("$", ";"))
                # We will not add the fingerprint as a cookie to the session; it will instead be stored with the user's
                # credentials.
                continue
            if re.search("^rsso", cookie['name']):
                if LOG_SENSITIVE_DATA:
                    log.debug("ROCKSTAR_RSSO: Got " + cookie['name'] + ": " + cookie['value'])
                else:
                    log.debug(f"ROCKSTAR_RSSO: Got rsso-***: {cookie['value'][:5]}***{cookie['value'][-3:]}")
            cookie_object = {
                "name": cookie['name'],
                "value": cookie['value'],
                "domain": cookie['domain'],
                "path": cookie['path']
            }
            self._http_client.update_cookie(cookie_object)
        try:
            user = await self._http_client.authenticate()
        except Exception as e:
            log.error(repr(e))
            raise InvalidCredentials
        return Authentication(user_id=user["rockstar_id"], user_name=user["display_name"])

    async def shutdown(self):
        # At this point, we can write to a file to keep a cached copy of the user's played time.
        # This will prevent the play time from being erased if the user loses authentication.
        if IS_WINDOWS and self.game_time_cache:
            # For the sake of convenience, we will store this file in the user's Documents folder.
            # Obviously, this feature is only compatible with (and relevant for) Windows machines.
            file_location = os.path.join(self.documents_location, "RockstarPlayTimeCache.txt")
            file = open(file_location, "w+")
            file.write("# This file contains a cached copy of the user's play time for the Rockstar plugin for GOG "
                       "Galaxy 2.0.\n")
            file.write("# DO NOT EDIT THIS FILE IN ANY WAY, LEST THE CACHE GETS CORRUPTED AND YOUR PLAY TIME IS LOST!\n"
                       )
            file.write(pickle.dumps(self.game_time_cache).hex())
            file.close()
        await self._http_client.close()
        await super().shutdown()

    def create_total_games_cache(self):
        cache = []
        for title_id in list(games_cache):
            cache.append(self.create_game_from_title_id(title_id))
        return cache

    if ARE_ACHIEVEMENTS_IMPLEMENTED:
        async def get_unlocked_achievements(self, game_id, context):
            # The Social Club API has an authentication endpoint located at https://scapi.rockstargames.com/
            # achievements/awardedAchievements?title=[game-id]&platform=pc&rockstarId=[rockstar-ID], which returns a
            # list of the user's unlocked achievements for the specified game. It uses the Social Club standard for
            # authentication (a request header named Authorization containing "Bearer [Bearer-Token]").

            title_id = get_game_title_id_from_ros_title_id(game_id)
            if games_cache[title_id]["achievementId"] is None or \
                    (games_cache[title_id]["isPreOrder"]):
                return []
            log.debug("ROCKSTAR_ACHIEVEMENT_CHECK: Beginning achievements check for " +
                      title_id + " (Achievement ID: " + get_achievement_id_from_ros_title_id(game_id) + ")...")
            # Now, we can begin getting the user's achievements for the specified game.
            achievement_id = get_achievement_id_from_ros_title_id(game_id)
            url = (f"https://scapi.rockstargames.com/achievements/awardedAchievements?title={achievement_id}"
                   f"&platform=pc&rockstarId={self._http_client.get_rockstar_id()}")
            unlocked_achievements = await self._http_client.get_json_from_request_strict(url)
            if not str("achievements_" + achievement_id) in self._all_achievements_cache:
                # In order to prevent having to make an HTTP request for a game's entire achievement list, it would be
                # better to store it in a cache.
                log.debug("ROCKSTAR_MISSING_CACHE: The achievements list for " + title_id + " is not in the persistent "
                          "cache!")
                await self.update_achievements_cache(achievement_id)
            all_achievements = self._all_achievements_cache[str("achievements_" + achievement_id)]
            achievements_dict = unlocked_achievements["awardedAchievements"]
            achievements_list = []
            for key, value in achievements_dict.items():
                # What if an achievement is added to the Social Club after the cache was already made? In this event, we
                # need to refresh the cache.
                if int(key) > len(all_achievements):
                    await self.update_achievements_cache(achievement_id)
                    all_achievements = self._all_achievements_cache[str("achievements_" + achievement_id)]
                achievement_num = key
                unlock_time = await get_unix_epoch_time_from_date(value["dateAchieved"])
                achievement_name = all_achievements[int(key) - 1]["name"]
                achievements_list.append(Achievement(unlock_time, achievement_num, achievement_name))
            return achievements_list

        async def update_achievements_cache(self, achievement_id):
            url = f"https://scapi.rockstargames.com/achievements/all?title={achievement_id}&platform=pc"
            all_achievements = await self._http_client.get_json_from_request_strict(url)
            self._all_achievements_cache[str("achievements_" + achievement_id)] = all_achievements["achievements"]
            log.debug("ROCKSTAR_ACHIEVEMENTS: Pushing achievements_" + achievement_id + " to the persistent cache...")
            self.persistent_cache[str("achievements_" + achievement_id)] = pickle.dumps(
                all_achievements["achievements"]).hex()
            log.debug("ROCKSTAR_NEW_CACHE: " + self.persistent_cache[str("achievements_" + achievement_id)])
            self.push_cache()



    async def get_friends(self) -> List[UserInfo]:
        # The Social Club website returns a list of the current user's friends through the url
        # https://scapi.rockstargames.com/friends/getFriendsFiltered?onlineService=sc&nickname=&pageIndex=0&pageSize=30.
        # The nickname URL parameter is left blank because the website instead uses the bearer token to get the correct
        # information. The last two parameters are of great importance, however. The parameter pageSize determines the
        # number of friends given on that page's list, while pageIndex keeps track of the page that the information is
        # on. The maximum number for pageSize is 30, so that is what we will use to cut down the number of HTTP
        # requests.

        # We first need to get the number of friends.
        url = ("https://scapi.rockstargames.com/friends/getFriendsFiltered?onlineService=sc&nickname=&"
               "pageIndex=0&pageSize=30")
        try:
            current_page = await self._http_client.get_json_from_request_strict(url)
        except TimeoutError:
            log.warning("ROCKSTAR_FRIENDS_TIMEOUT: The request to get the user's friends at page index 0 timed out. "
                        "Returning the cached list...")
            return self.friends_cache
        if LOG_SENSITIVE_DATA:
            log.debug("ROCKSTAR_FRIENDS_REQUEST: " + str(current_page))
        else:
            log.debug("ROCKSTAR_FRIENDS_REQUEST: ***")
        num_friends = current_page['rockstarAccountList']['totalFriends']
        num_pages_required = num_friends / 30 if num_friends % 30 != 0 else (num_friends / 30) - 1

        # Now, we need to get the information about the friends.
        friends_list = current_page['rockstarAccountList']['rockstarAccounts']
        return_list = await self._parse_friends(friends_list)

        # The first page is finished, but now we need to work on any remaining pages.
        if num_pages_required > 0:
            for i in range(1, int(num_pages_required + 1)):
                try:
                    url = ("https://scapi.rockstargames.com/friends/getFriendsFiltered?onlineService=sc&nickname=&"
                           "pageIndex=" + str(i) + "&pageSize=30")
                    for friend in await self._get_friends(url):
                        return_list.append(friend)
                except TimeoutError:
                    log.warning(f"ROCKSTAR_FRIENDS_TIMEOUT: The request to get the user's friends at page index {i} "
                                f"timed out. Returning the cached list...")
                    return self.friends_cache
        return return_list

    async def _get_friends(self, url: str) -> List[UserInfo]:
        try:
            current_page = await self._http_client.get_json_from_request_strict(url)
        except TimeoutError:
            raise
        friends_list = current_page['rockstarAccountList']['rockstarAccounts']
        return await self._parse_friends(friends_list)

    async def _parse_friends(self, friends_list: dict) -> List[UserInfo]:
        return_list = []
        for i in range(0, len(friends_list)):
            avatar_uri = f"https://a.rsg.sc/n/{friends_list[i]['displayName'].lower()}/l"
            profile_uri = f"https://socialclub.rockstargames.com/member/{friends_list[i]['displayName']}/"
            friend = UserInfo(user_id=str(friends_list[i]['rockstarId']),
                              user_name=friends_list[i]['displayName'],
                              avatar_url=avatar_uri,
                              profile_url=profile_uri)
            return_list.append(friend)
            for cached_friend in self.friends_cache:
                if cached_friend.user_id == friend.user_id:
                    break
            else:  # An else-statement occurs after a for-statement if the latter finishes WITHOUT breaking.
                self.friends_cache.append(friend)
            if LOG_SENSITIVE_DATA:
                log.debug("ROCKSTAR_FRIEND: Found " + friend.user_name + " (Rockstar ID: " +
                          str(friend.user_id) + ")")
            else:
                log.debug(f"ROCKSTAR_FRIEND: Found {friend.user_name[:1]}*** (Rockstar ID: ***)")
        return return_list

    async def get_owned_games_online(self):
        # Get the list of games_played from https://socialclub.rockstargames.com/ajax/getGoogleTagManagerSetupData.
        owned_title_ids = []
        online_check_success = True
        self.last_online_game_check = time()
        try:
            played_games = await self._http_client.get_played_games()
            for game in played_games:
                owned_title_ids.append(game)
                log.debug("ROCKSTAR_ONLINE_GAME: Found played game " + game + "!")
        except Exception as e:
            log.error("ROCKSTAR_PLAYED_GAMES_ERROR: The exception " + repr(e) + " was thrown when attempting to get"
                      " the user's played games online. Falling back to log file check...")
            online_check_success = False
        return owned_title_ids, online_check_success

    async def get_owned_games(self, owned_title_ids=None, online_check_success=False):
        # Here is the actual implementation of getting the user's owned games:
        # -Get the list of games_played from rockstargames.com/auth/get-user.json.
        #   -If possible, use the launcher log to confirm which games are actual launcher games and which are
        #   Steam/Retail games.
        #   -If it is not possible to use the launcher log, then just use the list provided by the website.
        if owned_title_ids is None:
            owned_title_ids = []
        if not self.is_authenticated():
            raise AuthenticationRequired()

        # The log is in the Documents folder.
        current_log_count = 0
        log_file = None
        log_file_append = ""
        # The Rockstar Games Launcher generates 10 log files before deleting them in a FIFO fashion. Old log files are
        # given a number ranging from 1 to 9 in their name. In case the first log file does not have all of the games,
        # we need to check the other log files, if possible.
        while current_log_count < 10:
            # We need to prevent the log file check for Mac users.
            if not IS_WINDOWS:
                break
            try:
                if current_log_count != 0:
                    log_file_append = ".0" + str(current_log_count)
                log_file = os.path.join(self.documents_location, "Rockstar Games\\Launcher\\launcher" + log_file_append
                                        + ".log")
                if LOG_SENSITIVE_DATA:
                    log.debug("ROCKSTAR_LOG_LOCATION: Checking the file " + log_file + "...")
                else:
                    log.debug("ROCKSTAR_LOG_LOCATION: Checking the file ***...")  # The path to the Launcher log file
                    # likely contains the user's PC profile name (C:\Users\[Name]\Documents...).
                owned_title_ids = await self.parse_log_file(log_file, owned_title_ids, online_check_success)
                break
            except NoGamesInLogException:
                log.warning("ROCKSTAR_LOG_WARNING: There are no owned games listed in " + str(log_file) + ". Moving to "
                            "the next log file...")
                current_log_count += 1
            except NoLogFoundException:
                log.warning("ROCKSTAR_LAST_LOG_REACHED: There are no more log files that can be found and/or read "
                            "from. Assuming that the online list is correct...")
                break
            except Exception:
                # This occurs after ROCKSTAR_LOG_ERROR.
                break
        if current_log_count == 10:
            log.warning("ROCKSTAR_LAST_LOG_REACHED: There are no more log files that can be found and/or read "
                        "from. Assuming that the online list is correct...")

        for title_id in owned_title_ids:
            game = self.create_game_from_title_id(title_id)
            if game not in self.owned_games_cache:
                log.debug("ROCKSTAR_ADD_GAME: Adding " + title_id + " to owned games cache...")
                self.add_game(game)
                self.owned_games_cache.append(game)

        return self.owned_games_cache

    @staticmethod
    async def parse_log_file(log_file, owned_title_ids, online_check_success):
        owned_title_ids_ = owned_title_ids
        checked_games_count = 0
        total_games_count = len(games_cache) - 1  # We need to subtract 1 to account for the Launcher.
        if os.path.exists(log_file):
            with FileReadBackwards(log_file, encoding="utf-8") as frb:
                while checked_games_count < total_games_count:
                    try:
                        line = frb.readline()
                    except UnicodeDecodeError:
                        log.warning("ROCKSTAR_LOG_UNICODE_WARNING: An invalid Unicode character was found in the line "
                                    + line + ". Continuing to next line...")
                        continue
                    except Exception as e:
                        log.error("ROCKSTAR_LOG_ERROR: Reading " + line + " from the log file resulted in the "
                                  "exception " + repr(e) + " being thrown. Using the online list... (Please report "
                                  "this issue on the plugin's GitHub page!)")
                        raise
                    if not line:
                        log.error("ROCKSTAR_LOG_FINISHED_ERROR: The entire log file was read, but all of the games "
                                  "could not be accounted for. Proceeding to import the games that have been "
                                  "confirmed...")
                        raise NoGamesInLogException()
                    # We need to do two main things with the log file:
                    # 1. If a game is present in owned_title_ids but not owned according to the log file, then it is
                    #    assumed to be a non-Launcher game, and is removed from the list.
                    # 2. If a game is owned according to the log file but is not already present in owned_title_ids,
                    #    then it is assumed that the user has purchased the game on the Launcher, but has not yet played
                    #    it. In this case, the game will be added to owned_title_ids.
                    if ("launcher" not in line) and ("on branch " in line):  # Found a game!
                        # Each log line for a title branch report describes the title id of the game starting at
                        # character 65. Interestingly, the lines all have the same colon as character 75. This implies
                        # that this format was intentionally done by Rockstar, so they likely will not change it anytime
                        # soon.
                        title_id = line[65:75].strip()
                        log.debug("ROCKSTAR_LOG_GAME: The game with title ID " + title_id + " is owned!")
                        if title_id not in owned_title_ids_:
                            if online_check_success is True:
                                # Case 2: The game is owned, but has not been played.
                                log.warning("ROCKSTAR_UNPLAYED_GAME: The game with title ID " + title_id +
                                            " is owned, but it has never been played!")
                            owned_title_ids_.append(title_id)
                        checked_games_count += 1
                    elif "no branches!" in line:
                        title_id = line[65:75].strip()
                        if title_id in owned_title_ids_:
                            # Case 1: The game is not actually owned on the launcher.
                            log.warning("ROCKSTAR_FAKE_GAME: The game with title ID " + title_id + " is not owned on "
                                        "the Rockstar Games Launcher!")
                            owned_title_ids_.remove(title_id)
                        checked_games_count += 1
                    if checked_games_count == total_games_count:
                        break
            return owned_title_ids_
        else:
            raise NoLogFoundException()

    async def get_game_time(self, game_id, context):
        # Although the Rockstar Games Launcher does track the played time for each game, there is currently no known
        # method for accessing this information. As such, game time will be recorded when games are launched through the
        # Galaxy 2.0 client.

        title_id = get_game_title_id_from_ros_title_id(game_id)
        if title_id in self.running_games_info_list:
            # The game is running (or has been running).
            start_time = self.running_games_info_list[title_id].get_start_time()
            self.running_games_info_list[title_id].update_start_time()
            current_time = datetime.datetime.now().timestamp()
            minutes_passed = (current_time - start_time) / 60
            if not self.running_games_info_list[title_id].get_pid():
                # The PID has been set to None, which means that the game has exited (see self.check_game_status). Now
                # that the start time is recorded, the game can be safely removed from the list of running games.
                del self.running_games_info_list[title_id]
            if self.game_time_cache[title_id]['time_played']:
                # The game has been played before, so the time will need to be added to the existing cached time.
                total_time_played = self.game_time_cache[title_id]['time_played'] + minutes_passed
                self.game_time_cache[title_id]['time_played'] = total_time_played
                self.game_time_cache[title_id]['last_played'] = current_time
                return GameTime(game_id=game_id, time_played=int(total_time_played), last_played_time=int(current_time))
            else:
                # The game has not been played before, so a new entry in the game_time_cache dictionary must be made.
                self.game_time_cache[title_id] = {
                    'time_played': minutes_passed,
                    'last_played': current_time
                }
                return GameTime(game_id=game_id, time_played=int(minutes_passed), last_played_time=int(current_time))
        else:
            # The game is no longer running (and there is no relevant entry in self.running_games_info_list).
            if title_id not in self.game_time_cache:
                self.game_time_cache[title_id] = {
                    'time_played': None,
                    'last_played': None
                }
            return GameTime(game_id=game_id, time_played=self.game_time_cache[title_id]['time_played'],
                            last_played_time=self.game_time_cache[title_id]['last_played'])

    def game_times_import_complete(self):
        log.debug("ROCKSTAR_GAME_TIME: Pushing the cache of played game times to the persistent cache...")
        self.persistent_cache['game_time_cache'] = pickle.dumps(self.game_time_cache).hex()
        self.push_cache()

    def get_friend_user_name_from_user_id(self, user_id):
        for friend in self.friends_cache:
            if friend.user_id == user_id:
                return friend.user_name
        return None

    async def prepare_user_presence_context(self, user_id_list: List[str]) -> Any:
        if CONFIG_OPTIONS['user_presence_mode'] == 2 or CONFIG_OPTIONS['user_presence_mode'] == 3:
            game = "gtav" if CONFIG_OPTIONS['user_presence_mode'] == 2 else "rdr2"
            return await self._http_client.get_json_from_request_strict("https://scapi.rockstargames.com/friends/"
                                                                        f"getFriendsWhoPlay?title={game}&platform=pc")
        return None

    async def get_user_presence(self, user_id, context):
        # For user presence settings 2 and 3, we need to verify that the specified user owns the game to get their
        # stats.

        friend_name = self.get_friend_user_name_from_user_id(user_id)
        if LOG_SENSITIVE_DATA:
            log.debug(f"ROCKSTAR_PRESENCE_START: Getting user presence for {friend_name} (Rockstar ID: {user_id})...")
        if context:
            for player in context['onlineFriends']:
                if player['userId'] == user_id:
                    # This user owns the specified game, so we can return this information.
                    break
            else:
                # The user does not own the specified game, so we need to return their last played game.
                return await self._http_client.get_last_played_game(friend_name)
        if CONFIG_OPTIONS['user_presence_mode'] == 0:
            self.presence_cache[user_id] = UserPresence(presence_state=PresenceState.Unknown)
            # 0 - Disable User Presence
        else:
            switch = {
                1: self._http_client.get_last_played_game(friend_name),
                # 1 - Get Last Played Game
                2: self._http_client.get_gta_online_stats(user_id, friend_name),
                # 2 - Get GTA Online Character Stats
                3: self._http_client.get_rdo_stats(user_id, friend_name)
                # 3 - Get Red Dead Online Character Stats
            }
            self.presence_cache[user_id] = await asyncio.create_task(switch[CONFIG_OPTIONS['user_presence_mode']])
        return self.presence_cache[user_id]

    async def open_rockstar_browser(self):
        # This method allows the user to install the Rockstar Games Launcher, if it is not already installed.
        url = "https://www.rockstargames.com/downloads"

        log.info(f"Opening Rockstar website {url}")
        webbrowser.open(url)

    def check_game_status(self, title_id):
        state = LocalGameState.None_

        game_installed = self._local_client.get_path_to_game(title_id)
        if game_installed:
            state |= LocalGameState.Installed

            if (title_id in self.running_games_info_list and
                    check_if_process_exists(self.running_games_info_list[title_id].get_pid())):
                state |= LocalGameState.Running
            elif title_id in self.running_games_info_list:
                # We will leave the info in the list, because it still contains the game start time for game time
                # tracking. However, we will set the PID to None to indicate that the game has been closed.
                self.running_games_info_list[title_id].clear_pid()

        return LocalGame(str(self.games_cache[title_id]["rosTitleId"]), state)

    if IS_WINDOWS:
        async def get_local_games(self):
            # Since the API requires that get_local_games returns a list of LocalGame objects, local_list is the value
            # that needs to be returned. However, for internal use (the self.local_games_cache field), the dictionary
            # local_games is used for greater flexibility.
            local_games = {}
            local_list = []
            for game in self.total_games_cache:
                title_id = get_game_title_id_from_ros_title_id(str(game.game_id))
                local_game = self.check_game_status(title_id)
                local_games[title_id] = local_game
                local_list.append(local_game)
            self.local_games_cache = local_games
            log.debug(f"ROCKSTAR_INSTALLED_GAMES: {local_games}")
            return local_list

    async def check_for_new_games(self):
        self.checking_for_new_games = True
        # The Social Club prevents the user from making too many requests in a given time span to prevent a denial of
        # service attack. As such, we need to limit online checking to every 5 minutes. For Windows devices, log file
        # checks will still occur every minute, but for other users, checking games only happens every 5 minutes.
        owned_title_ids = None
        online_check_success = False
        if not self.last_online_game_check or time() >= self.last_online_game_check + 300:
            owned_title_ids, online_check_success = await self.get_owned_games_online()
        elif IS_WINDOWS:
            log.debug("ROCKSTAR_SC_ONLINE_GAMES_SKIP: No attempt has been made to scrape the user's games from the "
                      "Social Club, as it has not been 5 minutes since the last check.")
        await self.get_owned_games(owned_title_ids, online_check_success)
        await asyncio.sleep(60 if IS_WINDOWS else 300)
        self.checking_for_new_games = False

    async def check_game_statuses(self):
        self.updating_game_statuses = True

        for title_id, current_local_game in self.local_games_cache.items():
            new_local_game = self.check_game_status(title_id)
            if new_local_game != current_local_game:
                log.debug(f"ROCKSTAR_LOCAL_CHANGE: The status for {title_id} has changed from: {current_local_game} to "
                          f"{new_local_game}.")
                self.update_local_game_status(new_local_game)
                self.local_games_cache[title_id] = new_local_game

        await asyncio.sleep(5)
        self.updating_game_statuses = False

    def list_running_game_pids(self):
        info_list = []
        for key, value in self.running_games_info_list.items():
            info_list.append(value.get_pid())
        return str(info_list)

    if IS_WINDOWS:
        async def launch_platform_client(self):
            if not self._local_client.get_local_launcher_path():
                await self.open_rockstar_browser()
                return

            pid = await self._local_client.launch_game_from_title_id("launcher")
            if not pid:
                log.warning("ROCKSTAR_LAUNCHER_FAILED: The Rockstar Games Launcher could not be launched!")

    if IS_WINDOWS:
        async def shutdown_platform_client(self):
            if not self._local_client.get_local_launcher_path():
                await self.open_rockstar_browser()
                return

            await self._local_client.kill_launcher()

    if IS_WINDOWS:
        async def launch_game(self, game_id):
            if not self._local_client.get_local_launcher_path():
                await self.open_rockstar_browser()
                return

            title_id = get_game_title_id_from_ros_title_id(game_id)
            game_pid = await self._local_client.launch_game_from_title_id(title_id)
            if game_pid:
                self.running_games_info_list[title_id] = RunningGameInfo()
                self.running_games_info_list[title_id].set_info(game_pid)
                log.debug(f"ROCKSTAR_PIDS: {self.list_running_game_pids()}")
                local_game = LocalGame(game_id, LocalGameState.Running | LocalGameState.Installed)
                self.update_local_game_status(local_game)
                self.local_games_cache[title_id] = local_game
            else:
                log.error(f'cannot start game: {title_id}')

    if IS_WINDOWS:
        async def install_game(self, game_id):
            if not self._local_client.get_local_launcher_path():
                await self.open_rockstar_browser()
                return

            title_id = get_game_title_id_from_ros_title_id(game_id)
            log.debug("ROCKSTAR_INSTALL_REQUEST: Requesting to install " + title_id + "...")
            # There is no need to check if the game is a pre-order, since the InstallLocation registry key will be
            # unavailable if it is.
            self._local_client.install_game_from_title_id(title_id)

    if IS_WINDOWS:
        async def uninstall_game(self, game_id):
            if not self._local_client.get_local_launcher_path():
                await self.open_rockstar_browser()
                return

            title_id = get_game_title_id_from_ros_title_id(game_id)
            log.debug("ROCKSTAR_UNINSTALL_REQUEST: Requesting to uninstall " + title_id + "...")
            self._local_client.uninstall_game_from_title_id(title_id)

    def create_game_from_title_id(self, title_id):
        return Game(str(self.games_cache[title_id]["rosTitleId"]), self.games_cache[title_id]["friendlyName"], None,
                    self.games_cache[title_id]["licenseInfo"])

    def tick(self):
        if not self.is_authenticated():
            return
        if not self.checking_for_new_games:
            log.debug("Checking for new games...")
            asyncio.create_task(self.check_for_new_games())
        if not self.updating_game_statuses and IS_WINDOWS:
            log.debug("Checking local game statuses...")
            asyncio.create_task(self.check_game_statuses())


def main():
    create_and_run_plugin(RockstarPlugin, sys.argv)


if __name__ == "__main__":
    main()
