#!/bin/sh
# Does the search's improvement over the incumbent survive opponents it does not model?
PY=~/.venvs/tuppi-ai/bin/python
for opp in partner_aware_v1 legacy_heuristic_port_v1 reactive_contract_v1; do
  $PY -m tuppi_ai.evaluate --checkpoint "search:runs/bc_small.pt:w=64:dd=6:show=1" --opponent $opp --deals 128 --seed tuppi-ai-transfer-v1 --workers 6 --out runs/transfer_search_$opp.json > /dev/null 2>&1
  $PY -m tuppi_ai.evaluate --checkpoint profile:partner_aware_lead_v2 --opponent $opp --deals 128 --seed tuppi-ai-transfer-v1 --workers 6 --out runs/transfer_incumbent_$opp.json > /dev/null 2>&1
done
