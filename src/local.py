import os
from winreg import *
import logging as log
import subprocess
import asyncio
import locale

from galaxy.proc_tools import pids, ProcessId

from consts import WINDOWS_UNINSTALL_KEY
from game_cache import games_cache


def check_if_process_exists(pid):
    log.debug("ROCKSTAR_RUNNING_CHECK: Is " + str(ProcessId(pid)) + " in " + str(pids()) + "?")
    if not pid:
        log.debug("Nope.")
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
            log.debug("ROCKSTAR_INSTALLER_PATH: " + self.installer_location)
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
        if not path:
            log.error(f"ROCKSTAR_LAUNCH_FAILURE: The game {title_id} could not be launched.")
            return
        exe_name = games_cache[title_id]['launchEXE']
        game_path = path[:-3] + "\\" + exe_name + "\""
        log.debug(f"ROCKSTAR_LAUNCH_REQUEST: Requesting to launch {game_path}...")
        subprocess.Popen(game_path, stdout=self.FNULL, stderr=self.FNULL, shell=False)

        # The Rockstar Games Launcher can be painfully slow to boot up games, loop will be just fine
        retries = 60
        while retries > 0:
            await asyncio.sleep(1)
            pid = await self.game_pid_from_tasklist(title_id)
            if pid:
                return pid
            retries -= 1

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
