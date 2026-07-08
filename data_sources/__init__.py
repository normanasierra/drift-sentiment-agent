"""External data sources for analysis: Yahoo, Hyperliquid, email newsletters, Schwab/ToS.

Each module is independent and degrades gracefully (returns empty / raises a
clear error) when a credential or network is missing, so one dead source never
takes down the daily report.
"""
