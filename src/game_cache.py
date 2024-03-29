from galaxy.api.types import LicenseInfo
from galaxy.api.consts import LicenseType

# The onlineTitleId values are taken from https://www.rockstargames.com/games/get-games.json?sort=&direction=&family=&
# platform=pc.
#
# All other data values can be found from https://gamedownloads-rockstargames-com.akamaized.net/public/
# title_metadata.json.
games_cache = {
    "launcher": {
        "friendlyName": "Rockstar Games Launcher",
        "guid": "Rockstar Games Launcher",
        "rosTitleId": 21,
        "onlineTitleId": None,
        "googleTagId": "Launcher_PC",
        "launchEXE": "Launcher.exe",
        "achievementId": None,
        "licenseInfo": LicenseInfo(LicenseType.Unknown),
        "isPreOrder": False
    },
    "gtasa": {
        "friendlyName": "Grand Theft Auto: San Andreas",
        "guid": "{D417C96A-FCC7-4590-A1BB-FAF73F5BC98E}",
        "rosTitleId": 18,
        "onlineTitleId": 31,
        "googleTagId": "GTASA_PC",
        "launchEXE": "gta_sa.exe",
        "achievementId": None,
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "gta5": {
        "friendlyName": "Grand Theft Auto V",
        "guid": "{5EFC6C07-6B87-43FC-9524-F9E967241741}",
        "rosTitleId": 11,
        "onlineTitleId": 241,
        "googleTagId": "GTAV_PC",
        "launchEXE": "PlayGTAV.exe",
        "trackEXE": "GTA5.exe",  # This value is for games that require the launch of multiple executables. So far,
        # Grand Theft Auto V seems to be the only game that requires this.
        "achievementId": "gtav",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "lanoire": {
        "friendlyName": "L.A. Noire: Complete Edition",
        "guid": "{915726DF-7891-444A-AA03-0DF1D64F561A}",
        "rosTitleId": 9,
        "onlineTitleId": 35,
        "googleTagId": "LAN_PC",
        "launchEXE": "LANoire.exe",
        "achievementId": "lan",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "mp3": {
        "friendlyName": "Max Payne 3",
        "guid": "{1AA94747-3BF6-4237-9E1A-7B3067738FE1}",
        "rosTitleId": 10,
        "onlineTitleId": 40,
        "googleTagId": "MP3_PC",
        "launchEXE": "MaxPayne3.exe",
        "achievementId": "mp3",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    # "lanoirevr": {
    #    "friendlyName": "L.A. Noire: The VR Case Files",
    #    "guid": "L.A. Noire: The VR Case Files",
    #    "rosTitleId": 24,
    #    "onlineTitleId": 35,  # For some reason, this is the same as L.A. Noire's ID.
    #    "googleTagId": "LANVR_PC",
    #    "launchEXE": "LANoireVR.exe",
    #    "achievementId": "lanvr",
    #    "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
    #    "isPreOrder": False
    # },
    "gta3": {
        "friendlyName": "Grand Theft Auto III",
        "guid": "{92B94569-6683-4617-8C54-EB27A1B51B30}",
        "rosTitleId": 26,
        "onlineTitleId": 24,
        "googleTagId": "GTAIII_PC",
        "launchEXE": "gta3.exe",
        "achievementId": None,
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "gtavc": {
        "friendlyName": "Grand Theft Auto: Vice City",
        "guid": "{4B35F00C-E63D-40DC-9839-DF15A33EAC46}",
        "rosTitleId": 27,
        "onlineTitleId": 33,
        "googleTagId": "GTAVC_PC",
        "launchEXE": "gta-vc.exe",
        "achievementId": None,
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "bully": {
        "friendlyName": "Bully: Scholarship Edition",
        "guid": "{A724605D-B399-4304-B8C7-33B3EF7D4677}",
        "rosTitleId": 23,
        "onlineTitleId": 19,
        "googleTagId": "Bully_PC",
        "launchEXE": "Bully.exe",
        "achievementId": None,  # The Social Club website lists Bully as having achievements, but it is only for the
        # mobile version of the game.
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "rdr2": {
        "friendlyName": "Red Dead Redemption 2",
        "guid": "Red Dead Redemption 2",
        "rosTitleId": 13,
        "onlineTitleId": 912,
        "googleTagId": "RDR2_PC",
        "launchEXE": "RDR2.exe",
        "achievementId": "rdr2",  # The achievements link for Red Dead Redemption 2 is currently unavailable, as the
        # game has not been released yet.
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "gta4": {
        "friendlyName": "Grand Theft Auto IV",
        "guid": "Grand Theft Auto IV",
        "rosTitleId": 1,
        "onlineTitleId": 25,
        "googleTagId": "GTAIV_PC",
        "launchEXE": "GTAIV.exe",
        "achievementId": "gtaiv",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "gta3unreal": {
        "friendlyName": "Grand Theft Auto III - The Definitive Edition",
        "guid": "GTA III - Definitive Edition",
        "rosTitleId": 28,
        "googleTagId": "GTA3UNREAL_PC",
        "launchEXE": "Gameface\\Binaries\\Win64\\LibertyCity.exe",
        "trackEXE": "LibertyCity.exe",
        "cmdLineArgs": "-scCommerceProvider=4",
        "achievementId": "gta3unreal",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "gtavcunreal": {
        "friendlyName": "Grand Theft Auto: Vice City - The Definitive Edition",
        "guid": "GTA Vice City - Definitive Edition",
        "rosTitleId": 29,
        "googleTagId": "GTAVCUNREAL_PC",
        "launchEXE": "Gameface\\Binaries\\Win64\\ViceCity.exe",
        "trackEXE": "ViceCity.exe",
        "cmdLineArgs": "-scCommerceProvider=4",
        "achievementId": "gtavcunreal",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    },
    "gtasaunreal": {
        "friendlyName": "Grand Theft Auto: San Andreas - The Definitive Edition",
        "guid": "GTA San Andreas - Definitive Edition",
        "rosTitleId": 30,
        "googleTagId": "GTASAUNREAL_PC",
        "launchEXE": "Gameface\\Binaries\\Win64\\SanAndreas.exe",
        "trackEXE": "SanAndreas.exe",
        "cmdLineArgs": "-scCommerceProvider=4",
        "achievementId": "gtasaunreal",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": False
    }
}

# Typically, we will ignore games from the metadata JSON (see the links in the documentation above games_cache) which
# have a "parentApp" field. These don't get listed in the Rockstar Games Launcher as programs which can be launched.
ignore_game_title_ids_list = [
    "rdr2_sp_steam",   # Red Dead Redemption 2 Single Player - Steam
    "rdr2_sp_rgl",     # Red Dead Redemption 2 Single Player - Rockstar Games Launcher
    "rdr2_sp",         # Red Dead Redemption 2 Single Player - General
    "rdr2_rdo",        # Red Dead Online Standalone
    "rdr2_sp_epic",    # Red Dead Redemption 2 Single Player - Epic Games Store
    "gtatrilogy"       # Grand Theft Auto: The Definitive Trilogy
]


def get_game_title_id_from_ros_title_id(ros_title_id):
    # The rosTitleId value is used by the Rockstar Games Launcher to uniquely identify the games that it supports.
    # For some reason, Rockstar made these values different from the internal numerical IDs for the same games on their
    # website (which are listed here as the onlineTitleId value).
    for game, d in games_cache.items():
        if d["rosTitleId"] == int(ros_title_id):
            return game
    return None


def get_game_title_id_from_online_title_id(online_title_id):
    # The onlineTitleId value is used to uniquely identify each game across Rockstar's various websites, including
    # https://www.rockstargames.com/auth/get-user.json. These values seem to have no use within the Rockstar Games
    # Launcher.
    for game, d in games_cache.items():
        if d["onlineTitleId"] == int(online_title_id):
            return game
    return None


def get_game_title_id_from_google_tag_id(google_tag_id):
    # The Google Tag Manager setup data contains a list of the Social Club user's played games as a string. The values
    # present in the string differ from other forms of identifiers on Rockstar's websites in that it describes the
    # game's title, and is not just a numeric ID.
    for game, d in games_cache.items():
        if 'googleTagId' in d and d['googleTagId'] == google_tag_id:
            return game
    return None


def get_game_title_id_from_ugc_title_id(ugc_id):
    # The ugc ID for a game seems to be related to the Google Tag ID of the game, although this could be wrong.
    for game, d in games_cache.items():
        if 'googleTagId' in d and d['googleTagId'].lower() == ugc_id.lower():
            return game
    return None


def get_achievement_id_from_ros_title_id(ros_title_id):
    # The achievementId value is used by the Social Club API to uniquely identify games. Here, it is used to get the
    # list of a game's achievements, as well as a user's unlocked achievements.
    for game, d in games_cache.items():
        if d["rosTitleId"] == int(ros_title_id):
            return games_cache[game]["achievementId"]
