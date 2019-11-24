from dataclasses import dataclass
from galaxy.api.errors import BackendError

import logging as log
import os


@dataclass
class Option(object):
    _option_name = None
    _current_value = None
    _default_value = None
    _allowed_values = []

    def create_option(self, option_name, default, allowed=None):
        self._option_name = option_name
        self._current_value = default
        self._default_value = default
        if not allowed:
            self._allowed_values = [True, False]
        else:
            self._allowed_values = allowed

    def get(self):
        return self._current_value

    def set(self, desired_value):
        for val in self._allowed_values:
            if str(desired_value) == str(val):
                self._current_value = val
                break

    def reset(self):
        self._current_value = self._default_value

    def get_default(self):
        return self._default_value


CONFIG_OPTIONS_INFO = {
    'user_presence_mode': {
        'default_value': 1,
        'allowed_values': [i for i in range(0, 4)]
    },
    'log_sensitive_data': {
        'default_value': False
    },
    'debug_always_refresh': {
        'default_value': False
    }
}

CONFIG_PATH = os.path.join(os.path.abspath(__file__), '..', 'config.cfg')

DEFAULT_CONFIG_PATH = os.path.join(os.path.abspath(__file__), '..', 'default_config.cfg')


def init_config_options(callback=False):
    if not callback:
        try:
            return _parse_config(open(CONFIG_PATH, "r"))
        except FileNotFoundError:
            log.warning("ROCKSTAR_CONFIG_MISSING: The config.cfg file could not be found in the root of the directory!")
            try:
                copy_default_config()
                init_config_options(callback=True)
            except FileNotFoundError:
                log.error("ROCKSTAR_DEFAULT_CONFIG_MISSING: The default_config.cfg file could not be found in the root "
                          "of the directory! Closing the plugin...")
                raise BackendError
            except Exception as e:
                log.exception("ROCKSTAR_DEFAULT_COPY_ERROR: Attempting to copy the default_config.cfg file to a new "
                              f"config.cfg resulted in this exception: {repr(e)}.")
                raise BackendError
        except Exception as e:
            log.exception(f"ROCKSTAR_READ_CONFIG_ERROR: The exception {repr(e)} was thrown while attempting to read the"
                          f" existing config.cfg file.")
            raise BackendError
    else:
        try:
            return _parse_config(open(CONFIG_PATH, "r"))
        except Exception as e:
            log.exception(f"ROCKSTAR_READ_CONFIG_CALLBACK_ERROR: Attempting to read the config.cfg file resulted in "
                          f"the exception {repr(e)} even after the default_config.cfg file was replicated. Closing the"
                          f" plugin...")
            raise BackendError


def copy_default_config():
    default_config = open(DEFAULT_CONFIG_PATH, 'r')
    config = open(CONFIG_PATH, 'w+')
    escaped_default_strings = False
    for line in default_config:
        if not escaped_default_strings:
            if line[:2] == "##":
                continue
            if line not in ['\r\n', '\n']:
                config.write(line)
                escaped_default_strings = True
        else:
            if line[:2] == "##":
                escaped_default_strings = False
                continue
            config.write(line)
    default_config.close()
    config.close()


def _parse_config(config):
    options_dict = {}
    for key in CONFIG_OPTIONS_INFO:
        options_dict[key] = Option()
        if "allowed_values" in CONFIG_OPTIONS_INFO[key]:
            options_dict[key].create_option(key, CONFIG_OPTIONS_INFO[key]['default_value'],
                                            CONFIG_OPTIONS_INFO[key]['allowed_values'])
        else:
            options_dict[key].create_option(key, CONFIG_OPTIONS_INFO[key]['default_value'])
    for line in config:
        if line[:1] == "#" or line in ['\r\n', '\n']:
            continue
        option = line.strip().split("=")
        if option[0] in CONFIG_OPTIONS_INFO:
            options_dict[option[0]].set(option[1])
            if options_dict[option[0]].get() != options_dict[option[0]].get_default():
                log.debug(f"ROCKSTAR_CONFIG_OPTION: The option {option[0]} is now set to {option[1]} instead of "
                          f"{CONFIG_OPTIONS_INFO[option[0]]['default_value']}.")
        else:
            log.debug(f"ROCKSTAR_FAKE_CONFIG_OPTION: The option {option[0]} is not a defined option!")
    config.close()
    return options_dict


class NoSuchConfigOptionException(Exception):
    pass


class InvalidConfigOptionException(Exception):
    pass
