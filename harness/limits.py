"""One source of execution defaults, with no model/daemon access."""
from .common import read
from pathlib import Path
import hashlib
CONFIG_PATH=Path(__file__).with_name('config.yaml')
CONFIG_FREEZE=read(CONFIG_PATH.with_name('config.freeze.json'))
if hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()!=CONFIG_FREEZE['sha256']:
    raise ValueError('common runtime config changed without updating the reviewed freeze record')
CONFIG=read(CONFIG_PATH)
INPUT_CAP=CONFIG['stage2']['max_input_tokens']
MAX_TURNS=CONFIG['stage2']['max_turns']
STALL_LIMIT=CONFIG['stage2']['stall_limit']
EXPLORATION_LIMIT=CONFIG['stage2']['exploration_limit']

TRIAL_TOKEN_LIMIT=CONFIG['execution']['trial_token_limit']
NO_EDIT_WARN=CONFIG['execution']['no_edit_warn']
NO_EDIT_STOP=CONFIG['execution']['no_edit_stop']
