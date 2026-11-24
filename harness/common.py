"""Small shared data/CLI helpers; no providers or network imports."""
import argparse
import json
from pathlib import Path
import yaml


def read(path):
    path = Path(path)
    return yaml.safe_load(path.read_text()) if path.suffix in {'.yaml', '.yml'} else json.loads(path.read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def selector(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--dataset', required=True, type=Path)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--case')
    g.add_argument('--all', action='store_true')
    return p


def seed_paths(dataset):
    """The deliberately empty recipe template is never a dataset case."""
    return [p for p in sorted((Path(dataset)/'seeds').glob('*.yaml')) if p.name != 'seed_template.yaml']


def seeds(args):
    paths = seed_paths(args.dataset)
    values = [read(p) for p in paths]
    if args.case:
        values = [s for s in values if s.get('id') == args.case]
    if not values:
        raise ValueError('No matching seed; templates are not datasets')
    ids = [s['id'] for s in values]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate case id')
    if any(not i or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in i) for i in ids):
        raise ValueError('unsafe case id')
    return values
