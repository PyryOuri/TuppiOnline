"""Research-only NOLO evidence; never a production policy or server dependency.

Private synthetic fixtures and DealState belong to the research harness only.
Policy-facing entry points must receive only PlayerObservation, never hidden
hands, fixture records, or full-information oracle results.
"""
