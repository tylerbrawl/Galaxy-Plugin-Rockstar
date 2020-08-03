import datetime
import sys

from time import time

from galaxyutils.config_parser import Option, get_config_options


class NoLogFoundException(Exception):
    pass


class NoGamesInLogException(Exception):
    pass


ARE_ACHIEVEMENTS_IMPLEMENTED = True

CONFIG_OPTIONS = get_config_options([
    Option(option_name='user_presence_mode', default_value=0, allowed_values=[i for i in range(0, 4)]),
    Option(option_name='log_sensitive_data'),
    Option(option_name='debug_always_refresh'),
    Option(option_name='rockstar_launcher_path_override', str_option=True, default_value=None)
])

LOG_SENSITIVE_DATA = CONFIG_OPTIONS['log_sensitive_data']

MANIFEST_URL = r"https://gamedownloads-rockstargames-com.akamaized.net/public/title_metadata.json"

IS_WINDOWS = (sys.platform == 'win32')

ROCKSTAR_LAUNCHERPATCHER_EXE = "LauncherPatcher.exe"
ROCKSTAR_LAUNCHER_EXE = "Launcher.exe"  # It's a terribly generic name for a launcher.

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 "
              "Safari/537.36")

WINDOWS_UNINSTALL_KEY = "SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"

AUTH_PARAMS = {
    "window_title": "Login to Rockstar Games Social Club",
    "window_width": 700,
    "window_height": 600,
    "start_uri": "https://signin.rockstargames.com/signin/user-form?cid=rsg",
    "end_uri_regex": r"https://scapi.rockstargames.com/profile/getbasicprofile"
}


async def get_unix_epoch_time_from_date(date):
    year = int(date[0:4])
    month = int(date[5:7])
    day = int(date[8:10])
    hour = int(date[11:13])
    minute = int(date[14:16])
    second = int(date[17:19])
    return int(datetime.datetime(year, month, day, hour, minute, second).timestamp())


async def get_time_passed(old_time: int) -> str:
    current_time = int(time())
    difference = current_time - old_time
    days_passed = int(difference / (3600 * 24))
    if days_passed == 0:
        return "Today"
    elif days_passed >= 365:
        years_passed = int(days_passed / 365)
        return f"{years_passed} Years Ago" if years_passed != 1 else "1 Year Ago"
    elif days_passed >= 30:
        months_passed = int(days_passed / 30)
        return f"{months_passed} Months Ago" if months_passed != 1 else "1 Month Ago"
    elif days_passed >= 7:
        weeks_passed = int(days_passed / 7)
        return f"{weeks_passed} Weeks Ago" if weeks_passed != 1 else "1 Week Ago"
    return f"{days_passed} Days Ago" if days_passed != 1 else "1 Day Ago"
