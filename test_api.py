#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
from config.settings import DB_PATH
from core.database import get_all_logs

# Get recent logs
logs = get_all_logs(limit=3)

print("Recent logs:")
print(json.dumps(logs, ensure_ascii=False, indent=2))
