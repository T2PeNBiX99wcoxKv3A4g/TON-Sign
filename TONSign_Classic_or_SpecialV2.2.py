import argparse
import glob
import logging
import os
import time
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


class LanguageManager(object):
    language: str
    logger = logging.getLogger(NAME)
    language_dir = "Language"
    database: dict[str, dict] = {}

    # noinspection PyShadowingNames
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
        self.language = args.lang

    def get(self, text: str) -> str:
        if not self.language in self.database or not text in self.database[self.language]:
            return text
        return self.database[self.language][text]

    # noinspection PyShadowingNames
    def info(self, msg: str, *args: object):
        logger.info(self.get(msg), *args)

    # noinspection PyShadowingNames
    def warning(self, msg: str, *args: object):
        logger.warning(self.get(msg), *args)

    # noinspection PyShadowingNames
    def error(self, msg: str, *args: object):
        logger.error(self.get(msg), *args)


language_manager: LanguageManager


def find_latest_log(directory: str):
    log_files = glob.glob(os.path.join(directory, "*.txt"))
    if not log_files:
        language_manager.error("logging.no_log_file")
        return None

    latest_log = max(log_files, key=os.path.getmtime)
    language_manager.info("logging.current_log_running", latest_log)
    return latest_log


def classify_round(round_type: str):
    if round_type in exempt_rounds:
        return "Exempt"
    elif round_type in special_rounds:
        return "Special"
    elif round_type in classic_rounds:
        return "Classic"
    else:
        return None


def update_round_log(round_log: list, round_type: str):
    classification = classify_round(round_type)

    if classification == "Exempt":
        if len(round_log) >= 2:
            if round_log[-2:] == ["Classic", "Classic"]:
                classification = "Special"
            elif round_log[-2:] == ["Classic", "Special"]:
                classification = "Classic"
            elif round_log[-2:] == ["Special", "Classic"]:
                classification = "Special" if is_alternate_pattern(round_log, False) else "Classic"

    round_log.append(classification)

    if len(round_log) > 7:
        round_log.pop(0)


def is_alternate_pattern(round_log: list, bonus_flag: bool):
    special_count = sum(1 for round_type in round_log[-6:] if round_type == "Special")
    return special_count > 2 or bonus_flag


def predict_next_round(round_log: list, bonus_flag: bool):
    if len(round_log) < 2:
        return "Classic"

    if round_log[-2:] == ["Special", "Special"]:
        language_manager.info("logging.host_left_before")
        round_log.pop()

    if is_alternate_pattern(round_log, bonus_flag):
        return "Classic" if round_log[-1] == "Special" else "Special"
    else:
        return "Special" if round_log[-2:] == ["Classic", "Classic"] else "Classic"


def get_recent_rounds_log(round_log: list):
    return ", ".join(["C" if round_type == "Classic" else "S" for round_type in round_log])


# noinspection PyShadowingNames
def monitor_round_types(
        log_file: str, known_round_types: list, known_jp_round_types: list, osc_client: SimpleUDPClient
):
    round_log: list = []
    last_position = 0
    last_prediction: bool = False
    bonus_flag: bool = False

    while True:
        with open(log_file, "r", encoding="utf-8") as file:
            file.seek(last_position)
            lines = file.readlines()
            new_position = file.tell()

            for line in lines:
                if "BONUS ACTIVE!" in line:  # TERROR NIGHTS STRING
                    bonus_flag = True
                    language_manager.info("logging.think_terror_nights")

                if "OnMasterClientSwitched" in line:
                    language_manager.info("logging.host_just_left")
                    osc_client.send_message("/avatar/parameters/TON_Sign", True)
                    last_prediction = True

                if "Saving Avatar Data:" in line:
                    language_manager.info("logging.saving_avatar_data")
                    osc_client.send_message("/avatar/parameters/TON_Sign", last_prediction)

                if "Round type is" in line:
                    parts = line.split("Round type is")
                    if len(parts) > 1:
                        possible_round_type = parts[1].strip().split()[0:2]
                        possible_round_type = " ".join(possible_round_type)
                        possible_round_type_for_print = possible_round_type

                        if possible_round_type in known_jp_round_types:
                            possible_round_type = known_round_types[known_jp_round_types.index(possible_round_type)]

                        if possible_round_type in known_round_types:
                            update_round_log(round_log, possible_round_type)
                            language_manager.info("logging.new_round_started", possible_round_type_for_print)

                            prediction = predict_next_round(round_log, bonus_flag)
                            special_count = sum(1 for round_type in round_log if round_type == "Special")
                            recent_rounds_log = get_recent_rounds_log(round_log)

                            language_manager.info("logging.next_round_should_be", recent_rounds_log, prediction)

                            # Send OSC message
                            if prediction == "Special":
                                osc_client.send_message("/avatar/parameters/TON_Sign", True)
                                last_prediction = True
                            else:
                                osc_client.send_message("/avatar/parameters/TON_Sign", False)
                                last_prediction = False
            last_position = new_position

            # Disable the terror nights flag after 6 rounds (assume you have enough data at this point, lol, might still break if it's a new lobby tho sry)
            if len(round_log) >= 6:
                bonus_flag = False
        time.sleep(10)


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
        monitor_round_types(latest_log_file, round_types, jp_round_types, osc_client)
