import base64
import io
import json
import logging

import pandas as pd
import requests
from PIL import Image
from requests.exceptions import JSONDecodeError

from poker.tools.helper import COMPUTER_NAME, get_config, get_dir
from poker.tools.room_manager import RemotePresetSync, get_preset_repository, read_room_manager_settings
from poker.tools.singleton import Singleton

TABLES_COLLECTION = 'tables'

log = logging.getLogger(__name__)


class MongoManager(metaclass=Singleton):
    """Compatibility wrapper around the new local preset repository and legacy API."""

    def __init__(self):
        self.login = ''
        self.password = ''
        self.url = ''
        self.remote_sync = None
        self.repository = get_preset_repository()
        self.last_runtime_resolution = None
        self.refresh_configuration()

    def refresh_configuration(self):
        config = get_config()
        self.login = config.config.get('main', 'login', fallback='guest')
        self.password = config.config.get('main', 'password', fallback='guest')
        self.url = config.config.get('main', 'db', fallback='').rstrip('/') + '/'
        self.remote_sync = RemotePresetSync(self.url, self.login, self.password) if self.url.strip('/') else None
        self.repository = get_preset_repository(self.remote_sync)
        self.repository.remote_sync = self.remote_sync
        self.repository.refresh_ai_provider(settings=read_room_manager_settings())
        return self.repository

    def save_image(self, table_name, label, image):
        loaded = Image.open(io.BytesIO(image))
        self.repository.update_table_image(table_name, label, loaded)

    def update_table_image(self, pil_image, label, table_name):
        self.repository.update_table_image(table_name, label, pil_image)
        log.info("Preset image updated for %s/%s", table_name, label)
        return True

    def update_state(self, state, label, table_name):
        self.repository.update_state(table_name, label, state)
        log.info("Preset state updated for %s/%s", table_name, label)
        return True

    def update_tensorflow_model(self, table_name: str, hdf5_file: bytes, model_str: str, class_mapping: str):
        self.repository.update_tensorflow_model(table_name, hdf5_file, model_str, class_mapping)
        return True

    def load_table_nn_weights(self, table_name: str):
        log.info("Loading neural network weights for %s...", table_name)
        weights = self.repository.load_table_nn_weights(table_name)
        if weights is None:
            try:
                weights_str = requests.post(self.url + "get_tensorflow_weights", params={'table_name': table_name}).json()
                weights = base64.b64decode(weights_str)
            except Exception as exc:
                log.error("No trained neural network found for %s. %s", table_name, exc)
                return

        with open(get_dir('codebase') + '/loaded_model.h5', 'wb') as fh:
            fh.write(weights)
        log.info("Neural network weights ready")

    def load_table_image(self, image_name, table_name):
        return self.repository.load_table_image(table_name, image_name)

    def get_table(self, table_name):
        try:
            return self.repository.get_table(table_name, prefer_draft=True)
        except IndexError as exc:
            raise RuntimeError("No table found for given name.") from exc
        except JSONDecodeError as exc:
            raise RuntimeError(
                "JSONDecodeError: Most likely this table has using neural network enabled"
                "but no neural network has been trained yet. Either train a neural network"
                "for this table, or untick the use neural network checkbox for the given table."
            ) from exc

    def get_runtime_table(self, table_name, screenshot=None):
        table_dict, resolution = self.repository.get_runtime_table(table_name, screenshot=screenshot)
        self.last_runtime_resolution = resolution
        return table_dict

    def get_last_runtime_resolution(self):
        return self.last_runtime_resolution

    def get_table_owner(self, table_name):
        owner = self.repository.get_table_owner(table_name)
        if owner is not None:
            return owner
        return requests.post(self.url + "get_table_owner", params={'table_name': table_name}).json()

    def get_available_tables(self, computer_name):
        return self.repository.get_available_tables(computer_name)

    def increment_plays(self, table_name):
        try:
            requests.post(self.url + "increment_plays", params={'table_name': table_name})
        except Exception as exc:
            log.debug("Unable to increment remote play counter for %s: %s", table_name, exc)

    def get_rounds(self, game_id):
        output = requests.post(self.url + "get_rounds", params={'game_id': game_id}).json()
        return output

    def create_new_table(self, table_name):
        return self.repository.create_new_table(table_name, owner=COMPUTER_NAME)

    def create_new_table_from_old(self, table_name, old_table_name):
        return self.repository.create_new_table_from_old(table_name, old_table_name, owner=COMPUTER_NAME)

    def save_coordinates(self, table_name, label, coordinates_dict):
        self.repository.save_coordinates(table_name, label, coordinates_dict)
        log.info("Coordinates saved")

    def delete_table(self, table_name, owner):
        _ = owner
        self.repository.delete_table(table_name)

    def update_table_identity(self, table_name, identity_updates):
        return self.repository.update_identity(table_name, identity_updates)

    def publish_table_draft(self, table_name, screenshots=None):
        return self.repository.publish_draft(table_name, screenshots=screenshots or [])

    def list_table_versions(self, table_name):
        return self.repository.list_versions(table_name)

    def compare_table_versions(self, table_name, version_a, version_b):
        return self.repository.compare_versions(table_name, version_a, version_b)

    def rollback_table_version(self, table_name, version_id):
        return self.repository.rollback_to_version(table_name, version_id)

    def sync_table_to_remote(self, table_name):
        return self.repository.sync_to_remote(table_name)

    def import_remote_table(self, table_name):
        return self.repository.import_remote_table(table_name)

    def validate_table(self, table_name, screenshots=None, use_draft=True):
        return self.repository.validate(table_name, live_screenshots=screenshots or [], use_draft=use_draft)

    def observe_runtime_table(self, table_name, screenshot):
        return self.repository.observe_runtime_drift(table_name, screenshot)

    def get_room_manager_summary(self, table_name):
        self.refresh_configuration()
        return self.repository.get_room_summary(table_name)

    def suggest_table_with_ai(self, table_name, screenshots=None):
        self.refresh_configuration()
        return self.repository.suggest(table_name, screenshots=screenshots or [])

    def get_top_strategies(self):
        response = requests.post(self.url + "get_top_strategies").json()
        return pd.DataFrame(json.loads(response))
