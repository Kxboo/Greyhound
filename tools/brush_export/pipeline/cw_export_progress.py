"""Best-effort atomic progress updates; telemetry must not abort geometry export."""
import json
import os
import time


def write_progress(path, data, attempts=6):
    temporary=path.with_suffix('.tmp')
    for attempt in range(attempts):
        try:
            temporary.write_text(json.dumps(data),encoding='utf-8')
            os.replace(temporary,path)
            return True
        except PermissionError:
            # Windows readers/scanners may briefly deny delete-sharing. Keep
            # the last complete JSON available, then try the next progress tick.
            if attempt+1<attempts:time.sleep(0.02*(attempt+1))
    return False
