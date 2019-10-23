from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.consts import Platform, OSCompatibility
from galaxy.api.types import NextStep, Authentication, Game, LocalGame, LocalGameState, FriendInfo, Achievement
from galaxy.api.errors import InvalidCredentials, AuthenticationRequired

from file_read_backwards import FileReadBackwards
import asyncio
import datetime
import logging as log
import os
import pickle
import re
import sys

from consts import IS_WINDOWS
if IS_WINDOWS:
    import ctypes.wintypes
    from local import LocalClient, check_if_process_exists

from consts import AUTH_PARAMS, NoGamesInLogException, NoLogFoundException
from game_cache import games_cache, get_game_title_id_from_ros_title_id, get_game_title_id_from_online_title_id, \
    get_achievement_id_from_ros_title_id
from http_client import AuthenticatedHttpClient
from version import __version__


class RockstarPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(Platform.Rockstar, __version__, reader, writer, token)
        self.games_cache = games_cache
        self._http_client = AuthenticatedHttpClient(self.store_credentials)
        self._local_client = None
        self.total_games_cache = self.create_total_games_cache()
        self._all_achievements_cache = {}
        self.friends_cache = []
        self.owned_games_cache = []
        self.local_games_cache = {}
        self.running_games_pids = {}
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

    def handshake_complete(self):
        for key, value in self.persistent_cache.items():
            if "achievements_" in key:
                log.debug("ROCKSTAR_CACHE_IMPORT: Importing " + key + " from persistent cache...")
                self._all_achievements_cache[key] = pickle.loads(bytes.fromhex(value))

    async def authenticate(self, stored_credentials=None):
        self._http_client.create_session(stored_credentials)
        if not stored_credentials:
            return NextStep("web_session", AUTH_PARAMS)
        try:
            log.info("INFO: The credentials were successfully obtained.")
            cookies = pickle.loads(bytes.fromhex(stored_credentials['session_object'])).cookies
            log.debug("ROCKSTAR_COOKIES_FROM_HEX: " + str(cookies))
            for cookie in cookies:
                cookie_object = {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path
                }
                self._http_client.update_cookie(cookie_object)
            self._http_client.set_current_auth_token(stored_credentials['current_auth_token'])
            self._http_client.set_refresh_token_absolute(
                pickle.loads(bytes.fromhex(stored_credentials['refresh_token'])))
            self._http_client.set_fingerprint(stored_credentials['fingerprint'])
            log.info("INFO: The stored credentials were successfully parsed. Beginning authentication...")
            user = await self._http_client.authenticate()
            return Authentication(user_id=user['rockstar_id'], user_name=user['display_name'])
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
                raise InvalidCredentials()

    async def pass_login_credentials(self, step, credentials, cookies):
        log.debug("ROCKSTAR_COOKIE_LIST: " + str(cookies))
        for cookie in cookies:
            if cookie['name'] == "ScAuthTokenData":
                self._http_client.set_current_auth_token(cookie['value'])
            if cookie['name'] == "RMT":
                log.debug("ROCKSTAR_REMEMBER_ME: Got RMT: " + cookie['value'])
                self._http_client.set_refresh_token(cookie['value'])
            if cookie['name'] == "fingerprint":
                log.debug("ROCKSTAR_FINGERPRINT: Got fingerprint: " + cookie['value'].replace("$", ";"))
                self._http_client.set_fingerprint(cookie['value'].replace("$", ";"))
                # We will not add the fingerprint as a cookie to the session; it will instead be stored with the user's
                # credentials.
                continue
            if re.search("^rsso", cookie['name']):
                log.debug("ROCKSTAR_RSSO: Got " + cookie['name'] + ": " + cookie['value'])
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
            raise InvalidCredentials()
        return Authentication(user_id=user["rockstar_id"], user_name=user["display_name"])

    async def shutdown(self):
        await self._http_client.close()

    def create_total_games_cache(self):
        cache = []
        for title_id in list(games_cache):
            cache.append(self.create_game_from_title_id(title_id))
        return cache

    async def get_unlocked_achievements(self, game_id, context):
        # The Social Club API has an authentication endpoint located at https://scapi.rockstargames.com/achievements/
        # awardedAchievements?title=[game-id]&platform=pc&rockstarId=[rockstar-ID], which returns a list of the user's
        # unlocked achievements for the specified game. It uses the Social Club standard for authentication (a request
        # header named Authorization containing "Bearer [Bearer-Token]").

        if games_cache[get_game_title_id_from_ros_title_id(game_id)]["achievementId"] is None or \
                (games_cache[get_game_title_id_from_ros_title_id(game_id)]["isPreOrder"]):
            return []
        log.debug("ROCKSTAR_ACHIEVEMENT_CHECK: Beginning achievements check for " +
                  get_game_title_id_from_ros_title_id(game_id) + " (Achievement ID: " +
                  get_achievement_id_from_ros_title_id(game_id) + ")...")
        # Now, we can begin getting the user's achievements for the specified game.
        achievement_id = get_achievement_id_from_ros_title_id(game_id)
        url = (f"https://scapi.rockstargames.com/achievements/awardedAchievements?title={achievement_id}&platform=pc&"
               f"rockstarId={self._http_client.get_rockstar_id()}")
        unlocked_achievements = await self._http_client.get_json_from_request_strict(url)
        if not str("achievements_" + achievement_id) in self._all_achievements_cache:
            # In order to prevent having to make an HTTP request for a game's entire achievement list, it would be
            # better to store it in a cache.
            log.debug("ROCKSTAR_MISSING_CACHE: The achievements list for " +
                      get_game_title_id_from_ros_title_id(game_id) + " is not in the persistent cache!")
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
            unlock_time = await self.get_unix_epoch_time_from_date(value["dateAchieved"])
            achievement_name = all_achievements[int(key) - 1]["name"]
            achievements_list.append(Achievement(unlock_time, achievement_num, achievement_name))
        return achievements_list

    async def update_achievements_cache(self, achievement_id):
        url = f"https://scapi.rockstargames.com/achievements/all?title={achievement_id}&platform=pc"
        all_achievements = await self._http_client.get_json_from_request_strict(url)
        self._all_achievements_cache[str("achievements_" + achievement_id)] = all_achievements["achievements"]
        log.debug("ROCKSTAR_ACHIEVEMENTS: Pushing achievements_" + achievement_id + " to persistent cache...")
        self.persistent_cache[str("achievements_" + achievement_id)] = pickle.dumps(
            all_achievements["achievements"]).hex()
        log.debug("ROCKSTAR_NEW_CACHE: " + self.persistent_cache[str("achievements_" + achievement_id)])
        self.push_cache()

    @staticmethod
    async def get_unix_epoch_time_from_date(date):
        year = int(date[0:4])
        month = int(date[5:7])
        day = int(date[8:10])
        hour = int(date[11:13])
        minute = int(date[14:16])
        second = int(date[17:19])
        return int(datetime.datetime(year, month, day, hour, minute, second).timestamp())

    async def get_friends(self):
        # NOTE: This will return a list of type FriendInfo.
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
        current_page = await self._http_client.get_json_from_request_strict(url)
        log.debug("ROCKSTAR_FRIENDS_REQUEST: " + str(current_page))
        num_friends = current_page['rockstarAccountList']['totalFriends']
        num_pages_required = num_friends / 30 if num_friends % 30 != 0 else (num_friends / 30) - 1

        # Now, we need to get the information about the friends.
        friends_list = current_page['rockstarAccountList']['rockstarAccounts']
        return_list = []
        for i in range(0, len(friends_list)):
            friend = FriendInfo(friends_list[i]['rockstarId'], friends_list[i]['displayName'])
            return_list.append(FriendInfo)
            for cached_friend in self.friends_cache:
                if cached_friend.user_id == friend.user_id:
                    break
            else:
                self.friends_cache.append(friend)
                self.add_friend(friend)
            log.debug("ROCKSTAR_FRIEND: Found " + friend.user_name + " (Rockstar ID: " +
                      str(friend.user_id) + ")")

        # The first page is finished, but now we need to work on any remaining pages.
        if num_pages_required > 0:
            for i in range(1, int(num_pages_required + 1)):
                url = ("https://scapi.rockstargames.com/friends/getFriendsFiltered?onlineService=sc&nickname=&"
                       "pageIndex=" + str(i) + "&pageSize=30")
                return_list.append(friend for friend in await self._get_friends(url))
        return return_list

    async def _get_friends(self, url):
        current_page = self._http_client.get_json_from_request_strict(url)
        friends_list = current_page['rockstarAccountList']['rockstarAccounts']
        return_list = []
        for i in range(0, len(friends_list)):
            friend = FriendInfo(friends_list[i]['rockstarId'], friends_list[i]['displayName'])
            return_list.append(FriendInfo)
            for cached_friend in self.friends_cache:
                if cached_friend.user_id == friend.user_id:
                    break
            else:  # An else-statement occurs after a for-statement if the latter finishes WITHOUT breaking.
                self.friends_cache.append(friend)
                self.add_friend(friend)
            log.debug("ROCKSTAR_FRIEND: Found " + friend.user_name + " (Rockstar ID: " +
                      str(friend.user_id) + ")")
        return return_list

    async def get_owned_games(self):
        # Here is the actual implementation of getting the user's owned games:
        # -Get the list of games_played from rockstargames.com/auth/get-user.json.
        #   -If possible, use the launcher log to confirm which games are actual launcher games and which are
        #   Steam/Retail games.
        #   -If it is not possible to use the launcher log, then just use the list provided by the website.
        if not self.is_authenticated():
            raise AuthenticationRequired()

        # Get the list of games_played from https://www.rockstargames.com/auth/get-user.json.
        owned_title_ids = []
        online_check_success = True
        try:
            played_games = await self._http_client.get_played_games()
            for game in played_games:
                title_id = get_game_title_id_from_online_title_id(game)
                owned_title_ids.append(title_id)
                log.debug("ROCKSTAR_ONLINE_GAME: Found played game " + title_id + "!")
        except Exception as e:
            log.error("ROCKSTAR_PLAYED_GAMES_ERROR: The exception " + repr(e) + " was thrown when attempting to get the"
                      " user's played games online. Falling back to log file check...")
            online_check_success = False

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
                log.debug("ROCKSTAR_LOG_LOCATION: Checking the file " + log_file + "...")
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
        remove_all = False
        if len(self.owned_games_cache) == 0:
            remove_all = True
        for title_id in owned_title_ids:
            game = self.create_game_from_title_id(title_id)
            if game not in self.owned_games_cache:
                log.debug("ROCKSTAR_ADD_GAME: Adding " + title_id + " to owned games cache...")
                self.add_game(game)
                self.owned_games_cache.append(game)
        if remove_all is True:
            for key, value in games_cache.items():
                if key not in owned_title_ids:
                    log.debug("ROCKSTAR_REMOVE_GAME: Removing " + key + " from owned games cache...")
                    self.remove_game(value['rosTitleId'])
        else:
            for game in self.owned_games_cache:
                if get_game_title_id_from_ros_title_id(game.game_id) not in owned_title_ids:
                    log.debug("ROCKSTAR_REMOVE_GAME: Removing " + get_game_title_id_from_ros_title_id(game.game_id) +
                              " from owned games cache...")
                    self.remove_game(game.game_id)
                    self.owned_games_cache.remove(game)
        return self.owned_games_cache

    @staticmethod
    async def parse_log_file(log_file, owned_title_ids, online_check_success):
        owned_title_ids_ = owned_title_ids
        checked_games_count = 0
        total_games_count = len(games_cache)
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

    if not IS_WINDOWS:
        async def get_local_games(self):
            # Since the API requires that get_local_games returns a list of LocalGame objects, local_list is the value that
            # needs to be returned. However, for internal use (the self.local_games_cache field), the dictionary local_games
            # is used for greater flexibility.
            local_games = {}
            local_list = []
            for game in self.total_games_cache:
                title_id = get_game_title_id_from_ros_title_id(str(game.game_id))
                check = self._local_client.get_path_to_game(title_id)
                if check is not None:
                    if (title_id in self.running_games_pids and
                            check_if_process_exists(self.running_games_pids[title_id][0])):
                        local_game = self.create_local_game_from_title_id(title_id, True, True)
                    else:
                        local_game = self.create_local_game_from_title_id(title_id, False, True)
                else:
                    local_game = self.create_local_game_from_title_id(title_id, False, False)
                local_games[title_id] = local_game
                local_list.append(local_game)
            self.local_games_cache = local_games
            log.debug("ROCKSTAR_INSTALLED_GAMES: " + str(local_games))
            return local_list

    async def check_for_new_games(self):
        self.checking_for_new_games = True
        await self.get_owned_games()
        await asyncio.sleep(60)
        self.checking_for_new_games = False

    async def check_game_statuses(self):
        self.updating_game_statuses = True
        old_local_game_cache = self.local_games_cache
        await self.get_local_games()
        for title_id, local_game in self.local_games_cache.items():
            if (local_game.local_game_state !=
                    (old_local_game_cache[title_id]).local_game_state):
                log.debug("ROCKSTAR_LOCAL_CHANGE: The status for " + title_id + " has changed.")
                self.update_local_game_status(local_game)
        #   else:
        #       log.debug("ROCKSTAR_LOCAL_REMAIN: The status for " + title_id + " has not changed.") - Reduce Console
        #       Spam (Enable this if you need to.)
        await asyncio.sleep(5)
        self.updating_game_statuses = False

    if IS_WINDOWS:
        async def launch_game(self, game_id):
            title_id = get_game_title_id_from_ros_title_id(game_id)
            self.running_games_pids[title_id] = [await self._local_client.launch_game_from_title_id(title_id), True]
            log.debug("ROCKSTAR_PIDS: " + str(self.running_games_pids))
            if self.running_games_pids[title_id][0] != '-1':
                self.update_local_game_status(LocalGame(game_id, LocalGameState.Running | LocalGameState.Installed))

    if IS_WINDOWS:
        async def install_game(self, game_id):
            title_id = get_game_title_id_from_ros_title_id(game_id)
            log.debug("ROCKSTAR_INSTALL_REQUEST: Requesting to install " + title_id + "...")
            self._local_client.install_game_from_title_id(title_id)
            # If the game is not released yet, then we should allow them to see this on the Rockstar Games Launcher, but the
            # game's installation status should not be changed.
            if games_cache[title_id]["isPreOrder"]:
                return
            self.update_local_game_status(LocalGame(game_id, LocalGameState.Installed))

    if IS_WINDOWS:
        async def uninstall_game(self, game_id):
            title_id = get_game_title_id_from_ros_title_id(game_id)
            log.debug("ROCKSTAR_UNINSTALL_REQUEST: Requesting to uninstall " + title_id + "...")
            self._local_client.uninstall_game_from_title_id(title_id)
            self.update_local_game_status(LocalGame(game_id, LocalGameState.None_))

    def create_game_from_title_id(self, title_id):
        return Game(self.games_cache[title_id]["rosTitleId"], self.games_cache[title_id]["friendlyName"], None,
                    self.games_cache[title_id]["licenseInfo"])

    def create_local_game_from_title_id(self, title_id, is_running, is_installed):
        if is_running:
            return LocalGame(self.games_cache[title_id]["rosTitleId"], LocalGameState.Running |
                             LocalGameState.Installed)
        elif is_installed:
            return LocalGame(self.games_cache[title_id]["rosTitleId"], LocalGameState.Installed)
        else:
            return LocalGame(self.games_cache[title_id]["rosTitleId"], LocalGameState.None_)

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
