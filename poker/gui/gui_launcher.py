from PyQt6 import uic
from PyQt6.QtWidgets import QMainWindow, QDialog
import os

from poker.tools.helper import get_dir


def _ui_path(filename):
    return os.path.join(get_dir('codebase'), 'gui', 'ui', filename)


class AnalyserForm(QMainWindow):

    def __init__(self):
        super(AnalyserForm, self).__init__()
        uic.loadUi(_ui_path('analyser_form.ui'), self)

        self.show()


class TableSetupForm(QMainWindow):

    def __init__(self):
        super(TableSetupForm, self).__init__()
        uic.loadUi(_ui_path('table_setup_form.ui'), self)

        self.show()


class SetupForm(QMainWindow):
    def __init__(self):
        super(SetupForm, self).__init__()
        uic.loadUi(_ui_path('setup_form.ui'), self)

        self.show()


class StrategyEditorForm(QMainWindow):

    def __init__(self):
        super(StrategyEditorForm, self).__init__()
        uic.loadUi(_ui_path('strategy_manager_form.ui'), self)

        self.show()


class GeneticAlgo(QDialog):

    def __init__(self):
        super(GeneticAlgo, self).__init__()
        uic.loadUi(_ui_path('genetic_algo_form.ui'), self)
        self.show()


class MainForm(QMainWindow):

    def __init__(self):
        super(MainForm, self).__init__()
        uic.loadUi(_ui_path('main_form.ui'), self)

        self.show()


class UiPokerbot(QMainWindow):

    def __init__(self):
        super(UiPokerbot, self).__init__()
        uic.loadUi(_ui_path('main_form.ui'), self)

        self.show()
