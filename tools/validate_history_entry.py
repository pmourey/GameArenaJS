#!/usr/bin/env python3
"""
Validate a JSON file against the provided JSON Schema.
Usage:
  python3 tools/validate_history_entry.py <history_entry.json> <schema.json>

If jsonschema is not installed, the script will try to install it using pip --user.
"""
import sys
import json
import subprocess
import os


def ensure_jsonschema():
    try:
        import jsonschema
        return jsonschema
    except Exception:
        print('jsonschema not found, installing via pip (--user)...')
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--user', 'jsonschema'])
        try:
            import importlib
            jsonschema = importlib.import_module('jsonschema')
            return jsonschema
        except Exception as e:
            print('Failed to import jsonschema after installation:', e)
            raise


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    if len(sys.argv) != 3:
        print('Usage: python3 tools/validate_history_entry.py <history_entry.json> <schema.json>')
        sys.exit(2)
    entry_path = sys.argv[1]
    schema_path = sys.argv[2]
    if not os.path.isfile(entry_path):
        print('history_entry file not found:', entry_path)
        sys.exit(1)
    if not os.path.isfile(schema_path):
        print('schema file not found:', schema_path)
        sys.exit(1)

    jsonschema = ensure_jsonschema()
    entry = load_json(entry_path)
    schema = load_json(schema_path)

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(entry), key=lambda e: e.path)
    if not errors:
        print('VALID: history_entry conforms to schema')
        sys.exit(0)
    else:
        print('INVALID: found', len(errors), 'error(s)')
        for e in errors:
            path = ''.join(['[{}]'.format(p) for p in e.path])
            print('-', path or '<root>', e.message)
        sys.exit(3)


if __name__ == '__main__':
    main()

