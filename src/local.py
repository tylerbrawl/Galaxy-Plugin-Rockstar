import os
from winreg import *
import logging as log
import subprocess
import asyncio
import locale

from galaxy.proc_tools import pids

from consts import WINDOWS_UNINSTALL_KEY, LOG_SENSITIVE_DATA
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
        self.FNULL = open(os.devnull, 'w')
        self.get_local_launcher_path()

    def get_local_launcher_path(self):
        try:
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

    def get_path_to_game(self, title_id):
        try:
            key = OpenKey(self.root_reg, WINDOWS_UNINSTALL_KEY + games_cache[title_id]['guid'])
            dir, type = QueryValueEx(key, "InstallLocation")
            return dir
        except WindowsError:
            # log.debug("ROCKSTAR_GAME_NOT_INSTALLED: The game with ID " + title_id + " is not installed.") - Reduce
            # Console Spam (Enable this if you need to.)
            return None

    async def game_pid_from_tasklist(self, title_id) -> str:
        pid = None
        find_actual_pid = subprocess.Popen(
            f'tasklist /FI "IMAGENAME eq {games_cache[title_id]["launchEXE"]} " /FI "STATUS eq running" /FO LIST',
            stdout=subprocess.PIPE)

        for line in find_actual_pid.stdout:
            new_line = line.decode(locale.getpreferredencoding())
            if "PID" in new_line:
                pid = [str(s) for s in new_line.split() if s.isdigit()][0]
                break
        return pid

    async def launch_game_from_title_id(self, title_id):
        path = self.get_path_to_game(title_id)
        path = path[:path.rindex('"')]
        if not path:
            log.error(f"ROCKSTAR_LAUNCH_FAILURE: The game {title_id} could not be launched.")
            return

        '''The old method below for launching games has been deprecated with the release of RDR 2.
        exe_name = games_cache[title_id]['launchEXE']
        game_path = path[:path.rindex('"')] + "\\" + exe_name + "\""
        log.debug(f"ROCKSTAR_LAUNCH_REQUEST: Requesting to launch {game_path}...")
        subprocess.Popen(game_path, stdout=self.FNULL, stderr=self.FNULL, shell=False)
        '''

        log.debug(f"ROCKSTAR_LAUNCH_REQUEST: Requesting to launch {path}\\{games_cache[title_id]['launchEXE']}...")
        subprocess.call(self.installer_location + " -launchTitleInFolder=" + path, stdout=self.FNULL, stderr=self.FNULL,
                        shell=False)
        launcher_pid = None
        while not launcher_pid:
            await asyncio.sleep(1)
            launcher_pid = await self.game_pid_from_tasklist("launcher")
        log.debug(f"ROCKSTAR_LAUNCHER_PATCHER_PID: {launcher_pid}")

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
                if check_if_process_exists(launcher_pid):
                    log.debug(f"ROCKSTAR_LAUNCH_WAITING: The game {title_id} has not launched yet, but the Rockstar "
                              f"Games Launcher is still running. Restarting the loop...")
                    retries += 30
                else:
                    return None

    def install_game_from_title_id(self, title_id):
        if not self.installer_location:
            return
        subprocess.call(self.installer_location + " -enableFullMode -install=" + title_id, stdout=self.FNULL,
                        stderr=self.FNULL, shell=False)

    def uninstall_game_from_title_id(self, title_id):
        if not self.installer_location:
            return
        subprocess.call(self.installer_location + " -enableFullMode -uninstall=" + title_id, stdout=self.FNULL,
                        stderr=self.FNULL, shell=False)
