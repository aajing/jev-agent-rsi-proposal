import json
import sys
from .cli import main

try:
    raise SystemExit(main())
except Exception as exc:
    # Do not leak private task text through exception representations/tracebacks.
    print(json.dumps({"status":"unscored", "error_type":type(exc).__name__,
        "message":"Command did not complete; no score was produced."}), file=sys.stderr)
    raise SystemExit(1)
