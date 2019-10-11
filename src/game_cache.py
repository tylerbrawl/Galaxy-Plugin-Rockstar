from galaxy.api.types import LicenseInfo
from galaxy.api.consts import LicenseType

# The onlineTitleId values are taken from https://www.rockstargames.com/games/get-games.json?sort=&direction=&family=&
# platform=pc.
#
# All other data values can be found from https://gamedownloads-rockstargames-com.akamaized.net/public/
# title_metadata.json.
games_cache = {
    "gtasa": {
        "friendlyName": "Grand Theft Auto: San Andreas",
        "guid": "Grand Theft Auto: San Andreas",
        "rosTitleId": 18,
        "onlineTitleId": 31,
        "launchEXE": "gta_sa.exe",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase)
    },
    "gta5": {
        "friendlyName": "Grand Theft Auto V",
        "guid": "{5EFC6C07-6B87-43FC-9524-F9E967241741}",
        "rosTitleId": 11,
        "onlineTitleId": 241,
        "launchEXE": "GTA5.exe",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase)
    },
    "lanoire": {
        "friendlyName": "L.A. Noire: Complete Edition",
        "guid": "{915726DF-7891-444A-AA03-0DF1D64F561A}",
        "rosTitleId": 9,
        "onlineTitleId": 35,
        "launchEXE": "LANoire.exe",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase)
    },
    "mp3": {
        "friendlyName": "Max Payne 3",
        "guid": "{1AA94747-3BF6-4237-9E1A-7B3067738FE1}",
        "rosTitleId": 10,
        "onlineTitleId": 40,
        "launchEXE": "MaxPayne3.exe",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase)
    },
    # "lanoirevr": {
    #    "friendlyName": "L.A. Noire: The VR Case Files",
    #    "guid": "L.A. Noire: The VR Case Files",
    #    "rosTitleId": 24,
    #    "onlineTitleId": 35,  # For some reason, this is the same as L.A. Noire's ID.
    #    "launchEXE": "LANoireVR.exe",
    #    "licenseInfo": LicenseInfo(LicenseType.SinglePurchase)
    # },
    "gta3": {
        "friendlyName": "Grand Theft Auto III",
        "guid": "Grand Theft Auto III",
        "rosTitleId": 26,
        "onlineTitleId": 24,
        "launchEXE": "gta3.exe",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase)
    },
    "gtavc": {
        "friendlyName": "Grand Theft Auto: Vice City",
        "guid": "Grand Theft Auto: Vice City",
        "rosTitleId": 27,
        "onlineTitleId": 33,
        "launchEXE": "gta-vc.exe",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase)
    },
    "bully": {
        "friendlyName": "Bully: Scholarship Edition",
        "guid": "Bully: Scholarship Edition",
        "rosTitleId": 23,
        "onlineTitleId": 19,
        "launchEXE": "Bully.exe",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase)
    },
    "rdr2": {
        "friendlyName": "Red Dead Redemption 2",
        "guid": "[Missing]",  # Update this value from the Rockstar Games Launcher as soon as possible.
        "rosTitleId": 13,
        "onlineTitleId": 912,
        "launchEXE": "RDR2.exe",
        "licenseInfo": LicenseInfo(LicenseType.SinglePurchase),
        "isPreOrder": True
    }
}


def get_game_title_id_from_ros_title_id(ros_title_id):
    # The rosTitleId value is used by the Rockstar Games Launcher to uniquely identify the games that it supports.
    # For some reason, Rockstar made these values different from the internal numerical IDs for the same games on their
    # website (which are listed here as the onlineTitleId value).
    for game, d in games_cache.items():
        if d["rosTitleId"] == int(ros_title_id):
            return game
    return None

    # switch = {
    #    '18': "gtasa",
    #    '11': "gta5",
    #    '9': "lanoire",
    #    '10': "mp3",
    #   #24: "lanoirevr",
    #    '26': "gta3",
    #    '27': "gtavc",
    #    '23': "bully"
    # }
    # return switch[rosTitleId]


def get_game_title_id_from_online_title_id(online_title_id):
    # The onlineTitleId value is used to uniquely identify each game across Rockstar's various websites, including
    # https://www.rockstargames.com/auth/get-user.json. These values seem to have no use within the Rockstar Games
    # Launcher.
    for game, d in games_cache.items():
        if d["onlineTitleId"] == int(online_title_id):
            return game
    return None
