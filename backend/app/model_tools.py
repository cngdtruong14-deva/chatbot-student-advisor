"""Offline, non-deserializing inspection. Never activate based on this check alone."""
import argparse
import json
from advisor_core.ml_boundary import verify_bundle_files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("--schema", default="/contracts/model_manifest.schema.json")
    args = parser.parse_args()
    result = verify_bundle_files(args.bundle, args.schema)
    print(json.dumps(result, indent=2))
