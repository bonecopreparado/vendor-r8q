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
    parser.add_argument('--baseline', type=Path,
                        help='Reviewed verbose neverallow multiset; gate new findings while retaining NOT_BOOT_READY status')
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
    result = module.main()
    if args.baseline is None:
        return result
    # The isolated bundle retains the raw compiler failure and its original
    # report. Only this separate regression check may accept known diagnostics;
    # init compilation, serialized version and capability checks stay required.
    gate_spec = importlib.util.spec_from_file_location(
        'policy_baseline_gate', Path(__file__).resolve().parents[1]/'ci-r8q/tools/check_policy_baseline.py')
    gate = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(gate)
    return gate.check_report(args.output_dir.resolve()/'result.json', args.baseline.resolve())


if __name__ == '__main__': raise SystemExit(main())
