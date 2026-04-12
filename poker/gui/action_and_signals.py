# pylint: disable=ungrouped-imports

from sys import platform

import numexpr  # required for pyinstaller
from PyQt6 import QtCore
import threading

_ = numexpr
import matplotlib
from matplotlib import pyplot as plt
import seaborn as sns
import numpy as np

from poker.gui.i18n import apply_translations, get_language, get_language_name, normalize_language, translate_text
from poker.gui.pandas_model import PandasModel
from poker.gui.plots.bar_plotter_2 import BarPlotter2
from poker.gui.plots.curve_plot import CurvePlot
from poker.gui.plots.funds_change_plot import FundsChangePlot
from poker.gui.plots.funds_plotter import FundsPlotter
from poker.gui.plots.histogram_equity import HistogramEquityWinLoss
from poker.gui.plots.pie_plotter import PiePlotter
from poker.gui.plots.scatter_plot import ScatterPlot
from poker.tools.helper import COMPUTER_NAME, open_payment_link

if not (platform == "linux" or platform == "linux2"):  # pylint: disable=consider-using-in
    matplotlib.use('QtAgg')
from PyQt6.QtCore import *
from poker.gui.room_manager_widget import RoomManagerDock
from poker.scraper.table_setup_actions_and_signals import TableSetupActionAndSignals
from poker.gui.gui_launcher import TableSetupForm, GeneticAlgo, SetupForm, StrategyEditorForm, AnalyserForm
from poker.tools.mongo_manager import MongoManager
from poker.tools.supported_sites import build_supported_sites_help_html

from poker.tools.vbox_manager import VirtualBoxController
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMessageBox, QWidget
import webbrowser
from poker.decisionmaker.gto_runtime import ensure_local_gto_server
from poker.decisionmaker.genetic_algorithm import *  # pylint: disable=wildcard-import
import os
import logging



# pylint: disable=unnecessary-lambda

class UIActionAndSignals(QObject):  # pylint: disable=undefined-variable
    signal_progressbar_increase = QtCore.pyqtSignal(int)
    signal_progressbar_reset = QtCore.pyqtSignal()

    signal_status = QtCore.pyqtSignal(str)
    signal_decision = QtCore.pyqtSignal(str)

    signal_bar_chart_update = QtCore.pyqtSignal(object, str)
    signal_funds_chart_update = QtCore.pyqtSignal(object)
    signal_pie_chart_update = QtCore.pyqtSignal(dict)
    signal_curve_chart_update1 = QtCore.pyqtSignal(float, float, float, float, float, float, str, str)
    signal_curve_chart_update2 = QtCore.pyqtSignal(float, float, float, float, float, float, float, float, float, float,
                                                   float)
    signal_lcd_number_update = QtCore.pyqtSignal(str, float)
    signal_label_number_update = QtCore.pyqtSignal(str, str)
    # signal_update_selected_strategy = QtCore.pyqtSignal(str)

    signal_update_strategy_sliders = QtCore.pyqtSignal(str)
    signal_open_setup = QtCore.pyqtSignal(object, object)

    RUNTIME_MODE_VALUES = ("auto", "observe", "play")

    def __init__(self, ui_main_window):
        self.logger = logging.getLogger('gui')
        self.current_language = get_language()
        self.current_status_text = None
        self.current_decision_text = None

        self.ui_analyser = None

        gl = GameLogger()

        self.strategy_handler = StrategyHandler()
        self.strategy_handler.read_strategy()
        p = self.strategy_handler

        self.pause_thread = True
        self.exit_thread = False
        self.runtime_boot_thread = None
        self.runtime_mode_container = None
        self.runtime_mode_label = None
        self.runtime_mode_selector = None

        QObject.__init__(self)  # pylint: disable=undefined-variable
        self.strategy_items_with_multipliers = {
            "always_call_low_stack_multiplier": 1,
            "out_multiplier": 1,
            "FlopBluffMaxEquity": 100,
            "TurnBluffMaxEquity": 100,
            "RiverBluffMaxEquity": 100,
            "max_abs_fundchange": 100,
            "RiverCheckDeceptionMinEquity": 100,
            "TurnCheckDeceptionMinEquity": 100,
            "pre_flop_equity_reduction_by_position": 100,
            "pre_flop_equity_increase_if_bet": 100,
            "pre_flop_equity_increase_if_call": 100,
            "minimum_bet_size": 1,
            "range_multiple_players": 100,
            "range_utg0": 100,
            "range_utg1": 100,
            "range_utg2": 100,
            "range_utg3": 100,
            "range_utg4": 100,
            "range_utg5": 100,
            "range_utg6": 100,
            "range_utg7": 100,
            "range_utg8": 100,
            "range_preflop": 100,
            "PreFlopCallPower": 1,
            "secondRiverBetPotMinEquity": 100,
            "FlopBetPower": 1,
            "betPotRiverEquityMaxBBM": 1,
            "TurnMinBetEquity": 100,
            "PreFlopBetPower": 1,
            "potAdjustmentPreFlop": 1,
            "RiverCallPower": 1,
            "minBullyEquity": 100,
            "PreFlopMinBetEquity": 100,
            "PreFlopMinCallEquity": 100,
            "BetPlusInc": 1,
            "FlopMinCallEquity": 100,
            "secondRoundAdjustmentPreFlop": 100,
            "FlopBluffMinEquity": 100,
            "TurnBluffMinEquity": 100,
            "FlopCallPower": 1,
            "TurnCallPower": 1,
            "RiverMinCallEquity": 100,
            "CoveredPlayersCallLikelihoodFlop": 100,
            "TurnMinCallEquity": 100,
            "secondRoundAdjustment": 100,
            "maxPotAdjustmentPreFlop": 100,
            "bullyDivider": 1,
            "maxBullyEquity": 100,
            "alwaysCallEquity": 100,
            "PreFlopMaxBetEquity": 100,
            "RiverBetPower": 1,
            "minimumLossForIteration": -1,
            "initialFunds": 100,
            "initialFunds2": 100,
            "potAdjustment": 1,
            "FlopCheckDeceptionMinEquity": 100,
            "bigBlind": 100,
            "secondRoundAdjustmentPowerIncrease": 1,
            "considerLastGames": 1,
            "betPotRiverEquity": 100,
            "RiverBluffMinEquity": 100,
            "smallBlind": 100,
            "TurnBetPower": 1,
            "FlopMinBetEquity": 100,
            "strategyIterationGames": 1,
            "RiverMinBetEquity": 100,
            "maxPotAdjustment": 100,
            "increased_preflop_betting": 1

        }

        self.ui = ui_main_window
        self.progressbar_value = 0

        # Main Window matplotlip widgets
        self.gui_funds = FundsPlotter(ui_main_window, p)
        self.gui_bar = BarPlotter2(ui_main_window, initialize=True)
        self.gui_curve = CurvePlot(ui_main_window, p)
        self.gui_pie = PiePlotter(ui_main_window, winnerCardTypeList={'Highcard': 22})

        # main window status update signal connections
        self.signal_progressbar_increase.connect(self.increase_progressbar)
        self.signal_progressbar_reset.connect(self.reset_progressbar)
        self.signal_status.connect(self.update_mainwindow_status)
        self.signal_decision.connect(self.update_mainwindow_decision)

        self.signal_lcd_number_update.connect(self.update_lcd_number)
        self.signal_label_number_update.connect(self.update_label_number)

        self.signal_bar_chart_update.connect(lambda: self.gui_bar.drawfigure(gl, p.current_strategy))

        self.signal_funds_chart_update.connect(lambda: self.gui_funds.drawfigure(gl))
        self.signal_curve_chart_update1.connect(self.gui_curve.update_plots)
        self.signal_curve_chart_update2.connect(self.gui_curve.update_lines)
        self.signal_pie_chart_update.connect(self.gui_pie.drawfigure)
        self.signal_open_setup.connect(lambda: self.open_setup())

        ui_main_window.button_genetic_algorithm.clicked.connect(lambda: self.open_genetic_algorithm(p, gl))
        ui_main_window.button_log_analyser.clicked.connect(lambda: self.open_strategy_analyser(p, gl))
        ui_main_window.button_strategy_editor.clicked.connect(lambda: self.open_strategy_editor())
        ui_main_window.button_pause.clicked.connect(lambda: self.pause(ui_main_window, p))
        ui_main_window.button_resume.clicked.connect(lambda: self.resume(ui_main_window, p))

        ui_main_window.pushButton_setup.clicked.connect(lambda: self.open_setup())
        ui_main_window.pushButton_help.clicked.connect(lambda: self.open_help())
        ui_main_window.open_chat.clicked.connect(lambda: self.open_chat())
        ui_main_window.button_table_setup.clicked.connect(lambda: self.toggle_room_manager())

        self.signal_update_strategy_sliders.connect(lambda: self.update_strategy_editor_sliders(p.current_strategy))

        mongo = MongoManager()
        available_tables = mongo.get_available_tables(COMPUTER_NAME)
        ui_main_window.table_selection.addItems(available_tables)
        playable_list = p.get_playable_strategy_list()
        ui_main_window.comboBox_current_strategy.addItems(playable_list)
        ui_main_window.comboBox_current_strategy.currentIndexChanged[int].connect(
            lambda: self.signal_update_selected_strategy(p))
        ui_main_window.table_selection.currentIndexChanged[int].connect(
            lambda: self.signal_update_selected_strategy(p))
        config = get_config()
        initial_selection = config.config.get('main', 'last_strategy')
        idx = 0
        for i in [i for i, x in enumerate(playable_list) if x == initial_selection]:
            idx = i
        ui_main_window.comboBox_current_strategy.setCurrentIndex(idx)

        table_scraper_name = config.config.get('main', 'table_scraper_name')
        try:
            idx = available_tables.index(table_scraper_name)
        except ValueError:
            idx = 0
        ui_main_window.table_selection.setCurrentIndex(idx)
        apply_translations(self.ui, self.current_language)
        self._setup_runtime_mode_selector()
        self.ensure_room_manager_dock()
        self.ui.button_table_setup.setText("Room Manager")
        self.ui.button_table_setup.setToolTip("Create, validate, sync and roll back room presets")

    @classmethod
    def normalize_runtime_mode(cls, value):
        runtime_mode = str(value or "auto").strip().lower()
        if runtime_mode not in cls.RUNTIME_MODE_VALUES:
            return "auto"
        return runtime_mode

    def _runtime_mode_label_copy(self, mode):
        labels = {
            "auto": ("Auto", "Auto"),
            "observe": ("Observation", "Observe"),
            "play": ("Jouer", "Play"),
        }
        return labels[self.normalize_runtime_mode(mode)][0 if self.current_language == 'fr' else 1]

    def _runtime_mode_status_copy(self, mode):
        mode = self.normalize_runtime_mode(mode)
        if self.current_language == 'fr':
            return {
                "auto": "Mode auto actif : detection observation / jeu",
                "observe": "Mode observation actif",
                "play": "Mode jouer actif",
            }[mode]

        return {
            "auto": "Auto mode running: detecting observation vs play",
            "observe": "Observation mode running",
            "play": "Play mode running",
        }[mode]

    def _ensure_runtime_mode_config(self):
        config = get_config()
        runtime_mode = self.normalize_runtime_mode(config.config.get('main', 'run_mode', fallback='auto'))
        if not config.config.has_option('main', 'run_mode') or config.config.get('main', 'run_mode', fallback='') != runtime_mode:
            config.config.set('main', 'run_mode', runtime_mode)
            config.update_file()
        return runtime_mode

    def _persist_runtime_mode(self, runtime_mode):
        runtime_mode = self.normalize_runtime_mode(runtime_mode)
        config = get_config()
        config.config.set('main', 'run_mode', runtime_mode)
        config.update_file()
        self.ui.auto_act.setChecked(runtime_mode == 'play')

    def get_runtime_mode(self):
        if self.runtime_mode_selector is not None:
            selected_mode = self.runtime_mode_selector.currentData()
            if selected_mode is not None:
                return self.normalize_runtime_mode(selected_mode)

        config = get_config()
        return self.normalize_runtime_mode(config.config.get('main', 'run_mode', fallback='auto'))

    def _setup_runtime_mode_selector(self):
        if self.runtime_mode_selector is not None:
            return

        runtime_mode = self._ensure_runtime_mode_config()
        self.ui.auto_act.hide()

        self.runtime_mode_container = QWidget(self.ui)
        self.runtime_mode_container.setObjectName("runtime_mode_container")
        layout = QHBoxLayout(self.runtime_mode_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.runtime_mode_label = QLabel(self.runtime_mode_container)
        self.runtime_mode_label.setObjectName("runtime_mode_label")

        self.runtime_mode_selector = QComboBox(self.runtime_mode_container)
        self.runtime_mode_selector.setObjectName("runtime_mode_selector")
        self.runtime_mode_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

        layout.addWidget(self.runtime_mode_label)
        layout.addWidget(self.runtime_mode_selector, 1)
        self.ui.verticalLayout_7.insertWidget(0, self.runtime_mode_container)

        self._refresh_runtime_mode_selector(runtime_mode)
        self.runtime_mode_selector.currentIndexChanged.connect(self._on_runtime_mode_changed)

    def _refresh_runtime_mode_selector(self, selected_mode=None):
        if self.runtime_mode_selector is None or self.runtime_mode_label is None:
            return

        runtime_mode = self.normalize_runtime_mode(selected_mode or self.get_runtime_mode())
        self.runtime_mode_label.setText("Mode")

        self.runtime_mode_selector.blockSignals(True)
        self.runtime_mode_selector.clear()
        for mode in self.RUNTIME_MODE_VALUES:
            self.runtime_mode_selector.addItem(self._runtime_mode_label_copy(mode), mode)
        selected_index = self.runtime_mode_selector.findData(runtime_mode)
        if selected_index < 0:
            selected_index = 0
        self.runtime_mode_selector.setCurrentIndex(selected_index)
        self.runtime_mode_selector.blockSignals(False)

        self.ui.auto_act.setChecked(runtime_mode == 'play')

    def _on_runtime_mode_changed(self, *_args):
        runtime_mode = self.get_runtime_mode()
        self._persist_runtime_mode(runtime_mode)
        if not self.pause_thread:
            self.signal_status.emit(self._runtime_mode_status_copy(runtime_mode))

    def signal_update_selected_strategy(self, p):
        config = get_config()

        newly_selected_strategy = self.ui.comboBox_current_strategy.currentText()
        config.config.set('main', 'last_strategy', newly_selected_strategy)

        table_selection = self.ui.table_selection.currentText()
        config.config.set('main', 'table_scraper_name', table_selection)

        config.update_file()
        p.read_strategy()
        self.logger.info("Active strategy changed to: " + p.current_strategy)
        self.logger.info("Active table changed to: " + table_selection)

    def refresh_table_selector(self):
        mongo = MongoManager()
        selected = self.ui.table_selection.currentText()
        available_tables = mongo.get_available_tables(COMPUTER_NAME)
        self.ui.table_selection.blockSignals(True)
        self.ui.table_selection.clear()
        self.ui.table_selection.addItems(available_tables)
        if selected in available_tables:
            self.ui.table_selection.setCurrentText(selected)
        elif available_tables:
            self.ui.table_selection.setCurrentIndex(0)
        self.ui.table_selection.blockSignals(False)
        if hasattr(self, 'room_manager_dock'):
            self.room_manager_dock.widget.refresh_tables()

    def ensure_room_manager_dock(self):
        if getattr(self, 'room_manager_dock', None) is not None:
            return self.room_manager_dock
        self.room_manager_dock = RoomManagerDock(
            self.ui,
            language=self.current_language,
            open_table_setup_callback=self.open_table_setup,
            refresh_table_selector_callback=self.refresh_table_selector,
        )
        self.ui.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.room_manager_dock)
        self.room_manager_dock.bind_main_table_selector(self.ui.table_selection)
        self.room_manager_dock.hide()
        return self.room_manager_dock

    def toggle_room_manager(self):
        dock = self.ensure_room_manager_dock()
        if dock.isVisible():
            dock.hide()
            return
        dock.refresh()
        dock.show()
        dock.raise_()

    def pause(self, ui, p):
        ui.button_resume.setEnabled(True)
        ui.button_pause.setEnabled(False)
        self.pause_thread = True
        self.signal_status.emit(
            "Runtime en pause" if self.current_language == 'fr' else "Runtime paused"
        )

    def _boot_runtime_services(self, requested_mode):
        starting_message = (
            "Demarrage du runtime..." if self.current_language == 'fr' else "Starting runtime..."
        )
        ready_message = (
            "Runtime pret : detection de table et solver disponibles"
            if self.current_language == 'fr'
            else "Runtime ready: table detection and solver online"
        )
        degraded_message = (
            "Runtime pret : detection active, solver optionnel"
            if self.current_language == 'fr'
            else "Runtime ready: detection active, solver optional"
        )

        self.signal_status.emit(starting_message)
        solver_ready = ensure_local_gto_server(timeout_sec=6)
        if self.pause_thread:
            return

        if solver_ready:
            self.signal_status.emit(ready_message)
        elif requested_mode in self.RUNTIME_MODE_VALUES:
            self.signal_status.emit(degraded_message)

    def resume(self, ui, p):
        ui.button_resume.setEnabled(False)
        ui.button_pause.setEnabled(True)
        self.pause_thread = False
        requested_mode = self.get_runtime_mode()
        self.signal_status.emit(self._runtime_mode_status_copy(requested_mode))
        if self.runtime_boot_thread is None or not self.runtime_boot_thread.is_alive():
            self.runtime_boot_thread = threading.Thread(
                target=self._boot_runtime_services,
                args=(requested_mode,),
                name='runtime_boot',
                daemon=True,
            )
            self.runtime_boot_thread.start()

    def increase_progressbar(self, value):
        self.progressbar_value += value
        self.progressbar_value = min(self.progressbar_value, 100)
        self.ui.progress_bar.setValue(self.progressbar_value)

    def reset_progressbar(self):
        self.progressbar_value = 0
        self.ui.progress_bar.setValue(0)

    def update_mainwindow_status(self, text):
        self.current_status_text = text
        self.ui.status.setText(translate_text(text, self.current_language))

    def update_mainwindow_decision(self, text):
        self.current_decision_text = text
        self.ui.last_decision.setText(translate_text(text, self.current_language))

    def update_lcd_number(self, item, value):
        func = getattr(self.ui, item)
        func.display(value)

    def update_label_number(self, item, value):
        func = getattr(self.ui, item)
        func.setText(str(value))

    @staticmethod
    def _combo_value(combo_box):
        value = combo_box.currentData()
        if value is None:
            return combo_box.currentText()
        return value

    def _retranslate_analyser_combos(self):
        if self.ui_analyser is None:
            return

        for combo_box in (self.ui_analyser.combobox_actiontype, self.ui_analyser.combobox_gamestage):
            for index in range(combo_box.count()):
                original = combo_box.itemData(index)
                if not isinstance(original, str):
                    original = combo_box.itemText(index)
                    combo_box.setItemData(index, original)
                combo_box.setItemText(index, translate_text(original, self.current_language))

    def open_strategy_analyser(self, p, l):
        self.signal_progressbar_reset.emit()
        self.ui_analyser = AnalyserForm()
        apply_translations(self.ui_analyser, self.current_language)

        self.gui_fundschange = FundsChangePlot(self.ui_analyser)
        self.gui_fundschange.drawfigure(self.ui_analyser.my_computer_only.isChecked())

        for action in ['All', 'Fold', 'Check', 'Call', 'Bet', 'BetPlus', 'Bet half pot', 'Bet pot', 'Bet Bluff']:
            self.ui_analyser.combobox_actiontype.addItem(translate_text(action, self.current_language), action)

        for game_stage in ['All', 'PreFlop', 'Flop', 'Turn', 'River']:
            self.ui_analyser.combobox_gamestage.addItem(translate_text(game_stage, self.current_language), game_stage)

        self.ui_analyser.combobox_strategy.addItems(l.get_played_strategy_list())

        index = self.ui_analyser.combobox_strategy.findText(p.current_strategy, QtCore.Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            self.ui_analyser.combobox_strategy.setCurrentIndex(index)

        self.gui_histogram = HistogramEquityWinLoss(self.ui_analyser)
        self.gui_scatterplot = ScatterPlot(self.ui_analyser)

        self.ui_analyser.combobox_gamestage.currentIndexChanged[int].connect(
            lambda: self.strategy_analyser_update_plots(l, p))
        self.ui_analyser.combobox_actiontype.currentIndexChanged[int].connect(
            lambda: self.strategy_analyser_update_plots(l, p))
        self.ui_analyser.combobox_strategy.currentIndexChanged[int].connect(lambda: self.update_strategy_analyser(l, p))
        self.ui_analyser.show_rounds.stateChanged[int].connect(lambda: self.update_strategy_analyser(l, p))
        self.ui_analyser.my_computer_only.stateChanged[int].connect(lambda: self.update_strategy_analyser(l, p))
        self.ui_analyser.show_league_table.clicked.connect(lambda: self.show_league_table())

        self.gui_bar2 = BarPlotter2(self.ui_analyser)
        self.gui_bar2.drawfigure(l,
                                 self.ui_analyser.combobox_strategy.currentText(),
                                 self._combo_value(self.ui_analyser.combobox_gamestage),
                                 self._combo_value(self.ui_analyser.combobox_actiontype),
                                 self.ui_analyser.show_rounds.isChecked(),
                                 self.ui_analyser.my_computer_only.isChecked())
        self.update_strategy_analyser(l, p)

    @staticmethod
    def show_league_table():
        mongo = MongoManager()
        top_df = mongo.get_top_strategies().sort_values('Return per bb in 100 Hands', ascending=False)

        def colors_from_values(values, palette_name):
            # normalize the values to range [0, 1]
            normalized = (values - min(values)) / (max(values) - min(values))
            # convert to indices
            indices = np.round(normalized * (len(values) - 1)).astype(np.int32)
            # use the indices to get the colors
            palette = sns.color_palette(palette_name, len(values))
            return np.array(palette).take(indices, axis=0)

        ax, fig = plt.subplots(figsize=(25, 20))
        sns.barplot(data=top_df, x='Return per bb in 100 Hands', y='_id', ci=None,
                    palette=colors_from_values(top_df['count'], "YlOrRd")).set(
            title='Top Strategies by individual player')
        plt.show()

    def open_strategy_editor(self):
        self.p_edited = StrategyHandler()
        self.p_edited.read_strategy()
        self.signal_progressbar_reset.emit()
        self.ui_editor = StrategyEditorForm()
        apply_translations(self.ui_editor, self.current_language)

        self.curveplot_preflop = CurvePlot(self.ui_editor, self.p_edited, layout='verticalLayout_preflop')
        self.curveplot_flop = CurvePlot(self.ui_editor, self.p_edited, layout='verticalLayout_flop')
        self.curveplot_turn = CurvePlot(self.ui_editor, self.p_edited, layout='verticalLayout_turn')
        self.curveplot_river = CurvePlot(self.ui_editor, self.p_edited, layout='verticalLayout_river')

        self.ui_editor.pushButton_update1.clicked.connect(
            lambda: self.update_strategy_editor_graphs(self.p_edited.current_strategy))
        self.ui_editor.pushButton_update2.clicked.connect(
            lambda: self.update_strategy_editor_graphs(self.p_edited.current_strategy))
        self.ui_editor.pushButton_update3.clicked.connect(
            lambda: self.update_strategy_editor_graphs(self.p_edited.current_strategy))
        self.ui_editor.pushButton_update4.clicked.connect(
            lambda: self.update_strategy_editor_graphs(self.p_edited.current_strategy))

        self.signal_update_strategy_sliders.emit(self.p_edited.current_strategy)
        self.ui_editor.Strategy.currentIndexChanged.connect(
            lambda: self.update_strategy_editor_sliders(self.ui_editor.Strategy.currentText()))
        self.ui_editor.pushButton_save_new_strategy.clicked.connect(
            lambda: self.save_strategy(self.ui_editor.lineEdit_new_name.text(), False))
        self.ui_editor.pushButton_save_current_strategy.clicked.connect(
            lambda: self.save_strategy(self.ui_editor.Strategy.currentText(), True))

        self.playable_list = self.p_edited.get_playable_strategy_list()
        self.ui_editor.Strategy.addItems(self.playable_list)
        config = get_config()
        initial_selection = config.config.get('main', 'last_strategy')
        idx = 0
        for i in [i for i, x in enumerate(self.playable_list) if x == initial_selection]:
            idx = i
        self.ui_editor.Strategy.setCurrentIndex(idx)

    def open_genetic_algorithm(self, p, l):
        self.ui.button_genetic_algorithm.setEnabled(False)
        g = GeneticAlgorithm(False, l)
        r = g.get_results()
        self.genetic_algorithm_form = GeneticAlgo()
        apply_translations(self.genetic_algorithm_form, self.current_language)
        self.genetic_algorithm_form.textBrowser.setText(str(r))

        self.genetic_algorithm_form.buttonBox.accepted.connect(lambda: GeneticAlgorithm(True, l))

    def open_help(self):
        url = "https://github.com/dickreuter/Poker"
        help_box = QMessageBox(self.ui)
        help_box.setWindowTitle(translate_text("Supported Rooms", self.current_language))
        help_box.setIcon(QMessageBox.Icon.Information)
        help_box.setTextFormat(Qt.TextFormat.RichText)
        help_box.setText(build_supported_sites_help_html())
        docs_button = help_box.addButton(
            translate_text("Open GitHub Guide", self.current_language),
            QMessageBox.ButtonRole.HelpRole,
        )
        help_box.addButton(QMessageBox.StandardButton.Ok)
        help_box.exec()

        if help_box.clickedButton() == docs_button:
            webbrowser.open(url, new=2)

    def open_chat(self):
        url = "https://discord.gg/xB9sR3Q7r3"
        webbrowser.open(url, new=2)

    def open_table_setup(self, open_wizard=False):
        self.ui_setup_table = TableSetupForm()
        apply_translations(self.ui_setup_table, self.current_language)
        self.table_setup_controller = TableSetupActionAndSignals(self.ui_setup_table)
        self.ui_setup_table.destroyed.connect(lambda *_: self.refresh_table_selector())
        if open_wizard:
            QtCore.QTimer.singleShot(0, self.table_setup_controller.start_room_wizard)

    def open_setup(self):
        self.ui_setup = SetupForm()
        self.ui_setup.pushButton_save.clicked.connect(lambda: self.save_setup())
        vm_list = ['Direct mouse control']
        try:
            vm = VirtualBoxController()
            vm_list += vm.get_vbox_list()
        except:
            pass  # no virtual machine

        for vm_name in vm_list:
            display = translate_text(vm_name, self.current_language) if vm_name == 'Direct mouse control' else vm_name
            self.ui_setup.comboBox_vm.addItem(display, vm_name)
        timeouts = ['8', '9', '10', '11', '12']
        self.ui_setup.comboBox_2.addItems(timeouts)
        self.ui_setup.comboBox_language.addItem(get_language_name('en', self.current_language), 'en')
        self.ui_setup.comboBox_language.addItem(get_language_name('fr', self.current_language), 'fr')

        config = get_config()
        try:
            mouse_control = config.config.get('main', 'control')
        except:
            mouse_control = 'Direct mouse control'
        for i in [i for i in range(self.ui_setup.comboBox_vm.count())
                  if self.ui_setup.comboBox_vm.itemData(i) == mouse_control]:
            idx = i
            self.ui_setup.comboBox_vm.setCurrentIndex(idx)

        try:
            timeout = config.config.get('main', 'montecarlo_timeout')
        except:
            timeout = 10
        for i in [i for i, x in enumerate(timeouts) if x == timeout]:
            idx = i
            self.ui_setup.comboBox_2.setCurrentIndex(idx)

        login = config.config.get('main', 'login')
        password = config.config.get('main', 'password')
        db = config.config.get('main', 'db')

        self.ui_setup.login.setText(login)
        self.ui_setup.password.setText(password)
        language_index = self.ui_setup.comboBox_language.findData(self.current_language)
        if language_index >= 0:
            self.ui_setup.comboBox_language.setCurrentIndex(language_index)
            
        self.ui_setup.enable_human_sleeps.setChecked(config.config.getboolean('antidetection', 'enable_human_sleeps', fallback=True))
        self.ui_setup.enable_fatigue.setChecked(config.config.getboolean('antidetection', 'enable_fatigue', fallback=True))
        self.ui_setup.enable_tilt.setChecked(config.config.getboolean('antidetection', 'enable_tilt', fallback=False))
        self.ui_setup.enable_info_gathering.setChecked(config.config.getboolean('antidetection', 'enable_info_gathering', fallback=False))
        self.ui_setup.enable_background_noise.setChecked(config.config.getboolean('antidetection', 'enable_background_noise', fallback=False))
        self.ui_setup.enable_bathroom_breaks.setChecked(config.config.getboolean('antidetection', 'enable_bathroom_breaks', fallback=True))
        self.ui_setup.enable_missclicks.setChecked(config.config.getboolean('antidetection', 'enable_missclicks', fallback=False))
        self.ui_setup.enable_scrolling.setChecked(config.config.getboolean('antidetection', 'enable_scrolling', fallback=False))
        self.ui_setup.enable_schedule.setChecked(config.config.getboolean('antidetection', 'enable_schedule', fallback=False))
        self.ui_setup.enable_elastic_tables.setChecked(config.config.getboolean('antidetection', 'enable_elastic_tables', fallback=False))

        apply_translations(self.ui_setup, self.current_language)

    def save_setup(self):
        config = get_config()
        control_value = self.ui_setup.comboBox_vm.currentData()
        if control_value is None:
            control_value = self.ui_setup.comboBox_vm.currentText()

        language_value = self.ui_setup.comboBox_language.currentData()
        if language_value is None:
            language_value = self.current_language

        config.config.set('main', 'control', control_value)
        config.config.set('main', 'montecarlo_timeout', self.ui_setup.comboBox_2.currentText())
        config.config.set('main', 'login', self.ui_setup.login.text())
        config.config.set('main', 'password', self.ui_setup.password.text())
        config.config.set('main', 'language', normalize_language(language_value))

        if not config.config.has_section('antidetection'):
            config.config.add_section('antidetection')
        config.config.set('antidetection', 'enable_human_sleeps', str(int(self.ui_setup.enable_human_sleeps.isChecked())))
        config.config.set('antidetection', 'enable_fatigue', str(int(self.ui_setup.enable_fatigue.isChecked())))
        config.config.set('antidetection', 'enable_tilt', str(int(self.ui_setup.enable_tilt.isChecked())))
        config.config.set('antidetection', 'enable_info_gathering', str(int(self.ui_setup.enable_info_gathering.isChecked())))
        config.config.set('antidetection', 'enable_background_noise', str(int(self.ui_setup.enable_background_noise.isChecked())))
        config.config.set('antidetection', 'enable_bathroom_breaks', str(int(self.ui_setup.enable_bathroom_breaks.isChecked())))
        config.config.set('antidetection', 'enable_missclicks', str(int(self.ui_setup.enable_missclicks.isChecked())))
        config.config.set('antidetection', 'enable_scrolling', str(int(self.ui_setup.enable_scrolling.isChecked())))
        config.config.set('antidetection', 'enable_schedule', str(int(self.ui_setup.enable_schedule.isChecked())))
        config.config.set('antidetection', 'enable_elastic_tables', str(int(self.ui_setup.enable_elastic_tables.isChecked())))

        config.update_file()
        self.current_language = normalize_language(language_value)
        self._retranslate_open_windows()
        self.ui_setup.close()

    def _retranslate_open_windows(self):
        apply_translations(self.ui, self.current_language)
        self.ui.button_table_setup.setText("Room Manager")
        self.ui.button_table_setup.setToolTip("Create, validate, sync and roll back room presets")
        self._refresh_runtime_mode_selector()

        if self.current_status_text is not None:
            self.ui.status.setText(translate_text(self.current_status_text, self.current_language))
        if self.current_decision_text is not None:
            self.ui.last_decision.setText(translate_text(self.current_decision_text, self.current_language))

        for attr_name in ('ui_analyser', 'ui_editor', 'genetic_algorithm_form', 'ui_setup_table'):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                apply_translations(widget, self.current_language)
        if getattr(self, 'room_manager_dock', None) is not None:
            self.room_manager_dock.set_language(self.current_language)

        if self.ui_analyser is not None:
            self._retranslate_analyser_combos()

    def update_strategy_analyser(self, l, p):
        number_of_games = int(l.get_game_count(self.ui_analyser.combobox_strategy.currentText(),
                                               self.ui_analyser.my_computer_only.isChecked()))
        total_return = l.get_strategy_return(self.ui_analyser.combobox_strategy.currentText(), 999999,
                                             self.ui_analyser.my_computer_only.isChecked())

        try:
            winnings_per_bb_100 = total_return / p.selected_strategy['bigBlind'] / number_of_games * 100
        except ZeroDivisionError:
            winnings_per_bb_100 = 0

        self.ui_analyser.lcdNumber_2.display(number_of_games)
        self.ui_analyser.lcdNumber.display(winnings_per_bb_100)
        self.gui_fundschange.drawfigure(self.ui_analyser.my_computer_only.isChecked())
        self.strategy_analyser_update_plots(l, p)
        self.strategy_analyser_update_table(l)

    def strategy_analyser_update_plots(self, l, p):
        p_name = str(self.ui_analyser.combobox_strategy.currentText())
        game_stage = str(self._combo_value(self.ui_analyser.combobox_gamestage))
        decision = str(self._combo_value(self.ui_analyser.combobox_actiontype))

        self.gui_histogram.drawfigure(p_name, game_stage, decision, l)
        self.gui_bar2.drawfigure(l,
                                 self.ui_analyser.combobox_strategy.currentText(),
                                 self._combo_value(self.ui_analyser.combobox_gamestage),
                                 self._combo_value(self.ui_analyser.combobox_actiontype),
                                 self.ui_analyser.show_rounds.isChecked(),
                                 self.ui_analyser.my_computer_only.isChecked())

        p.read_strategy(p_name)

        call_or_bet = 'Bet' if decision[0] == 'B' else 'Call'

        max_value = float(p.selected_strategy['initialFunds'])
        if game_stage == 'All':
            game_stage = 'PreFlop'
        min_equity = float(p.selected_strategy[game_stage + 'Min' + call_or_bet + 'Equity'])
        max_equity = float(
            p.selected_strategy['PreFlopMaxBetEquity']) if game_stage == 'PreFlop' and call_or_bet == 'Bet' else 1
        power = float(p.selected_strategy[game_stage + call_or_bet + 'Power'])
        max_X = .95 if game_stage == "PreFlop" else 1

        self.gui_scatterplot.drawfigure(p_name, game_stage, decision, l,
                                        float(p.selected_strategy['smallBlind']),
                                        float(p.selected_strategy['bigBlind']),
                                        max_value,
                                        min_equity,
                                        max_X,
                                        max_equity,
                                        power)

    def strategy_analyser_update_table(self, l):
        p_name = str(self.ui_analyser.combobox_strategy.currentText())
        df = l.get_worst_games(p_name)
        if not df.empty:
            model = PandasModel(df)
            self.ui_analyser.tableView.setModel(model)

    def update_strategy_editor_sliders(self, strategy_name):
        self.strategy_handler.read_strategy(strategy_name)
        for key, value in self.strategy_items_with_multipliers.items():
            func = getattr(self.ui_editor, key)
            func.setValue(100)
            v = int(self.strategy_handler.selected_strategy[key] * value)
            func.setValue(v)
            # print (key)

        self.ui_editor.pushButton_save_current_strategy.setEnabled(False)
        try:
            if self.strategy_handler.selected_strategy['computername'] == COMPUTER_NAME or \
                    COMPUTER_NAME == 'NICOLAS-ASUS' or COMPUTER_NAME == 'Home-PC-ND':
                self.ui_editor.pushButton_save_current_strategy.setEnabled(True)
        except Exception as e:
            pass

        self.ui_editor.use_relative_equity.setChecked(self.strategy_handler.selected_strategy['use_relative_equity'])
        self.ui_editor.use_pot_multiples.setChecked(self.strategy_handler.selected_strategy['use_pot_multiples'])
        self.ui_editor.opponent_raised_without_initiative_flop.setChecked(
            self.strategy_handler.selected_strategy['opponent_raised_without_initiative_flop'])
        self.ui_editor.opponent_raised_without_initiative_turn.setChecked(
            self.strategy_handler.selected_strategy['opponent_raised_without_initiative_turn'])
        self.ui_editor.opponent_raised_without_initiative_river.setChecked(
            self.strategy_handler.selected_strategy['opponent_raised_without_initiative_river'])
        self.ui_editor.differentiate_reverse_sheet.setChecked(
            self.strategy_handler.selected_strategy['differentiate_reverse_sheet'])
        self.ui_editor.range_of_range.setChecked(
            self.strategy_handler.selected_strategy['range_of_range'])
        self.ui_editor.preflop_override.setChecked(self.strategy_handler.selected_strategy['preflop_override'])
        self.ui_editor.gather_player_names.setChecked(self.strategy_handler.selected_strategy['gather_player_names'])

        self.ui_editor.collusion.setChecked(self.strategy_handler.selected_strategy['collusion'])
        self.ui_editor.flop_betting_condidion_1.setChecked(
            self.strategy_handler.selected_strategy['flop_betting_condidion_1'])
        self.ui_editor.turn_betting_condidion_1.setChecked(
            self.strategy_handler.selected_strategy['turn_betting_condidion_1'])
        self.ui_editor.river_betting_condidion_1.setChecked(
            self.strategy_handler.selected_strategy['river_betting_condidion_1'])
        self.ui_editor.flop_bluffing_condidion_1.setChecked(
            self.strategy_handler.selected_strategy['flop_bluffing_condidion_1'])
        self.ui_editor.turn_bluffing_condidion_1.setChecked(
            self.strategy_handler.selected_strategy['turn_bluffing_condidion_1'])
        self.ui_editor.turn_bluffing_condidion_2.setChecked(
            self.strategy_handler.selected_strategy['turn_bluffing_condidion_2'])
        self.ui_editor.river_bluffing_condidion_1.setChecked(
            self.strategy_handler.selected_strategy['river_bluffing_condidion_1'])
        self.ui_editor.river_bluffing_condidion_2.setChecked(
            self.strategy_handler.selected_strategy['river_bluffing_condidion_2'])

        self.update_strategy_editor_graphs(strategy_name)

    def update_strategy_editor_graphs(self, strategy_name):
        strategy_dict = self.update_dictionary(strategy_name)

        try:
            self.curveplot_preflop.update_lines(float(strategy_dict['PreFlopCallPower']),
                                                float(strategy_dict['PreFlopBetPower']),
                                                float(strategy_dict['PreFlopMinCallEquity']),
                                                float(strategy_dict['PreFlopMinBetEquity']),
                                                float(strategy_dict['smallBlind']),
                                                float(strategy_dict['bigBlind']),
                                                float(strategy_dict['initialFunds']),
                                                float(strategy_dict['initialFunds2']),
                                                1,
                                                0.85,
                                                float(strategy_dict['PreFlopMaxBetEquity']))

            self.curveplot_flop.update_lines(float(strategy_dict['FlopCallPower']),
                                             float(strategy_dict['FlopBetPower']),
                                             float(strategy_dict['FlopMinCallEquity']),
                                             float(strategy_dict['FlopMinBetEquity']),
                                             float(strategy_dict['smallBlind']),
                                             float(strategy_dict['bigBlind']),
                                             float(strategy_dict['initialFunds']),
                                             float(strategy_dict['initialFunds2']),
                                             1,
                                             1,
                                             1)

            self.curveplot_turn.update_lines(float(strategy_dict['TurnCallPower']),
                                             float(strategy_dict['TurnBetPower']),
                                             float(strategy_dict['TurnMinCallEquity']),
                                             float(strategy_dict['TurnMinBetEquity']),
                                             float(strategy_dict['smallBlind']),
                                             float(strategy_dict['bigBlind']),
                                             float(strategy_dict['initialFunds']),
                                             float(strategy_dict['initialFunds2']),
                                             1,
                                             1,
                                             1)

            self.curveplot_river.update_lines(float(strategy_dict['RiverCallPower']),
                                              float(strategy_dict['RiverBetPower']),
                                              float(strategy_dict['RiverMinCallEquity']),
                                              float(strategy_dict['RiverMinBetEquity']),
                                              float(strategy_dict['smallBlind']),
                                              float(strategy_dict['bigBlind']),
                                              float(strategy_dict['initialFunds']),
                                              float(strategy_dict['initialFunds2']),
                                              1,
                                              1,
                                              1)
        except:
            print("retry")

    def update_dictionary(self, name):
        self.strategy_dict = self.p_edited.selected_strategy
        for key, value in self.strategy_items_with_multipliers.items():
            func = getattr(self.ui_editor, key)
            self.strategy_dict[key] = func.value() / value
        self.strategy_dict['Strategy'] = name
        self.strategy_dict['computername'] = COMPUTER_NAME

        self.strategy_dict['use_relative_equity'] = int(self.ui_editor.use_relative_equity.isChecked())
        self.strategy_dict['use_pot_multiples'] = int(self.ui_editor.use_pot_multiples.isChecked())

        self.strategy_dict['opponent_raised_without_initiative_flop'] = int(
            self.ui_editor.opponent_raised_without_initiative_flop.isChecked())
        self.strategy_dict['opponent_raised_without_initiative_turn'] = int(
            self.ui_editor.opponent_raised_without_initiative_turn.isChecked())
        self.strategy_dict['opponent_raised_without_initiative_river'] = int(
            self.ui_editor.opponent_raised_without_initiative_river.isChecked())

        self.strategy_dict['differentiate_reverse_sheet'] = int(self.ui_editor.differentiate_reverse_sheet.isChecked())
        self.strategy_dict['preflop_override'] = int(self.ui_editor.preflop_override.isChecked())
        self.strategy_dict['range_of_range'] = int(self.ui_editor.range_of_range.isChecked())
        self.strategy_dict['gather_player_names'] = int(self.ui_editor.gather_player_names.isChecked())

        self.strategy_dict['collusion'] = int(self.ui_editor.collusion.isChecked())

        self.strategy_dict['flop_betting_condidion_1'] = int(self.ui_editor.flop_betting_condidion_1.isChecked())
        self.strategy_dict['turn_betting_condidion_1'] = int(self.ui_editor.turn_betting_condidion_1.isChecked())
        self.strategy_dict['river_betting_condidion_1'] = int(self.ui_editor.river_betting_condidion_1.isChecked())
        self.strategy_dict['flop_bluffing_condidion_1'] = int(self.ui_editor.flop_bluffing_condidion_1.isChecked())
        self.strategy_dict['turn_bluffing_condidion_1'] = int(self.ui_editor.turn_bluffing_condidion_1.isChecked())
        self.strategy_dict['turn_bluffing_condidion_2'] = int(self.ui_editor.turn_bluffing_condidion_2.isChecked())
        self.strategy_dict['river_bluffing_condidion_1'] = int(self.ui_editor.river_bluffing_condidion_1.isChecked())
        self.strategy_dict['river_bluffing_condidion_2'] = int(self.ui_editor.river_bluffing_condidion_2.isChecked())

        return self.strategy_dict

    def save_strategy(self, name, update):
        if (name != "" and name not in self.playable_list) or update:
            strategy_dict = self.update_dictionary(name)
            if update:
                success = self.p_edited.update_strategy(strategy_dict)
            else:
                success = self.p_edited.save_strategy(strategy_dict)
                self.ui_editor.Strategy.insertItem(0, name)
                idx = len(self.p_edited.get_playable_strategy_list())
                self.ui_editor.Strategy.setCurrentIndex(0)
                self.ui.comboBox_current_strategy.insertItem(0, name)
            msg = QMessageBox()
            # msg.setIcon(QMessageBox.information())
            if success:
                msg.setText(translate_text("Saved", self.current_language))
            else:
                msg.setText(translate_text("To save strategies you need to purchase a subscription", self.current_language))
                open_payment_link()
            msg.setWindowTitle(translate_text("Strategy editor", self.current_language))
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            retval = msg.exec()
            self.logger.info("Strategy saved successfully")

        else:
            msg = QMessageBox()
            msg.setText(translate_text("There has been a problem and the strategy is not saved. Check if the name is already taken.", self.current_language))
            msg.setWindowTitle(translate_text("Strategy editor", self.current_language))
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            retval = msg.exec()
            self.logger.warning("Strategy not saved")

    def recommendation_pop_up(self, mouse_target):
            msg = QMessageBox()
            msg.setText(translate_text(f"Execute the {mouse_target} and then press OK to continue", self.current_language))
            msg.setWindowTitle(translate_text(f"Recommendation: {mouse_target}", self.current_language))
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            retval = msg.exec()
