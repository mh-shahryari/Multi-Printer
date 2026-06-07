#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
from config.settings import DB_PATH
from core.database import get_all_logs

# Get recent PRINT type logs
logs = get_all_logs(limit=50)
print_logs = [log for log in logs if log['type'] == 'PRINT']

print(f"Found {len(print_logs)} PRINT logs (out of {len(logs)} total)")
if print_logs:
    print("\nRecent PRINT logs:")
    print(json.dumps(print_logs[:3], ensure_ascii=False, indent=2))
else:
    print("No PRINT logs found")
    print("\nAll types:", set(log['type'] for log in logs))
