# Data audit experiment

This directory is temporary design/test space for the static-data audit.

Run:

```bash
.venv/bin/python _experiments/data_audit/audit_static_data.py
```

The script reads Python AST only. It does not import engine/compiler modules and does not change production artifacts.

Outputs:

- `current_static_data_audit.md`
- `current_static_data_audit.json`

