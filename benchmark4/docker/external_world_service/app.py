"""Independent configurable What-only HTTP service. No history API."""
import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import yaml

PROFILES = {'T0_history', 'A_static', 'B_irrelevant', 'C_changed'}
QUERY_KEYS = {'amount', 'date', 'channel', 'protocol'}
FORBIDDEN = {'rule', 'key_premise', 'scope_boundary', 'dead_end', 'history', 'why', 'gold'}


def check_profiles(profiles):
    if set(profiles) != PROFILES:
        raise ValueError('four world profiles required')
    def check(value):
        if isinstance(value, dict):
            if FORBIDDEN.intersection(str(k).lower() for k in value):
                raise ValueError('historical metadata in public response')
            for v in value.values(): check(v)
        elif isinstance(value, list):
            for v in value: check(v)
    for config in profiles.values():
        check(config['default'])
        seen = set()
        for route in config['routes']:
            if not set(route['match']) <= QUERY_KEYS:
                raise ValueError('unsupported routing field')
            key = json.dumps(route['match'], sort_keys=True)
            if key in seen: raise ValueError('duplicate route')
            seen.add(key)
            check(route['response'])


class World:
    def __init__(self, profiles):
        check_profiles(profiles)
        self.profiles = deepcopy(profiles)

    def snapshot(self, profile, query):
        if not set(query) <= QUERY_KEYS:
            raise ValueError('unsupported query field')
        config = self.profiles[profile]
        for route in config['routes']:
            if all(query.get(k) == v for k, v in route['match'].items()):
                return deepcopy(route['response'])
        return deepcopy(config['default'])


def serve(world, host, port, active_profile=None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                if self.path != '/snapshot': raise ValueError('unknown endpoint')
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 4096: raise ValueError('request size')
                data = json.loads(self.rfile.read(size))
                profile = data.get('world_profile', active_profile)
                if active_profile and profile != active_profile: raise ValueError('inactive profile')
                body = world.snapshot(profile, data.get('query', {}))
                status = 200
            except (ValueError, KeyError, TypeError):
                body, status = {'error': 'invalid request'}, 400
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='world_profile.yaml')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8080)
    p.add_argument('--profile', choices=sorted(PROFILES))
    args = p.parse_args()
    with open(args.config) as f: world = World(yaml.safe_load(f)['profiles'])
    serve(world, args.host, args.port, args.profile)
