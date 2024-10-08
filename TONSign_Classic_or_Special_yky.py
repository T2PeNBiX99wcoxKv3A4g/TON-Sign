import argparse
import glob
import logging
import os
import sys
import time
import traceback
from enum import Enum
from venv import logger

import pygetwindow as gw
import yaml
from pythonosc.udp_client import SimpleUDPClient

save_data: dict = {
    "last_log_file": ""
}

# Current round types in game
round_types: list = [
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

jp_round_types: list = [
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

exempt_rounds: list = [
    "Mystic Moon",
    "Twilight",
    "Solstice"
]

special_rounds: list = [
    "Fog",
    "Punished",
    "Sabotage",
    "Cracked",
    "Alternate",
    "Bloodbath",
    "Midnight",
    "8 Pages"
]

classic_rounds: list = [
    "Classic",
    "Blood Moon"
]

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
            if "en" in self.database and text in self.database["en"]:
                return self.database["en"][text]
            return text
        return self.database[self.language][text]

    def info(self, msg: str, *args: object) -> None:
        logger.info(self.get(msg), *args)

    def warning(self, msg: str, *args: object) -> None:
        logger.warning(self.get(msg), *args)

    def error(self, msg: str, *args: object) -> None:
        logger.error(self.get(msg), *args)

    def debug(self, msg: str, *args: object) -> None:
        logger.debug(self.get(msg), *args)

    def dbg(self, msg: str, *args: object) -> None:
        self.debug(msg, *args)


lm: LanguageManager


def find_latest_log(directory: str) -> str | None:
    log_files = glob.glob(os.path.join(directory, "*.txt"))
    if not log_files:
        lm.error("log.no_log_file")
        return None

    latest_log = max(log_files, key=os.path.getmtime)
    lm.info("log.current_log_running", latest_log)
    return latest_log


def classify_round(round_type: str) -> RoundType:
    if round_type in exempt_rounds:
        return RoundType.Exempt
    elif round_type in special_rounds:
        return RoundType.Special
    elif round_type in classic_rounds:
        return RoundType.Classic
    return RoundType.NIL


def update_round_log(round_log: list[RoundType], round_type: str) -> None:
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
        lm.info("log.host_left_before")
        round_log.pop()

    if is_alternate_pattern(round_log, bonus_flag):
        return RoundType.Classic if round_log[-1] == RoundType.Special else RoundType.Special
    else:
        return RoundType.Special if round_log[-2:] == [RoundType.Classic, RoundType.Classic] else RoundType.Classic


def get_recent_rounds_log(round_log: list[RoundType]) -> str:
    return ", ".join([lm.get(
        "log.recent_rounds_log_classic") if round_type == RoundType.Classic else lm.get(
        "log.recent_rounds_log_special") for round_type in round_log])


def check_vrchat_is_running() -> bool:
    return "VRChat" in gw.getAllTitles()


def check_vrchat_loop() -> None:
    temp: int = 0
    while True:
        if temp < 1:
            lm.info("log.waiting_vrchat")

        check = check_vrchat_is_running()
        lm.dbg(f"Check: {check}")

        if check:
            lm.info("log.vrchat_found")
            break

        temp += 1
        time.sleep(2)


# noinspection PyShadowingNames
def monitor_round_types(log_file: str, osc_client: SimpleUDPClient) -> None:
    round_log: list[RoundType] = []
    last_position: int = 0
    last_prediction: bool = False
    bonus_flag: bool = False

    while True:
        if not check_vrchat_is_running():
            lm.info("log.vrchat_not_found")
            break
        with open(log_file, "r", encoding="utf-8") as file:
            file.seek(last_position)
            lines = file.readlines()
            new_position = file.tell()

            for line in lines:
                if "BONUS ACTIVE!" in line:  # TERROR NIGHTS STRING
                    bonus_flag = True
                    lm.info("log.think_terror_nights")
                elif "OnMasterClientSwitched" in line:
                    lm.info("log.host_just_left")
                    osc_client.send_message("/avatar/parameters/TON_Sign", True)
                    lm.dbg("OnMasterClientSwitched: /avatar/parameters/TON_Sign %s", True)
                    last_prediction = True
                elif "Saving Avatar Data:" in line:
                    lm.info("log.saving_avatar_data")
                    osc_client.send_message("/avatar/parameters/TON_Sign", last_prediction)
                    lm.dbg("Saving Avatar Data: /avatar/parameters/TON_Sign %s", last_prediction)
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
                            lm.info("log.new_round_started", possible_round_type_for_print)

                            classic = lm.get("log.predict_next_round_classic")
                            special = lm.get("log.predict_next_round_special")
                            prediction = predict_next_round(round_log, bonus_flag)
                            # special_count = sum(1 for round_type in round_log if round_type == "Special")
                            recent_rounds_log = get_recent_rounds_log(round_log)

                            lm.info("log.next_round_should_be", recent_rounds_log,
                                    special if prediction == RoundType.Special else classic)

                            # Send OSC message
                            if prediction == RoundType.Special:
                                osc_client.send_message("/avatar/parameters/TON_Sign", True)
                                lm.dbg("Round type is: /avatar/parameters/TON_Sign %s", True)
                                last_prediction = True
                            else:
                                osc_client.send_message("/avatar/parameters/TON_Sign", False)
                                lm.dbg("Round type is: /avatar/parameters/TON_Sign %s", False)
                                last_prediction = False
            last_position = new_position

            # Disable the terror nights flag after 6 rounds (assume you have enough data at this point, lol, might still break if it's a new lobby tho sry)
            if len(round_log) >= 6:
                bonus_flag = False
        time.sleep(10)


def run_test():
    lm.info("log.test")


def exit_do():
    # dir_path = os.path.dirname(os.path.realpath(__file__))
    # 
    # with open(os.path.join(dir_path, "save.yml"), "w", encoding="utf-8") as save_file:
    #     yaml.dump(save_data, save_file, default_flow_style=False)
    lm.dbg("Exit!")
    sys.exit()


def load_save():
    global save_data
    try:
        dir_path = os.path.dirname(os.path.realpath(__file__))

        with open(os.path.join(dir_path, "save.yml"), "r", encoding="utf-8") as save_file:
            load_data: dict = yaml.safe_load(save_file)
            lm.dbg(f"Data: {load_data}, last_log_file: {load_data["last_log_file"]}")

            for data_key in save_data.keys():
                if not data_key in load_data:
                    continue
                save_data[data_key] = load_data[data_key]
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--lang', '-l', default="en", help="Select the Language.", type=str)
    parser.add_argument('--debug', help="Debug mode.", action="store_true")
    parser.add_argument('--test', help="Test mode. (For workflows)", action="store_true")
    args = parser.parse_args()
    lm: LanguageManager = LanguageManager(args)
    # load_save()

    while True:
        # noinspection PyBroadException
        try:
            # OSC setup
            ip = "127.0.0.1"
            port = 9000
            osc_client = SimpleUDPClient(ip, port)
            running_time: int = 0

            if args.test:
                run_test()
                sys.exit()

            while True:
                if not check_vrchat_is_running():
                    if running_time < 1:
                        running_time += 1
                    check_vrchat_loop()

                if running_time > 0:
                    lm.info("log.wait_until_join_game")
                    time.sleep(60)

                # Directory and file search UPDATED becuase some people's getlogin function EXPLODED so we're doing it this way now :3
                log_directory = os.path.join(os.path.expanduser("~"), "AppData", "LocalLow", "VRChat", "VRChat")
                latest_log_file = find_latest_log(log_directory)

                if latest_log_file:
                    monitor_round_types(latest_log_file, osc_client)
                    running_time += 1
                else:
                    break
        except KeyboardInterrupt:
            lm.info("log.exit")
            exit_do()
        except Exception:
            lm.error(traceback.format_exc())
