import os
from winreg import *
import logging as log
import subprocess
import asyncio

from consts import WINDOWS_UNINSTALL_KEY
from game_cache import games_cache


def check_if_process_exists(pid):
    if pid == '-1':
        return False
    process_status = (subprocess.check_output(f'tasklist /FI "PID eq {int(pid)}" /FI "STATUS eq running"').
                      decode("utf-8"))
    log.debug("ROCKSTAR_RUNNING_CHECK: Is " + str(pid) + " in " + process_status + "?")
    return str(pid) in process_status


class LocalClient:
    def __init__(self):
        self.root_reg = ConnectRegistry(None, HKEY_LOCAL_MACHINE)
        self.installer_location = None
        self.FNULL = open(os.devnull, 'w')
        self.get_local_launcher_path()

    def get_local_launcher_path(self):
        try:
            if not self.installer_location:
                # The uninstall key for the launcher is called Rockstar Games Launcher.
                key = OpenKey(self.root_reg, WINDOWS_UNINSTALL_KEY + "Rockstar Games Launcher")
                dir, type = QueryValueEx(key, "InstallLocation")
                self.installer_location = dir[:len(dir) - 1] + "\\Launcher.exe\""
                log.debug("ROCKSTAR_INSTALLER_PATH: " + self.installer_location)
            return self.installer_location
        except WindowsError:
            return None

    def get_path_to_game(self, title_id):
        try:
            key = OpenKey(self.root_reg, WINDOWS_UNINSTALL_KEY + games_cache[title_id]['guid'])
            dir, type = QueryValueEx(key, "InstallLocation")
            return dir
        except WindowsError:
            # log.debug("ROCKSTAR_GAME_NOT_INSTALLED: The game with ID " + title_id + " is not installed.") - Reduce
            # Console Spam (Enable this if you need to.)
            return None

    async def launch_game_from_title_id(self, title_id):

        path = self.get_path_to_game(title_id)
        if not path:
            log.error("ROCKSTAR_LAUNCH_FAILURE: The game " + title_id + " could not be launched.")
            return
        exe_name = games_cache[title_id]['launchEXE']
        game_path = path[:len(path) - 3] + "\\" + exe_name + "\""
        log.debug("ROCKSTAR_LAUNCH_REQUEST: Requesting to launch " + game_path + "...")
        game_process = subprocess.Popen(game_path, stdout=self.FNULL, stderr=self.FNULL, shell=False)
        await asyncio.sleep(30)  # The Rockstar Games Launcher can be painfully slow to boot up games, so there is a
        # 30-second buffer present before checking for the PID.
        find_actual_pid = subprocess.Popen(f'tasklist /FI "IMAGENAME eq ' + games_cache[title_id]["launchEXE"] +
                                           '" /FI "STATUS eq running" /FO LIST', stdout=subprocess.PIPE)
        pid = ""
        for line in find_actual_pid.stdout:
            new_line = str(line)
            if "PID" in new_line:
                for i in range(0, len(new_line)):
                    try:
                        num = int(new_line[i:i + 1])
                        pid += str(num)
                    except NameError and ValueError as e:
                        continue
        if pid == '':
            return '-1'
        else:
            return pid

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
