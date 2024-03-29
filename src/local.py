from typing import Optional
from winreg import *
import logging as log
import subprocess
import asyncio

from galaxy.proc_tools import pids

from consts import WINDOWS_UNINSTALL_KEY, LOG_SENSITIVE_DATA, CONFIG_OPTIONS
from game_cache import games_cache


def check_if_process_exists(pid):
    if not pid:
        return False
    if int(pid) in pids():
        return True
    return False


class LocalClient:
    def __init__(self):
        self.root_reg = ConnectRegistry(None, HKEY_LOCAL_MACHINE)
        self.installer_location = None
        self.get_local_launcher_path()

    def get_local_launcher_path(self):
        try:
            if CONFIG_OPTIONS['rockstar_launcher_path_override']:
                self.installer_location = CONFIG_OPTIONS['rockstar_launcher_path_override']
                if LOG_SENSITIVE_DATA:
                    log.debug("ROCKSTAR_INSTALLER_PATH: " + self.installer_location)
                else:
                    log.debug("ROCKSTAR_INSTALLER_PATH: ***")
            else:
                # The uninstall key for the launcher is called Rockstar Games Launcher.
                key = OpenKey(self.root_reg, WINDOWS_UNINSTALL_KEY + "Rockstar Games Launcher")
                dir, type = QueryValueEx(key, "InstallLocation")
                self.installer_location = dir[:-1] + "\\Launcher.exe\""
                if LOG_SENSITIVE_DATA:
                    log.debug("ROCKSTAR_INSTALLER_PATH: " + self.installer_location)
                else:
                    log.debug("ROCKSTAR_INSTALLER_PATH: ***")
        except WindowsError:
            self.installer_location = None
        return self.installer_location

    async def kill_launcher(self):
        # The Launcher exits without displaying an error message if LauncherPatcher.exe is killed before Launcher.exe.
        subprocess.Popen("taskkill /im SocialClubHelper.exe")

    def get_path_to_game(self, title_id):
        try:
            key = OpenKey(self.root_reg, WINDOWS_UNINSTALL_KEY + games_cache[title_id]['guid'])
            dir, type = QueryValueEx(key, "InstallLocation")
            return dir
        except WindowsError:
            # log.debug("ROCKSTAR_GAME_NOT_INSTALLED: The game with ID " + title_id + " is not installed.") - Reduce
            # Console Spam (Enable this if you need to.)
            return None

    async def get_game_size_in_bytes(self, title_id) -> Optional[int]:
        path = self.get_path_to_game(title_id)
        # We will add quotes if they are not present already.
        if path[:1] != '"':
            path = f'"{path}"'
        find_game_size = subprocess.Popen(
            f'chcp 65001 & dir {path} /a /s /-c', stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        output, err = find_game_size.communicate()

        # The file size will be listed in the second-to-last line of the output.
        line_list = output.decode().splitlines()
        game_size_line = line_list[len(line_list) - 2]
        size = None
        if "bytes" in game_size_line:
            size = int([str(s) for s in game_size_line.split() if s.isdigit()][1])
        if size:
            log.debug(f"ROCKSTAR_GAME_SIZE: The size of {title_id} is {size} bytes.")
        else:
            log.warning(f"ROCKSTAR_GAME_SIZE_FAILURE: The size of {title_id} could not be determined!")
        return size

    async def game_pid_from_tasklist(self, title_id) -> str:
        pid = None
        tracked_key = "trackEXE" if "trackEXE" in games_cache[title_id] else "launchEXE"
        # When reading output from the Windows Command Prompt, it is a good idea to first set the code page to one that
        # is used by the application. In this case, "chcp 65001" is sent to change the code page to Unicode, which is
        # what Python uses. Changes to the code page in this manner are temporary, so it should be sent along with the
        # desired command in one call to subprocess.Popen() (such as by using "&"). The "shell" parameter must also be
        # set to "True."
        find_actual_pid = subprocess.Popen(
            f'chcp 65001 & tasklist /FI "IMAGENAME eq {games_cache[title_id][tracked_key]} " /FI "STATUS eq running" '
            f'/FO LIST', stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        output, err = find_actual_pid.communicate()

        for line in output.decode().splitlines():
            if "PID" in line:
                pid = [str(s) for s in line.split() if s.isdigit()][0]
                break
        return pid

    async def launch_game_from_title_id(self, title_id):
        path = self.get_path_to_game(title_id)
        path = path.replace('"', '').replace(',0', '')
        if not path:
            log.error(f"ROCKSTAR_LAUNCH_FAILURE: The game {title_id} could not be launched.")
            return
        game_path = f"{path}\\{games_cache[title_id]['launchEXE']}"
        log.debug(f"ROCKSTAR_LAUNCH_REQUEST: Requesting to launch {game_path}...")

        launch_params = "-launchTitleInFolder"
        if "cmdLineArgs" in games_cache[title_id]:
            launch_params += " " + games_cache[title_id]["cmdLineArgs"]

        subprocess.Popen([game_path, launch_params, path, "@commandline.txt"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, shell=False)
        launcher_pid = None
        retries = 120
        while not launcher_pid:
            await asyncio.sleep(1)
            launcher_pid = await self.game_pid_from_tasklist("launcher")
            retries -= 1
            if retries == 0:
                log.debug("ROCKSTAR_LAUNCHER_PID_FAILURE: The Rockstar Games Launcher took too long to launch!")
                return None
        log.debug(f"ROCKSTAR_LAUNCHER_PID: {launcher_pid}")

        # The Rockstar Games Launcher can be painfully slow to boot up games, loop will be just fine
        retries = 30
        while True:
            await asyncio.sleep(1)
            pid = await self.game_pid_from_tasklist(title_id)
            if pid:
                return pid
            retries -= 1
            if retries == 0:
                # If it has been this long and the game still has not launched, then it might be downloading an update.
                # We should refresh the retries counter if the Rockstar Games Launcher is still running; otherwise, we
                # return None.
                if await self.game_pid_from_tasklist("launcher"):
                    log.debug(f"ROCKSTAR_LAUNCH_WAITING: The game {title_id} has not launched yet, but the Rockstar "
                              f"Games Launcher is still running. Restarting the loop...")
                    retries += 30
                else:
                    return None

    def install_game_from_title_id(self, title_id):
        if not self.installer_location:
            return
        subprocess.call(self.installer_location + " -enableFullMode -install=" + title_id, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, shell=False)

    def uninstall_game_from_title_id(self, title_id):
        if not self.installer_location:
            return
        subprocess.call(self.installer_location + " -enableFullMode -uninstall=" + title_id, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, shell=False)
