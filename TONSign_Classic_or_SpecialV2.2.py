import argparse
import glob
import logging
import os
import sys
import time
from enum import Enum
from venv import logger

import yaml
from pythonosc.udp_client import SimpleUDPClient

# Current round types in game
round_types = [
    "Classic",
    "Fog",
    "Punished",
    "Sabotage",
    "Cracked",
    "Alternate",
    "Bloodbath",
    "Midnight",
    "Mystic Moon",
    "Twilight",
    "Solstice",
    "8 Pages",
    "Blood Moon",
]

jp_round_types = [
    "クラシック",
    "霧",
    "パニッシュ",
    "サボタージュ",
    "狂気",
    "オルタネイト",
    "ブラッドバス",
    "ミッドナイト",
    "ミスティックムーン",
    "トワイライト",
    "ソルスティス",
    "8ページ",
    "ブラッドバス",
]

exempt_rounds = {"Mystic Moon", "Twilight", "Solstice"}
special_rounds = {"Fog", "Punished", "Sabotage", "Cracked", "Alternate", "Bloodbath", "Midnight", "8 Pages"}
classic_rounds = {"Classic", "Blood Moon"}

NAME = "TONSign_Classic_or_Special"


class RoundType(Enum):
    NIL = -1
    Exempt = 0
    Special = 1
    Classic = 2


class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    green = "\x1b[32;20m"
    blue = '\x1b[38;5;39m'
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    time = "[%(asctime)s]"
    level_name = "%(levelname)s"
    message = "%(message)s"

    FORMATS = {
        logging.DEBUG: f"{grey}{time}{reset} {blue}{level_name}{reset}: {blue}{message}{reset}",
        logging.INFO: f"{grey}{time}{reset} {green}{level_name}{reset}: {message}",
        logging.WARNING: f"{grey}{time}{reset} {yellow}{level_name}{reset}: {yellow}{message}{reset}",
        logging.ERROR: f"{red}{time}{reset} {red}{level_name}{reset}: {red}{message}{reset}",
        logging.CRITICAL: f"{bold_red}{time}{reset} {bold_red}{level_name}{reset}: {bold_red}{message}{reset}"
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


# noinspection PyShadowingNames
class LanguageManager(object):
    language: str
    logger = logging.getLogger(NAME)
    language_dir = "Language"
    database: dict[str, dict] = {}

    def __init__(self, args: argparse.Namespace):
        level = logging.DEBUG if args.debug else logging.INFO
        logger.setLevel(level)

        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(CustomFormatter())

        logger.addHandler(ch)

        dir_path = os.path.dirname(os.path.realpath(__file__))

        for file in glob.glob(os.path.join(dir_path, self.language_dir, "*.yml")):
            with open(file, 'r', encoding="utf-8") as yml:
                data = yaml.safe_load(yml)
                lang_id = os.path.basename(file).split('.')[0]
                self.database[lang_id] = data
                yml.close()
        self.language = str(args.lang).lower()

    def get(self, text: str) -> str:
        if not self.language in self.database or not text in self.database[self.language]:
            return text
        return self.database[self.language][text]

    def info(self, msg: str, *args: object):
        logger.info(self.get(msg), *args)

    def warning(self, msg: str, *args: object):
        logger.warning(self.get(msg), *args)

    def error(self, msg: str, *args: object):
        logger.error(self.get(msg), *args)

    def debug(self, msg: str, *args: object):
        logger.debug(self.get(msg), *args)

    def dbg(self, msg: str, *args: object):
        self.debug(msg, *args)


language_manager: LanguageManager


def find_latest_log(directory: str) -> str | None:
    log_files = glob.glob(os.path.join(directory, "*.txt"))
    if not log_files:
        language_manager.error("logging.no_log_file")
        return None

    latest_log = max(log_files, key=os.path.getmtime)
    language_manager.info("logging.current_log_running", latest_log)
    return latest_log


def classify_round(round_type: str) -> RoundType:
    if round_type in exempt_rounds:
        return RoundType.Exempt
    elif round_type in special_rounds:
        return RoundType.Special
    elif round_type in classic_rounds:
        return RoundType.Classic
    return RoundType.NIL


def update_round_log(round_log: list[RoundType], round_type: str):
    classification: RoundType = classify_round(round_type)

    if classification == RoundType.Exempt:
        if len(round_log) >= 2:
            if round_log[-2:] == [RoundType.Classic, RoundType.Classic]:
                classification = RoundType.Special
            elif round_log[-2:] == [RoundType.Classic, RoundType.Special]:
                classification = RoundType.Classic
            elif round_log[-2:] == [RoundType.Special, RoundType.Classic]:
                classification = RoundType.Special if is_alternate_pattern(round_log, False) else RoundType.Classic

    round_log.append(classification)

    if len(round_log) > 7:
        round_log.pop(0)


def is_alternate_pattern(round_log: list[RoundType], bonus_flag: bool) -> bool:
    special_count = sum(1 for round_type in round_log[-6:] if round_type == RoundType.Special)
    return special_count > 2 or bonus_flag


def predict_next_round(round_log: list[RoundType], bonus_flag: bool) -> RoundType:
    if len(round_log) < 2:
        return RoundType.Classic

    if round_log[-2:] == [RoundType.Special, RoundType.Special]:
        language_manager.info("logging.host_left_before")
        round_log.pop()

    if is_alternate_pattern(round_log, bonus_flag):
        return RoundType.Classic if round_log[-1] == RoundType.Special else RoundType.Special
    else:
        return RoundType.Special if round_log[-2:] == [RoundType.Classic, RoundType.Classic] else RoundType.Classic


def get_recent_rounds_log(round_log: list[RoundType]) -> str:
    return ", ".join([language_manager.get(
        "logging.recent_rounds_log_classic") if round_type == RoundType.Classic else language_manager.get(
        "logging.recent_rounds_log_special") for round_type in round_log])


# noinspection PyShadowingNames
def monitor_round_types(log_file: str, osc_client: SimpleUDPClient):
    round_log: list[RoundType] = []
    last_position: int = 0
    last_prediction: bool = False
    bonus_flag: bool = False

    while True:
        try:
            with open(log_file, "r", encoding="utf-8") as file:
                file.seek(last_position)
                lines = file.readlines()
                new_position = file.tell()

                for line in lines:
                    if "BONUS ACTIVE!" in line:  # TERROR NIGHTS STRING
                        bonus_flag = True
                        language_manager.info("logging.think_terror_nights")
                    elif "OnMasterClientSwitched" in line:
                        language_manager.info("logging.host_just_left")
                        osc_client.send_message("/avatar/parameters/TON_Sign", True)
                        language_manager.dbg("OnMasterClientSwitched: /avatar/parameters/TON_Sign %s", True)
                        last_prediction = True
                    elif "Saving Avatar Data:" in line:
                        language_manager.info("logging.saving_avatar_data")
                        osc_client.send_message("/avatar/parameters/TON_Sign", last_prediction)
                        language_manager.dbg("Saving Avatar Data: /avatar/parameters/TON_Sign %s", last_prediction)
                    elif "Round type is" in line:
                        parts = line.split("Round type is")
                        if len(parts) > 1:
                            possible_round_type = parts[1].strip().split()[0:2]
                            possible_round_type = " ".join(possible_round_type)
                            possible_round_type_for_print = possible_round_type

                            if possible_round_type in jp_round_types:
                                possible_round_type = round_types[jp_round_types.index(possible_round_type)]

                            if possible_round_type in round_types:
                                update_round_log(round_log, possible_round_type)
                                language_manager.info("logging.new_round_started", possible_round_type_for_print)

                                classic = language_manager.get("logging.predict_next_round_classic")
                                special = language_manager.get("logging.predict_next_round_special")
                                prediction = predict_next_round(round_log, bonus_flag)
                                # special_count = sum(1 for round_type in round_log if round_type == "Special")
                                recent_rounds_log = get_recent_rounds_log(round_log)

                                language_manager.info("logging.next_round_should_be", recent_rounds_log,
                                                      special if prediction == RoundType.Special else classic)

                                # Send OSC message
                                if prediction == RoundType.Special:
                                    osc_client.send_message("/avatar/parameters/TON_Sign", True)
                                    language_manager.dbg("Round type is: /avatar/parameters/TON_Sign %s", True)
                                    last_prediction = True
                                else:
                                    osc_client.send_message("/avatar/parameters/TON_Sign", False)
                                    language_manager.dbg("Round type is: /avatar/parameters/TON_Sign %s", False)
                                    last_prediction = False
                last_position = new_position

                # Disable the terror nights flag after 6 rounds (assume you have enough data at this point, lol, might still break if it's a new lobby tho sry)
                if len(round_log) >= 6:
                    bonus_flag = False
            time.sleep(10)
        except KeyboardInterrupt:
            language_manager.info("logging.exit")
            sys.exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--lang', '-l', default="en", help="Select the Language.", type=str)
    parser.add_argument('--debug', help="Debug mode.", action="store_true")
    args = parser.parse_args()
    language_manager = LanguageManager(args)

    # OSC setup
    ip = "127.0.0.1"
    port = 9000
    osc_client = SimpleUDPClient(ip, port)

    # Directory and file search UPDATED becuase some people's getlogin function EXPLODED so we're doing it this way now :3
    log_directory = os.path.join(os.path.expanduser("~"), "AppData", "LocalLow", "VRChat", "VRChat")
    latest_log_file = find_latest_log(log_directory)

    if latest_log_file:
        monitor_round_types(latest_log_file, osc_client)
