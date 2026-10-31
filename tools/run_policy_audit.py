"""Run the pinned, reviewed isolated policy audit bundle. Never touches ROM images."""
from pathlib import Path
import argparse
import importlib.util
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secilc', type=Path, required=True)
    parser.add_argument('--inputs-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--cap-checker', type=Path)
    parser.add_argument('--genfs', choices=['none','202504','202604','202704'], default='none')
    args = parser.parse_args()
    root = args.inputs_dir.resolve()
    spec = importlib.util.spec_from_file_location('isolated_policy_audit', root/'compile_bundle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    checker = args.cap_checker or args.secilc.resolve().parent/'check-policy-caps'
    sys.argv = ['compile_bundle.py', '--secilc', str(args.secilc.resolve()),
                '--cap-checker', str(checker.resolve()), '--out', str(args.output_dir.resolve()),
                '--genfs', args.genfs]
    return module.main()


if __name__ == '__main__': raise SystemExit(main())
