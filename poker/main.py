import datetime
import logging.handlers
import os
import sys
import threading
import time
import warnings
from sys import platform
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from PyQt6 import QtGui, QtWidgets

from poker.restapi_local import local_restapi
from poker.tools import constants as const

if platform not in ["linux", "linux2"]:
    matplotlib.use('QtAgg')

from poker.decisionmaker.current_hand_memory import (CurrentHandPreflopState,
                                                     History)
from poker.decisionmaker.decisionmaker_gto import Decision
from poker.decisionmaker.montecarlo_python import run_montecarlo_wrapper
from poker.gui.action_and_signals import StrategyHandler, UIActionAndSignals
from poker.gui.gui_launcher import UiPokerbot
from poker.scraper.table_screen_based import TableScreenBased
from poker.tools.game_logger import GameLogger
from poker.tools.helper import init_logger, get_config, get_dir
from poker.tools.mongo_manager import MongoManager
from poker.tools.mouse_mover import MouseMoverTableBased
from poker.tools.screen_operations import take_screenshot
from poker.tools.update_checker import UpdateChecker

# pylint: disable=no-member,simplifiable-if-expression,protected-access,line-too-long,use-fstring-for-concatenation,refactoring:missing-module-dosctring,

warnings.filterwarnings("ignore", category=matplotlib.MatplotlibDeprecationWarning)
warnings.filterwarnings("ignore", message="ignoring `maxfev` argument to `Minimizer()`. Use `max_nfev` instead.")
warnings.filterwarnings("ignore", message="DataFrame columns are not unique, some columns will be omitted.")
warnings.filterwarnings("ignore", message="All-NaN axis encountered")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

version = 6.76
ui = None
ROOT = Path(__file__).resolve().parents[1]
LEGACY_ARCHIVED_MESSAGE = (
    "Le runtime V1 sous poker/ est archive. Le chemin canonique est maintenant src/main.py. "
    "Definis POKER_USE_LEGACY=1 uniquement pour forcer le mode heritage."
)


class ThreadManager(threading.Thread):
    def __init__(self, threadID, name, counter, gui_signals, updater):
        threading.Thread.__init__(self)
        self.threadID = threadID
        self.gui_signals = gui_signals
        self.updater = updater
        self.name = name
        self.counter = counter
        self.loger = logging.getLogger('main')

        self.game_logger = GameLogger()
        self.last_drift_check_at = 0.0
        self.session_start = time.time()
        self.tilt_hands_remaining = 0
        self.last_round_funds = None

    @staticmethod
    def capture_runtime_screenshot(control_mode):
        return take_screenshot(virtual_box=control_mode != 'Direct mouse control')

    @staticmethod
    def normalize_runtime_mode(value):
        runtime_mode = str(value or 'auto').strip().lower()
        if runtime_mode not in {'auto', 'observe', 'play'}:
            return 'auto'
        return runtime_mode

    def get_requested_runtime_mode(self):
        config = get_config()
        return self.normalize_runtime_mode(config.config.get('main', 'run_mode', fallback='auto'))

    def emit_runtime_status_once(self, status_text):
        if self.gui_signals.current_status_text != status_text:
            self.gui_signals.signal_status.emit(status_text)

    def emit_runtime_wait_status(self, requested_mode, hero_cards_found):
        language = self.gui_signals.current_language
        if requested_mode == 'observe':
            status_text = (
                "Mode observation : table detectee, aucune action executee"
                if language == 'fr'
                else "Observation mode: table detected, no action will be taken"
            )
        elif requested_mode == 'play':
            status_text = (
                "Mode jouer : attente d'une main jouable"
                if not hero_cards_found and language == 'fr'
                else "Play mode: waiting for a playable hand"
                if not hero_cards_found
                else "Mode jouer : attente de ton tour"
                if language == 'fr'
                else "Play mode: waiting for your turn"
            )
        else:
            status_text = (
                "Mode auto : observation de table, attente d'une main jouable"
                if not hero_cards_found and language == 'fr'
                else "Auto mode: observing table, waiting for a playable hand"
                if not hero_cards_found
                else "Mode auto : main detectee, attente de ton tour"
                if language == 'fr'
                else "Auto mode: hand detected, waiting for your turn"
            )

        self.emit_runtime_status_once(status_text)

    def emit_non_live_action_status(self, requested_mode, mouse_target):
        language = self.gui_signals.current_language
        if mouse_target is None:
            if requested_mode == 'observe':
                status_text = (
                    "Mode observation : spot observe, aucune action automatique"
                    if language == 'fr'
                    else "Observation mode: spot observed, no automatic action"
                )
            elif requested_mode == 'play':
                status_text = (
                    "Mode jouer : decision bloquee, aucune action live"
                    if language == 'fr'
                    else "Play mode: decision blocked, no live action taken"
                )
            else:
                status_text = (
                    "Mode auto : spot detecte mais decision bloquee"
                    if language == 'fr'
                    else "Auto mode: spot detected but decision is blocked"
                )
        else:
            status_text = (
                "Mode observation : recommandation uniquement, joue cette main toi-meme"
                if language == 'fr'
                else "Observation mode: recommendation only, play this hand yourself"
            )

        self.emit_runtime_status_once(status_text)
        return status_text

    def update_most_gui_items(self, preflop_state, p, m, t, d, h, gui_signals):
        try:
            sheet_name = t.preflop_sheet_name
        except:
            sheet_name = ''
        gui_signals.signal_decision.emit(str(d.decision + " " + sheet_name))
        gui_signals.signal_status.emit(d.decision)
        range2 = ''
        if hasattr(t, 'reverse_sheet_name'):
            _range = t.reverse_sheet_name
            if hasattr(preflop_state, 'range_column_name'):
                range2 = " " + preflop_state.range_column_name + ""

        else:
            _range = str(m.opponent_range)
        if _range == '1':
            _range = 'All cards'

        if t.gameStage != 'PreFlop' and p.selected_strategy['preflop_override']:
            sheet_name = preflop_state.preflop_sheet_name

        gui_signals.signal_label_number_update.emit('equity', str(np.round(t.abs_equity * 100, 2)) + "%")
        gui_signals.signal_label_number_update.emit('required_minbet', str(np.round(t.minBet, 2)))
        gui_signals.signal_label_number_update.emit('required_mincall', str(np.round(t.minCall, 2)))
        # gui_signals.signal_lcd_number_update.emit('potsize', t.totalPotValue)
        gui_signals.signal_label_number_update.emit('gamenumber',
                                                    str(int(self.game_logger.get_game_count(p.current_strategy))))
        gui_signals.signal_label_number_update.emit('assumed_players', str(int(t.assumedPlayers)))
        gui_signals.signal_label_number_update.emit('calllimit', str(np.round(d.finalCallLimit, 2)))
        gui_signals.signal_label_number_update.emit('betlimit', str(np.round(d.finalBetLimit, 2)))
        gui_signals.signal_label_number_update.emit('runs', str(int(m.runs)))
        gui_signals.signal_label_number_update.emit('sheetname', sheet_name)
        gui_signals.signal_label_number_update.emit('collusion_cards', str(m.collusion_cards))
        gui_signals.signal_label_number_update.emit('mycards', str(t.mycards))
        gui_signals.signal_label_number_update.emit('tablecards', str(t.cardsOnTable))
        gui_signals.signal_label_number_update.emit('opponent_range', str(_range) + str(range2))
        gui_signals.signal_label_number_update.emit('mincallequity', str(np.round(t.minEquityCall*100, 2)) + "%")
        gui_signals.signal_label_number_update.emit('minbetequity', str(np.round(t.minEquityBet*100, 2)) + "%")
        gui_signals.signal_label_number_update.emit('outs', str(d.outs))
        gui_signals.signal_label_number_update.emit('initiative', str(t.other_player_has_initiative))
        gui_signals.signal_label_number_update.emit('round_pot', str(np.round(t.round_pot_value, 2)))
        gui_signals.signal_label_number_update.emit('pot_multiple', str(np.round(d.pot_multiple, 2)))

        if t.gameStage != 'PreFlop' and p.selected_strategy['use_relative_equity']:
            gui_signals.signal_label_number_update.emit('relative_equity',
                                                        str(np.round(t.relative_equity, 2) * 100) + "%")
            gui_signals.signal_label_number_update.emit('range_equity', str(np.round(t.range_equity, 2) * 100) + "%")
        else:
            gui_signals.signal_label_number_update.emit('relative_equity', "")
            gui_signals.signal_label_number_update.emit('range_equity', "")

        # gui_signals.signal_lcd_number_update.emit('zero_ev', round(d.maxCallEV, 2))

        gui_signals.signal_pie_chart_update.emit(t.winnerCardTypeList)
        gui_signals.signal_curve_chart_update1.emit(h.histEquity, h.histMinCall, h.histMinBet, t.equity,
                                                    t.minCall, t.minBet,
                                                    'bo',
                                                    'ro')

        gui_signals.signal_curve_chart_update2.emit(t.power1, t.power2, t.minEquityCall, t.minEquityBet,
                                                    t.smallBlind, t.bigBlind,
                                                    t.maxValue_call, t.maxValue_bet,
                                                    t.maxEquityCall, t.max_X, t.maxEquityBet)

    def run(self):
        log = logging.getLogger(__name__)
        history = History()
        preflop_url, preflop_url_backup = self.updater.get_preflop_sheet_url()
        try:
            history.preflop_sheet = pd.read_excel(preflop_url, sheet_name=None, engine='openpyxl')
        except:
            history.preflop_sheet = pd.read_excel(preflop_url_backup, sheet_name=None, engine='openpyxl')


        strategy = StrategyHandler()
        strategy.read_strategy()

        preflop_state = CurrentHandPreflopState()
        mongo = MongoManager()
        table_scraper_name = None
        runtime_table_name = None
        nn_model = None
        slow_table = False

        # Session scheduling logic
        config = get_config()
        try:
            enable_schedule = config.config.getboolean('antidetection', 'enable_schedule', fallback=False)
        except:
            enable_schedule = False
        session_length_seconds = np.random.uniform(2.5, 5.5) * 3600 if enable_schedule else float('inf')

        while True:
            if enable_schedule and (time.time() - self.session_start) > session_length_seconds:
                self.loger.info(f"Human Mimicry: Scheduled session time limit reached ({session_length_seconds/3600:.1f}h). Quitting.")
                self.gui_signals.signal_status.emit('Session Complete')
                sys.exit()
            # reload table if changed

            if self.gui_signals.pause_thread:
                while self.gui_signals.pause_thread:
                    time.sleep(0.5)
                    if self.gui_signals.exit_thread:
                        sys.exit()

            ready = False
            while not ready:
                config = get_config()
                requested_mode = self.get_requested_runtime_mode()
                control_mode = config.config.get('main', 'control')
                selected_table_name = config.config.get('main','table_scraper_name')
                if table_scraper_name != selected_table_name:
                    table_scraper_name = selected_table_name
                    log.info(f"Loading table scraper info for {table_scraper_name}")
                preloaded_screenshot = self.capture_runtime_screenshot(control_mode)
                table_dict = mongo.get_runtime_table(table_scraper_name, screenshot=preloaded_screenshot)
                resolution = mongo.get_last_runtime_resolution()
                resolved_table_name = resolution.resolved_table_name if resolution else table_scraper_name
                if resolution and resolution.resolved_table_name != table_scraper_name:
                    log.info(
                        "Runtime preset resolution switched %s -> %s (score %.3f)",
                        table_scraper_name,
                        resolution.resolved_table_name,
                        resolution.score,
                    )

                if runtime_table_name != resolved_table_name:
                    runtime_table_name = resolved_table_name
                    nn_model = None
                    slow_table = False
                    if 'use_neural_network' in table_dict and (table_dict['use_neural_network'] == '2' or table_dict['use_neural_network'] == 'CheckState.Checked'):
                        from tensorflow.keras.models import model_from_json
                        try:
                            nn_model = model_from_json(table_dict['_model'])
                        except KeyError:
                            raise Exception("This table does not have a neural network model. Please train one first or untick neural network for this table.")
                            
                        mongo.load_table_nn_weights(runtime_table_name)
                        nn_model.load_weights(get_dir('codebase') + '/loaded_model.h5')
                        slow_table = True

                table = TableScreenBased(strategy, table_dict, self.gui_signals, self.game_logger, version, nn_model)
                table.preloaded_entire_screen_pil = preloaded_screenshot
                mouse = MouseMoverTableBased(table_dict)
                mouse.move_mouse_away_from_buttons_jump()

                config = get_config()
                has_info = config.config.getboolean('antidetection', 'enable_info_gathering', fallback=False)
                if has_info and np.random.uniform() < 0.02:
                    log.info("Human Mimicry: Gathering opponent information while waiting...")
                    import random
                    mouse.mouse_action('NoAction', table.tlc, {})
                    mouse.mouse_mover(table.tlc[0] + random.randint(100, 600), table.tlc[1] + random.randint(100, 400))
                    
                    try:
                        has_scrolling = config.config.getboolean('antidetection', 'enable_scrolling', fallback=False)
                        if has_scrolling and random.random() < 0.5:
                            mouse.scroll(random.randint(2, 5))
                    except Exception:
                        pass

                if not table.take_screenshot(True, strategy):
                    continue
                if not table.get_top_left_corner(strategy):
                    continue
                if not table.check_for_captcha(mouse):
                    continue
                if not table.get_lost_everything(history, table, strategy, self.gui_signals):
                    continue
                if not table.check_for_imback(mouse):
                    continue
                if not table.check_for_resume_hand(mouse):
                    continue
                if not table.check_for_button_if_slow_table(slow_table):
                    self.emit_runtime_wait_status(requested_mode, hero_cards_found=False)
                    time.sleep(0.25)
                    continue
                if not table.get_my_cards():
                    self.emit_runtime_wait_status(requested_mode, hero_cards_found=False)
                    time.sleep(0.25)
                    continue
                if not table.get_new_hand(mouse, history, strategy):
                    continue
                if not table.get_table_cards(history):
                    continue
                if not table.upload_collusion_wrapper(strategy, history):
                    continue
                if not table.get_dealer_position():
                    continue
                if not table.check_fast_fold(history, strategy, mouse):
                    continue
                if not table.check_for_button():
                    self.emit_runtime_wait_status(requested_mode, hero_cards_found=True)
                    time.sleep(0.25)
                    continue
                if not strategy.read_strategy():
                    continue
                if not table.get_round_number(history):
                    continue
                if not table.check_for_checkbutton():
                    continue
                if not table.init_get_other_players_info():
                    continue
                if not table.get_other_player_status(strategy, history):
                    continue
                if not table.get_other_player_names(strategy):
                    continue
                if not table.get_other_player_funds(strategy):
                    continue
                if not table.get_total_pot_value(history):
                    continue
                if not table.get_round_pot_value(history):
                    continue
                if not table.check_for_call():
                    continue
                if not table.check_for_betbutton():
                    continue
                if not table.check_for_allincall():
                    continue
                if not table.get_current_call_value(strategy):
                    continue
                if not table.get_current_bet_value(strategy):
                    continue

                ready = True

            if not self.gui_signals.pause_thread:
                config = get_config()
                m = run_montecarlo_wrapper(strategy, self.gui_signals, config, ui, table, self.game_logger,
                                           preflop_state, history)
                self.gui_signals.signal_progressbar_increase.emit(20)
                d = Decision(table, history, strategy, self.game_logger)
                d.make_decision(table, history, strategy, self.game_logger)
                self.gui_signals.signal_progressbar_increase.emit(10)
                if self.gui_signals.exit_thread: sys.exit()

                self.update_most_gui_items(preflop_state, strategy, m, table, d, history, self.gui_signals)

                enable_drift_watcher = config.config.getboolean('room_manager', 'enable_drift_watcher', fallback=False)
                drift_interval = config.config.getint('room_manager', 'drift_check_interval_seconds', fallback=300)
                if enable_drift_watcher and (time.time() - self.last_drift_check_at) >= drift_interval:
                    drift_result = mongo.observe_runtime_table(runtime_table_name or table_scraper_name, table.entireScreenPIL)
                    self.last_drift_check_at = time.time()
                    log.info(
                        "Drift watcher result for %s: %s (score %.3f)%s",
                        runtime_table_name or table_scraper_name,
                        drift_result.status,
                        drift_result.score,
                        f' -> {drift_result.version_id}' if drift_result.version_id else '',
                    )

                log.info(
                    "Equity: " + str(table.equity * 100) + "% -> " + str(int(table.assumedPlayers)) + " (" + str(
                        int(table.other_active_players)) + "-" + str(int(table.playersAhead)) + "+1) Plr")
                log.info("Final Call Limit: " + str(d.finalCallLimit) + " --> " + str(table.minCall))
                log.info("Final Bet Limit: " + str(d.finalBetLimit) + " --> " + str(table.minBet))
                log.info(
                    "Pot size: " + str(table.totalPotValue) + " -> Zero EV Call: " + str(round(d.maxCallEV, 2)))
                log.info("+++++++++++++++++++++++ Decision: " + str(d.decision) + "+++++++++++++++++++++++")

                mouse_target = d.decision
                action_options = {}
                live_action_executed = False
                if mouse_target == 'NoAction':
                    log.warning("Decision gate requested NoAction; skipping live click")
                    mouse_target = None

                if mouse_target == 'Call' and table.allInCallButton:
                    mouse_target = 'Call2'
                elif mouse_target == 'BetPlus':
                    action_options['increases_num'] = strategy.selected_strategy['BetPlusInc']

                requested_mode = self.get_requested_runtime_mode()
                execute_live_action = requested_mode != 'observe' and mouse_target is not None

                if execute_live_action:
                    config = get_config()
                    has_fatigue = config.config.getboolean('antidetection', 'enable_fatigue', fallback=True)
                    has_tilt = config.config.getboolean('antidetection', 'enable_tilt', fallback=False)

                    # Calculate Proportional Hesitation
                    base_delay = np.random.uniform(0.5, 2.0)
                    
                    # Street Multiplier
                    street_mult = {'PreFlop': 1.0, 'Flop': 1.2, 'Turn': 1.5, 'River': 2.0}.get(table.gameStage, 1.0)
                    
                    # Pot Multiplier (caps at 2.5x)
                    pot_mult = 1.0
                    try:
                        if table.bigBlind and table.totalPotValue:
                            bb_ratio = table.totalPotValue / table.bigBlind
                            pot_mult = min(1.0 + (bb_ratio * 0.05), 2.5)
                    except Exception:
                        pass
                        
                    # Decision Hardness Multiplier
                    decision_mult = 1.0
                    if mouse_target in ['Call', 'Call2'] and pot_mult >= 1.5:
                        decision_mult = 1.8
                        
                    # Fatigue Multiplier
                    hours_played = (time.time() - self.session_start) / 3600.0
                    fatigue_mult = min(1.0 + (hours_played * 0.15), 1.5) if has_fatigue else 1.0

                    has_elastic = config.config.getboolean('antidetection', 'enable_elastic_tables', fallback=False)
                    if has_elastic and fatigue_mult > 1.3:
                        if np.random.uniform() < 0.05:
                            log.info("Human Mimicry: Fatigue threshold reached! Elastic Multi-tabling is terminating this table session.")
                            sys.exit()

                    tilt_mult = 1.0
                    if has_tilt and self.tilt_hands_remaining > 0:
                        tilt_mult = 0.3 # fast and aggressive when frustrated
                    
                    final_delay = min(base_delay * street_mult * pot_mult * decision_mult * fatigue_mult * tilt_mult, 12.0)
                    if has_fatigue or tilt_mult != 1.0:
                        log.info(f"Human Mimicry: Hesitating for {final_delay:.2f} seconds before acting (Fatigue x{fatigue_mult:.2f}, Tilt x{tilt_mult:.2f})")
                        time.sleep(final_delay)

                    mouse.mouse_action(mouse_target, table.tlc, action_options)
                    live_action_executed = True
                else:
                    status_text = self.emit_non_live_action_status(requested_mode, mouse_target)
                    if mouse_target is None:
                        log.info("%s", status_text)
                    else:
                        log.info("%s. Recommendation only: %s", status_text, mouse_target)
                    time.sleep(0.25)

                # for pokerstars, high fold straight after all in call (fold button matches the stay in game)
                # if mouse_target == 'Call2' and table.allInCallButton:
                #     mouse_target = 'Fold'
                #     mouse.mouse_action(mouse_target, table.tlc, action_options)

                if not live_action_executed:
                    continue

                table.time_action_completed = datetime.datetime.utcnow()

                filename = str(history.GameID) + "_" + str(table.gameStage) + "_" + str(history.round_number) + ".png"
                log.debug("Saving screenshot: " + filename)
                pil_image = table.crop_image(table.entireScreenPIL, table.tlc[0], table.tlc[1], table.tlc[0] + const.CROP_WIDTH,
                                             table.tlc[1] + const.CROP_HEIGHT)
                pil_image.save("log/screenshots/" + filename)

                self.gui_signals.signal_status.emit("Logging data")

                t_log_db = threading.Thread(name='t_log_db', target=self.game_logger.write_log_file,
                                            args=[strategy, history, table, d])
                t_log_db.daemon = True
                t_log_db.start()
                # self.game_logger.write_log_file(strategy, history, table, d)

                history.previousPot = table.totalPotValue
                history.histGameStage = table.gameStage
                history.histDecision = d.decision
                history.histEquity = table.equity
                history.histMinCall = table.minCall
                history.histMinBet = table.minBet
                history.hist_other_players = table.other_players
                history.first_raiser = table.first_raiser
                history.first_caller = table.first_caller
                history.previous_decision = d.decision
                history.lastRoundGameID = history.GameID
                history.previous_round_pot_value = table.round_pot_value
                history.last_round_bluff = False if table.currentBluff == 0 else True
                if table.gameStage == 'PreFlop':
                    preflop_state.update_values(table, d.decision, history, d)
                mongo.increment_plays(table_scraper_name)
                log.info("=========== round end ===========")

                config = get_config()
                has_bathroom = config.config.getboolean('antidetection', 'enable_bathroom_breaks', fallback=True)
                has_bg_noise = config.config.getboolean('antidetection', 'enable_background_noise', fallback=False)
                has_tilt = config.config.getboolean('antidetection', 'enable_tilt', fallback=False)

                if has_tilt:
                    try:
                        current_funds = float(strategy.selected_strategy['initialFunds'])
                        if self.last_round_funds is not None:
                            loss = self.last_round_funds - current_funds
                            import random
                            loss_threshold = current_funds * random.uniform(0.08, 0.15)
                            if loss > loss_threshold: 
                                self.tilt_hands_remaining = random.randint(2, 7)
                                log.info(f"HUMAN TILT DETECTED: Gross bankroll loss. Simulating emotional distress for next {self.tilt_hands_remaining} hands.")
                        self.last_round_funds = current_funds
                    except:
                        pass
                
                if self.tilt_hands_remaining > 0:
                    self.tilt_hands_remaining -= 1

                # Random Bathroom/Idle Break (1.5% chance)
                if has_bathroom and np.random.uniform() < 0.015:
                    break_time = np.random.uniform(120, 300)
                    log.info(f"Human Mimicry: Taking a random break for {break_time:.1f} seconds to simulate a human stepping away.")
                    if has_bg_noise:
                        log.info("Human Mimicry: Opening dummy browser window for background noise.")
                        import webbrowser
                        import random
                        urls = [
                            "https://en.wikipedia.org/wiki/Special:Random",
                            "https://www.youtube.com/",
                            "https://www.amazon.fr/",
                            "https://www.twitch.tv/",
                            "https://www.dailymotion.com/",
                            "https://news.google.com/",
                            "https://www.reddit.com/r/poker/",
                            "https://twitter.com/",
                            "https://www.lequipe.fr/",
                            "https://www.netflix.com/"
                        ]
                        try:
                           webbrowser.open_new(random.choice(urls))
                        except: pass
                    time.sleep(break_time)

# ==== MAIN PROGRAM =====

def run_poker():
    init_logger(screenlevel=logging.INFO, filename='deepmind_pokerbot', logdir='log')
    # print(f"Screenloglevel: {screenloglevel}")
    log = logging.getLogger("")
    log.info("Initializing program")

    # Back up the reference to the exceptionhook
    sys._excepthook = sys.excepthook
    log.info("Check for auto-update")
    updater = UpdateChecker()
    updater.check_update(version)
    log.info(f"Lastest version already installed: {version}")

    def exception_hook(exctype, value, traceback):
        # Print the error and traceback
        logger = logging.getLogger('main')
        print(exctype, value, traceback)
        logger.error(str(exctype))
        logger.error(str(value))
        logger.error(str(traceback))
        # Call the normal Exception hook after
        sys.__excepthook__(exctype, value, traceback)
        sys.exit(1)

    # Set the exception hook to our wrapping function
    sys.__excepthook__ = exception_hook

    app = QtWidgets.QApplication(sys.argv)
    global ui  # pylint: disable=global-statement
    ui = UiPokerbot()
    ui.setWindowIcon(QtGui.QIcon(os.path.join(get_dir('codebase'), 'gui', 'ui', 'icon.ico')))

    gui_signals = UIActionAndSignals(ui)

    t1 = ThreadManager(1, "Thread-1", 1, gui_signals, updater)
    t1.start()
    
    t2 = threading.Thread(target=local_restapi)
    t2.daemon = True
    t2.start()

    try:
        sys.exit(app.exec())
    except:
        print("Preparing to exit...")
        gui_signals.exit_thread = True


if __name__ == '__main__':
    use_v2_runtime = str(os.getenv("POKER_USE_LEGACY", "0") or "0").strip().lower() not in {"1", "true", "yes", "on"}
    if use_v2_runtime:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from src.main import run_bot

        logging.getLogger("").info(LEGACY_ARCHIVED_MESSAGE)
        run_bot()
    else:
        logging.getLogger("").warning(LEGACY_ARCHIVED_MESSAGE)
        run_poker()
