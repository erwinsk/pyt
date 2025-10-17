modbus_logger_v3.1
==================

Modular Modbus RTU/TCP logger and GUI (PyQt5)
- GUI reads config.ini (read-only)
- CLI reads config.ini and runs polling loop
- Storage: CSV (append) and MySQL (open/insert/close per insert)
- Default storage: CSV in ./logs/

Run GUI:
    python3 main_gui.py

Run CLI:
    python3 main_cli.py
