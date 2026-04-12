from __future__ import annotations

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QMessageBox

from poker.gui.i18n import translate_text
from poker.tools.helper import COMPUTER_NAME, get_config
from poker.tools.mongo_manager import MongoManager
from poker.tools.room_manager import read_room_manager_settings, update_room_manager_settings
from poker.tools.screen_operations import take_screenshot


class RoomManagerWidget(QtWidgets.QWidget):
    def __init__(
        self,
        parent=None,
        language: str = "en",
        open_table_setup_callback=None,
        refresh_table_selector_callback=None,
    ):
        super().__init__(parent)
        self.current_language = language
        self.open_table_setup_callback = open_table_setup_callback
        self.refresh_table_selector_callback = refresh_table_selector_callback
        self.mongo = MongoManager()
        self.main_table_selector = None
        self._syncing_table = False
        self.latest_summary = None
        self._build_ui()
        self.load_settings()
        self.refresh_tables()
        self.retranslate()

    def _t(self, text: str) -> str:
        return translate_text(text, self.current_language)

    def _build_ui(self):
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        root_layout.addWidget(scroll)

        content = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout(content)
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        self.content_layout.setSpacing(10)
        scroll.setWidget(content)

        self.title_label = QtWidgets.QLabel()
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.content_layout.addWidget(self.title_label)

        table_row = QtWidgets.QHBoxLayout()
        self.table_label = QtWidgets.QLabel()
        self.table_combo = QtWidgets.QComboBox()
        self.table_combo.currentTextChanged.connect(self._sync_to_main_selector)
        self.refresh_button = QtWidgets.QPushButton()
        self.refresh_button.clicked.connect(self.refresh_tables)
        table_row.addWidget(self.table_label)
        table_row.addWidget(self.table_combo, 1)
        table_row.addWidget(self.refresh_button)
        self.content_layout.addLayout(table_row)

        self.summary_group = QtWidgets.QGroupBox()
        summary_layout = QtWidgets.QFormLayout(self.summary_group)
        self.identity_value = QtWidgets.QLabel()
        self.lifecycle_value = QtWidgets.QLabel()
        self.validation_value = QtWidgets.QLabel()
        self.ai_status_value = QtWidgets.QLabel()
        self.identity_value.setWordWrap(True)
        self.lifecycle_value.setWordWrap(True)
        self.validation_value.setWordWrap(True)
        self.ai_status_value.setWordWrap(True)
        summary_layout.addRow("", self.identity_value)
        summary_layout.addRow("", self.lifecycle_value)
        summary_layout.addRow("", self.validation_value)
        summary_layout.addRow("", self.ai_status_value)
        self.content_layout.addWidget(self.summary_group)

        self.actions_group = QtWidgets.QGroupBox()
        actions_layout = QtWidgets.QGridLayout(self.actions_group)
        self.wizard_button = QtWidgets.QPushButton()
        self.wizard_button.clicked.connect(lambda: self._open_table_setup(auto_wizard=True))
        self.setup_editor_button = QtWidgets.QPushButton()
        self.setup_editor_button.clicked.connect(lambda: self._open_table_setup(auto_wizard=False))
        self.validate_button = QtWidgets.QPushButton()
        self.validate_button.clicked.connect(self.validate_selected_preset)
        self.publish_button = QtWidgets.QPushButton()
        self.publish_button.clicked.connect(self.publish_selected_preset)
        self.drift_button = QtWidgets.QPushButton()
        self.drift_button.clicked.connect(self.run_drift_check)
        self.sync_button = QtWidgets.QPushButton()
        self.sync_button.clicked.connect(self.sync_selected_preset)
        self.import_button = QtWidgets.QPushButton()
        self.import_button.clicked.connect(self.import_remote_preset)
        buttons = [
            self.wizard_button,
            self.setup_editor_button,
            self.validate_button,
            self.publish_button,
            self.drift_button,
            self.sync_button,
            self.import_button,
        ]
        for index, button in enumerate(buttons):
            actions_layout.addWidget(button, index // 2, index % 2)
        self.content_layout.addWidget(self.actions_group)

        self.versions_group = QtWidgets.QGroupBox()
        versions_layout = QtWidgets.QVBoxLayout(self.versions_group)
        self.version_tree = QtWidgets.QTreeWidget()
        self.version_tree.setRootIsDecorated(False)
        self.version_tree.setAlternatingRowColors(True)
        self.version_tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        versions_layout.addWidget(self.version_tree)
        version_actions = QtWidgets.QHBoxLayout()
        self.rollback_button = QtWidgets.QPushButton()
        self.rollback_button.clicked.connect(self.rollback_selected_version)
        self.compare_button = QtWidgets.QPushButton()
        self.compare_button.clicked.connect(self.compare_selected_versions)
        version_actions.addWidget(self.rollback_button)
        version_actions.addWidget(self.compare_button)
        versions_layout.addLayout(version_actions)
        self.content_layout.addWidget(self.versions_group)

        self.ai_group = QtWidgets.QGroupBox()
        ai_layout = QtWidgets.QFormLayout(self.ai_group)
        self.drift_watcher_checkbox = QtWidgets.QCheckBox()
        self.drift_interval_spin = QtWidgets.QSpinBox()
        self.drift_interval_spin.setRange(30, 7200)
        self.ai_mode_combo = QtWidgets.QComboBox()
        self.ai_mode_combo.addItem("Local only", "local")
        self.ai_mode_combo.addItem("Cloud assist", "cloud")
        self.ai_provider_combo = QtWidgets.QComboBox()
        self.ai_provider_combo.addItem("OpenAI-compatible", "openai_compatible")
        self.ai_provider_combo.addItem("Generic JSON", "generic_json")
        self.ai_endpoint_edit = QtWidgets.QLineEdit()
        self.ai_model_edit = QtWidgets.QLineEdit()
        self.ai_api_key_env_edit = QtWidgets.QLineEdit()
        self.ai_api_key_edit = QtWidgets.QLineEdit()
        self.ai_api_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.ai_extra_headers_edit = QtWidgets.QLineEdit()
        self.ai_timeout_spin = QtWidgets.QSpinBox()
        self.ai_timeout_spin.setRange(5, 300)
        self.ai_max_images_spin = QtWidgets.QSpinBox()
        self.ai_max_images_spin.setRange(1, 10)
        self.ai_allow_full_checkbox = QtWidgets.QCheckBox()
        self.save_ai_settings_button = QtWidgets.QPushButton()
        self.save_ai_settings_button.clicked.connect(self.save_room_manager_settings)
        self.ask_ai_button = QtWidgets.QPushButton()
        self.ask_ai_button.clicked.connect(self.request_ai_suggestion)
        ai_layout.addRow("", self.drift_watcher_checkbox)
        ai_layout.addRow("", self.drift_interval_spin)
        ai_layout.addRow("", self.ai_mode_combo)
        ai_layout.addRow("", self.ai_provider_combo)
        ai_layout.addRow("", self.ai_endpoint_edit)
        ai_layout.addRow("", self.ai_model_edit)
        ai_layout.addRow("", self.ai_api_key_env_edit)
        ai_layout.addRow("", self.ai_api_key_edit)
        ai_layout.addRow("", self.ai_extra_headers_edit)
        ai_layout.addRow("", self.ai_timeout_spin)
        ai_layout.addRow("", self.ai_max_images_spin)
        ai_layout.addRow("", self.ai_allow_full_checkbox)
        ai_button_row = QtWidgets.QHBoxLayout()
        ai_button_row.addWidget(self.save_ai_settings_button)
        ai_button_row.addWidget(self.ask_ai_button)
        ai_layout.addRow("", ai_button_row)
        self.content_layout.addWidget(self.ai_group)

        self.details_group = QtWidgets.QGroupBox()
        details_layout = QtWidgets.QVBoxLayout(self.details_group)
        self.details_box = QtWidgets.QPlainTextEdit()
        self.details_box.setReadOnly(True)
        details_layout.addWidget(self.details_box)
        self.content_layout.addWidget(self.details_group, 1)

    def bind_main_table_selector(self, combo_box):
        self.main_table_selector = combo_box
        combo_box.currentTextChanged.connect(self._sync_from_main_selector)
        self._sync_from_main_selector(combo_box.currentText())

    def set_language(self, language: str):
        self.current_language = language
        self.retranslate()
        self.refresh_current_table()

    @staticmethod
    def _set_form_label(form_layout, field, text):
        label = form_layout.labelForField(field)
        if label is not None:
            label.setText(text)

    def retranslate(self):
        self.title_label.setText(self._t("Room Manager"))
        self.table_label.setText(self._t("Preset"))
        self.refresh_button.setText(self._t("Refresh"))
        self.summary_group.setTitle(self._t("Preset Summary"))
        summary_layout = self.summary_group.layout()
        summary_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self._set_form_label(summary_layout, self.identity_value, self._t("Identity"))
        self._set_form_label(summary_layout, self.lifecycle_value, self._t("Lifecycle"))
        self._set_form_label(summary_layout, self.validation_value, self._t("Validation"))
        self._set_form_label(summary_layout, self.ai_status_value, self._t("AI Assist"))

        self.actions_group.setTitle(self._t("Actions"))
        self.wizard_button.setText(self._t("Wizard"))
        self.setup_editor_button.setText(self._t("Open Setup Editor"))
        self.validate_button.setText(self._t("Validate"))
        self.publish_button.setText(self._t("Publish"))
        self.drift_button.setText(self._t("Run Drift Check"))
        self.sync_button.setText(self._t("Sync Remote"))
        self.import_button.setText(self._t("Import Remote"))

        self.versions_group.setTitle(self._t("Version History"))
        self.version_tree.setHeaderLabels(
            [
                self._t("Version"),
                self._t("Status"),
                self._t("Score"),
                self._t("Published"),
                self._t("Active"),
                self._t("Candidate"),
            ]
        )
        self.rollback_button.setText(self._t("Rollback Selected"))
        self.compare_button.setText(self._t("Compare Selected"))

        self.ai_group.setTitle(self._t("Monitoring And AI"))
        self.ai_mode_combo.setItemText(0, self._t("Local only"))
        self.ai_mode_combo.setItemText(1, self._t("Cloud assist"))
        self.ai_provider_combo.setItemText(0, self._t("OpenAI-compatible"))
        self.ai_provider_combo.setItemText(1, self._t("Generic JSON"))
        ai_layout = self.ai_group.layout()
        self._set_form_label(ai_layout, self.drift_watcher_checkbox, self._t("Enable drift watcher"))
        self._set_form_label(ai_layout, self.drift_interval_spin, self._t("Drift interval (s)"))
        self._set_form_label(ai_layout, self.ai_mode_combo, self._t("AI mode"))
        self._set_form_label(ai_layout, self.ai_provider_combo, self._t("Provider type"))
        self._set_form_label(ai_layout, self.ai_endpoint_edit, self._t("API endpoint"))
        self._set_form_label(ai_layout, self.ai_model_edit, self._t("Model"))
        self._set_form_label(ai_layout, self.ai_api_key_env_edit, self._t("API key env var"))
        self._set_form_label(ai_layout, self.ai_api_key_edit, self._t("API key override"))
        self._set_form_label(ai_layout, self.ai_extra_headers_edit, self._t("Extra headers JSON"))
        self._set_form_label(ai_layout, self.ai_timeout_spin, self._t("Timeout (s)"))
        self._set_form_label(ai_layout, self.ai_max_images_spin, self._t("Max images"))
        self._set_form_label(ai_layout, self.ai_allow_full_checkbox, self._t("Allow full screenshot"))
        self.save_ai_settings_button.setText(self._t("Save Settings"))
        self.ask_ai_button.setText(self._t("Ask AI"))

        self.details_group.setTitle(self._t("Details"))

    def load_settings(self):
        settings = read_room_manager_settings()
        self.drift_watcher_checkbox.setChecked(settings["enable_drift_watcher"])
        self.drift_interval_spin.setValue(settings["drift_check_interval_seconds"])
        self._set_combo_data(self.ai_mode_combo, settings["ai_mode"])
        self._set_combo_data(self.ai_provider_combo, settings["ai_provider_type"])
        self.ai_endpoint_edit.setText(settings["ai_endpoint"])
        self.ai_model_edit.setText(settings["ai_model"])
        self.ai_api_key_env_edit.setText(settings["ai_api_key_env"])
        self.ai_api_key_edit.setText(settings["ai_api_key"])
        self.ai_extra_headers_edit.setText(settings["ai_extra_headers_json"])
        self.ai_timeout_spin.setValue(settings["ai_timeout_seconds"])
        self.ai_max_images_spin.setValue(settings["ai_max_images"])
        self.ai_allow_full_checkbox.setChecked(settings["ai_allow_full_screenshot"])

    def save_room_manager_settings(self):
        settings = update_room_manager_settings(
            {
                "enable_drift_watcher": self.drift_watcher_checkbox.isChecked(),
                "drift_check_interval_seconds": self.drift_interval_spin.value(),
                "ai_mode": self.ai_mode_combo.currentData(),
                "ai_cloud_opt_in": self.ai_mode_combo.currentData() == "cloud",
                "ai_provider_type": self.ai_provider_combo.currentData(),
                "ai_endpoint": self.ai_endpoint_edit.text().strip(),
                "ai_model": self.ai_model_edit.text().strip(),
                "ai_api_key_env": self.ai_api_key_env_edit.text().strip(),
                "ai_api_key": self.ai_api_key_edit.text().strip(),
                "ai_extra_headers_json": self.ai_extra_headers_edit.text().strip(),
                "ai_timeout_seconds": self.ai_timeout_spin.value(),
                "ai_max_images": self.ai_max_images_spin.value(),
                "ai_allow_full_screenshot": self.ai_allow_full_checkbox.isChecked(),
            }
        )
        self.mongo.refresh_configuration()
        self.load_settings()
        self._write_details(
            self._t("Room Manager settings saved."),
            [
                f"AI mode: {settings['ai_mode']}",
                f"Provider: {settings['ai_provider_type']}",
                f"Endpoint: {settings['ai_endpoint'] or 'not set'}",
                f"Drift watcher: {'enabled' if settings['enable_drift_watcher'] else 'disabled'}",
            ],
        )
        self.refresh_current_table()

    def refresh_tables(self):
        self.mongo.refresh_configuration()
        current = self.table_combo.currentText() or (
            self.main_table_selector.currentText() if self.main_table_selector is not None else ""
        )
        tables = self.mongo.get_available_tables(COMPUTER_NAME)
        self._syncing_table = True
        self.table_combo.clear()
        self.table_combo.addItems(tables)
        if current in tables:
            self.table_combo.setCurrentText(current)
        elif tables:
            self.table_combo.setCurrentIndex(0)
        self._syncing_table = False
        self.refresh_current_table()

    def refresh_current_table(self):
        table_name = self.selected_table_name()
        if not table_name:
            self.latest_summary = None
            self.identity_value.setText("")
            self.lifecycle_value.setText("")
            self.validation_value.setText("")
            self.ai_status_value.setText("")
            self.version_tree.clear()
            return
        try:
            summary = self.mongo.get_room_manager_summary(table_name)
        except Exception as exc:
            self._write_details(self._t("Unable to load room summary."), [str(exc)])
            return
        self.latest_summary = summary
        current = summary.get("current") or {}
        family = summary.get("family") or {}
        identity = current.get("identity", {})
        lifecycle = current.get("lifecycle", {})
        validation = current.get("validation", {})
        ai_assist = current.get("ai_assist", {})
        identity_lines = [
            f"{identity.get('network', '-')}",
            f"site={identity.get('site', '-')}",
            f"variant={identity.get('variant', '-')}",
            f"theme={identity.get('theme', '-')}",
            f"max_players={identity.get('max_players', '-')}",
            f"{identity.get('cash_or_tournament', '-')}/{identity.get('real_or_play', '-')}",
        ]
        self.identity_value.setText(" | ".join(identity_lines))
        self.lifecycle_value.setText(
            " | ".join(
                [
                    f"draft={'yes' if summary.get('draft') else 'no'}",
                    f"active={family.get('active_version_id') or '-'}",
                    f"candidate={family.get('candidate_version_id') or '-'}",
                    f"current={lifecycle.get('status', '-')}",
                ]
            )
        )
        self.validation_value.setText(
            " | ".join(
                [
                    f"status={validation.get('status', '-')}",
                    f"golden={validation.get('golden_pass_rate', 0):.2f}",
                    f"live={validation.get('live_pass_rate', 0):.2f}",
                    f"anchors={validation.get('critical_anchor_score', 0):.2f}",
                ]
            )
        )
        last_suggestion = ai_assist.get("last_suggestion", {})
        provider = last_suggestion.get("provider", current.get("ai_assist", {}).get("provider", "local"))
        notes = last_suggestion.get("notes", [])
        self.ai_status_value.setText(f"{provider} | {notes[0] if notes else self._t('No recent AI suggestion.')}")
        self._populate_versions(summary.get("versions", []))
        details_lines = []
        if notes:
            details_lines.extend(notes)
        request_summary = last_suggestion.get("request_summary")
        if request_summary:
            details_lines.append(str(request_summary))
        self._write_details(self._t("Room summary loaded."), details_lines or [self._t("Ready.")], append=False)

    def _populate_versions(self, versions):
        selected_ids = {item.data(0, QtCore.Qt.ItemDataRole.UserRole) for item in self.version_tree.selectedItems()}
        self.version_tree.clear()
        for version in versions:
            item = QtWidgets.QTreeWidgetItem(
                [
                    version.get("version_id", ""),
                    version.get("status", ""),
                    f"{float(version.get('score') or 0):.2f}",
                    version.get("published_at", "") or "",
                    "yes" if version.get("is_active") else "",
                    "yes" if version.get("is_candidate") else "",
                ]
            )
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, version.get("version_id"))
            self.version_tree.addTopLevelItem(item)
            if version.get("version_id") in selected_ids:
                item.setSelected(True)
        for column in range(self.version_tree.columnCount()):
            self.version_tree.resizeColumnToContents(column)

    def selected_table_name(self) -> str:
        return self.table_combo.currentText().strip()

    def _sync_from_main_selector(self, table_name: str):
        if self._syncing_table:
            return
        if table_name and self.table_combo.currentText() != table_name:
            self._syncing_table = True
            if self.table_combo.findText(table_name) < 0:
                self.table_combo.addItem(table_name)
            self.table_combo.setCurrentText(table_name)
            self._syncing_table = False
        self.refresh_current_table()

    def _sync_to_main_selector(self, table_name: str):
        if self._syncing_table:
            return
        if self.main_table_selector is not None and table_name and self.main_table_selector.currentText() != table_name:
            self.main_table_selector.setCurrentText(table_name)
        self.refresh_current_table()

    @staticmethod
    def _set_combo_data(combo_box, value):
        index = combo_box.findData(value)
        if index >= 0:
            combo_box.setCurrentIndex(index)

    def _capture_live_screenshots(self, count: int = 1):
        screenshots = []
        config = get_config()
        control_mode = config.config.get("main", "control", fallback="Direct mouse control")
        for _ in range(max(1, count)):
            try:
                screenshots.append(take_screenshot(virtual_box=control_mode != "Direct mouse control"))
            except Exception as exc:
                self._write_details(self._t("Screenshot capture failed."), [str(exc)])
                break
        return screenshots

    def _open_table_setup(self, auto_wizard: bool):
        if self.open_table_setup_callback is not None:
            self.open_table_setup_callback(open_wizard=auto_wizard)

    def validate_selected_preset(self):
        table_name = self.selected_table_name()
        if not table_name:
            return
        screenshots = self._capture_live_screenshots()
        if not screenshots:
            return
        result = self.mongo.validate_table(table_name, screenshots=screenshots, use_draft=True)
        self._write_details(
            self._t("Validation completed."),
            [
                f"status={result.status}",
                f"golden={result.golden_pass_rate:.2f}",
                f"live={result.live_pass_rate:.2f}",
                f"anchors={result.critical_anchor_score:.2f}",
            ] + list(result.issues),
        )
        self.refresh_current_table()

    def publish_selected_preset(self):
        table_name = self.selected_table_name()
        if not table_name:
            return
        screenshots = self._capture_live_screenshots()
        if not screenshots:
            return
        try:
            result = self.mongo.publish_table_draft(table_name, screenshots=screenshots)
            lines = [
                f"version={result['version_id']}",
                f"status={result['status']}",
                f"active={result['active_version_id']}",
            ]
            self._write_details(self._t("Draft published."), lines)
        except Exception as exc:
            self._write_details(self._t("Publish failed."), [str(exc)])
        self.refresh_current_table()

    def run_drift_check(self):
        table_name = self.selected_table_name()
        if not table_name:
            return
        screenshots = self._capture_live_screenshots(1)
        if not screenshots:
            return
        screenshot = screenshots[0]
        result = self.mongo.observe_runtime_table(table_name, screenshot)
        self._write_details(
            self._t("Drift check completed."),
            [
                f"status={result.status}",
                f"score={result.score:.2f}",
                f"version={result.version_id or '-'}",
            ] + list(result.diagnostics),
        )
        self.refresh_current_table()

    def sync_selected_preset(self):
        table_name = self.selected_table_name()
        if not table_name:
            return
        try:
            synced = self.mongo.sync_table_to_remote(table_name)
        except Exception as exc:
            self._write_details(self._t("Remote sync failed."), [str(exc)])
            return
        self._write_details(
            self._t("Remote sync completed." if synced else "Remote sync failed."),
            [table_name],
        )

    def import_remote_preset(self):
        table_name = self.selected_table_name()
        if not table_name:
            return
        try:
            imported = self.mongo.import_remote_table(table_name)
        except Exception as exc:
            self._write_details(self._t("Remote import failed."), [str(exc)])
            return
        self._write_details(
            self._t("Remote import completed." if imported else "Remote import failed."),
            [table_name],
        )
        self.refresh_current_table()

    def request_ai_suggestion(self):
        table_name = self.selected_table_name()
        if not table_name:
            return
        screenshots = self._capture_live_screenshots()
        if not screenshots:
            return
        suggestion = self.mongo.suggest_table_with_ai(table_name, screenshots=screenshots)
        lines = []
        if suggestion.get("site_guess"):
            lines.append(f"site_guess={suggestion['site_guess']}")
        if suggestion.get("base_preset"):
            lines.append(f"base_preset={suggestion['base_preset']}")
        lines.extend(suggestion.get("notes", []))
        if suggestion.get("request_summary"):
            lines.append(str(suggestion["request_summary"]))
        self._write_details(self._t("AI suggestion completed."), lines or [self._t("No suggestion returned.")])
        self.refresh_current_table()

    def rollback_selected_version(self):
        table_name = self.selected_table_name()
        version_id = self._single_selected_version()
        if not table_name or not version_id:
            self._write_details(self._t("Select exactly one version to roll back to."), [])
            return
        answer = QMessageBox.question(
            self,
            self._t("Confirm Rollback"),
            self._t(f"Reactivate version {version_id} for {table_name}?"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.mongo.rollback_table_version(table_name, version_id)
        self._write_details(self._t("Rollback completed."), [f"{table_name} -> {version_id}"])
        self.refresh_current_table()

    def compare_selected_versions(self):
        table_name = self.selected_table_name()
        if not table_name:
            return
        selected = [item.data(0, QtCore.Qt.ItemDataRole.UserRole) for item in self.version_tree.selectedItems()]
        family = (self.latest_summary or {}).get("family", {})
        if len(selected) == 1 and family.get("active_version_id") and family.get("active_version_id") != selected[0]:
            selected.append(family["active_version_id"])
        if len(selected) != 2:
            self._write_details(self._t("Select one or two versions to compare."), [])
            return
        diff = self.mongo.compare_table_versions(table_name, selected[0], selected[1])
        self._write_details(
            self._t("Version comparison completed."),
            [
                f"{diff['version_a']} vs {diff['version_b']}",
                f"changed_keys={', '.join(diff.get('changed_keys', [])) or '-'}",
                f"changed_assets={', '.join(diff.get('changed_assets', [])) or '-'}",
            ],
        )

    def _single_selected_version(self):
        selected = [item.data(0, QtCore.Qt.ItemDataRole.UserRole) for item in self.version_tree.selectedItems()]
        if len(selected) == 1:
            return selected[0]
        return None

    def _write_details(self, title: str, lines, append: bool = False):
        content = title
        if lines:
            content += "\n" + "\n".join(str(line) for line in lines)
        if append and self.details_box.toPlainText():
            content = self.details_box.toPlainText() + "\n\n" + content
        self.details_box.setPlainText(content)


class RoomManagerDock(QtWidgets.QDockWidget):
    def __init__(
        self,
        parent=None,
        language: str = "en",
        open_table_setup_callback=None,
        refresh_table_selector_callback=None,
    ):
        super().__init__("Room Manager", parent)
        self.setObjectName("room_manager_dock")
        self.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.widget = RoomManagerWidget(
            parent=self,
            language=language,
            open_table_setup_callback=open_table_setup_callback,
            refresh_table_selector_callback=refresh_table_selector_callback,
        )
        self.setWidget(self.widget)

    def bind_main_table_selector(self, combo_box):
        self.widget.bind_main_table_selector(combo_box)

    def refresh(self):
        self.widget.refresh_tables()

    def set_language(self, language: str):
        self.widget.set_language(language)
        self.setWindowTitle(translate_text("Room Manager", language))
