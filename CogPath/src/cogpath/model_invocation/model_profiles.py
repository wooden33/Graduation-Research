"""Load optional per-model LiteLLM settings from model_profiles.ini."""

import configparser
import json
import os
from pathlib import Path


PROFILE_FILE = Path(__file__).resolve().parents[1] / "model_profiles.ini"
LOCAL_PROFILE_FILE = Path(__file__).resolve().parents[1] / "model_profiles.local.ini"


def _read_profiles():
    parser = configparser.ConfigParser(interpolation=None)
    # The local file is read second so credentials and machine-specific settings
    # can override the shareable profile without entering version control.
    parser.read([str(PROFILE_FILE), str(LOCAL_PROFILE_FILE)], encoding="utf-8")
    return parser


def load_model_profile(model: str) -> dict:
    """Return LiteLLM parameters configured for ``model``.

    Credentials can be supplied as ``api_key`` in the ignored local profile or
    referenced by ``api_key_env``. The ``litellm_params`` value is a JSON object
    merged into standard ``litellm.completion`` arguments.
    """
    parser = _read_profiles()
    if not parser.has_section(model):
        return {}

    section = parser[model]
    profile = {}
    if section.get("model"):
        profile["model"] = section["model"].strip()
    if section.get("api_base"):
        profile["api_base"] = section["api_base"].strip()

    api_key_env = section.get("api_key_env", "").strip()
    api_key = section.get("api_key", "").strip()
    if api_key:
        profile["api_key"] = api_key
    if api_key_env:
        env_api_key = os.environ.get(api_key_env)
        if not api_key and not env_api_key:
            raise ValueError(
                "Model {!r} requires environment variable {}.".format(
                    model, api_key_env
                )
            )
        if not api_key:
            profile["api_key"] = env_api_key

    raw_params = section.get("litellm_params", "").strip()
    if raw_params:
        params = json.loads(raw_params)
        if not isinstance(params, dict):
            raise ValueError(
                "litellm_params for model {!r} must be a JSON object.".format(model)
            )
        profile.update(params)

    return profile
