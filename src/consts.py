import os
import sys

MANIFEST_URL = r"https://gamedownloads-rockstargames-com.akamaized.net/public/title_metadata.json"

PLUGIN_PATH_WINDOWS = os.getenv("LOCALAPPDATA") + "\\GOG.com\\Galaxy\\plugins\\installed\\Rockstar"
PLUGIN_HTML_PATH_WINDOWS = PLUGIN_PATH_WINDOWS + "\\RockstarFPGen.html"

PLUGIN_PATH_MAC = "${HOME}/Library/Application Support/GOG.com/Galaxy/plugins/installed/Rockstar"  # Is this right?
PLUGIN_HTML_PATH_MAC = PLUGIN_PATH_MAC + "\\RockstarFPGen.html"

ROCKSTAR_LAUNCHERPATCHER_EXE = "LauncherPatcher.exe"
ROCKSTAR_LAUNCHER_EXE = "Launcher.exe"  # It's a terribly generic name for a launcher.

OPERATING_SYSTEM = "Windows" if sys.platform == "win32" else "Mac"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/76.0.3809.132 "
              "Safari/537.36")

WINDOWS_UNINSTALL_KEY = "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"

AUTH_PARAMS = {
    "window_title": "Login to Rockstar Games Social Club",
    "window_width": 700,
    "window_height": 600,
    "start_uri": "https://tylerbrawl.github.io/Galaxy-Plugin-Rockstar/index.html",
    "end_uri_regex": r"https://www.rockstargames.com/auth/get-user.json.*"
}


class NoLogFoundException(Exception):
    pass


class NoGamesInLogException(Exception):
    pass
