#!/usr/bin/env bash
# EXPLORATION TOOL (not product code). Show start-up timing and warnings from the HA log.
C="${1:-integration-homeassistant-1}"
L="$(docker logs "$C" 2>&1 | sed -E 's/\x1b\[[0-9;]*m//g')"
echo "--- start-up lines"
echo "$L" | grep -iE "Home Assistant initialized|Setup of domain home_keeper|Setting up home_keeper|home_keeper.*took|Waiting on integrations" | head -14
echo "--- first and last home_keeper line"
echo "$L" | grep -E "home_keeper" | sed -n '1p;$p' | cut -c1-160
echo "--- warnings and errors (count by first 110 chars)"
echo "$L" | grep -E " (WARNING|ERROR) " | grep -vE "metno|http.ban|We found a custom integration|py.warnings" | cut -c1-200 | sed -E 's/^[0-9-]+ [0-9:.]+ //' | cut -c1-110 | sort | uniq -c | sort -rn | head -20
echo "--- slow / blocking"
echo "$L" | grep -iE "took longer|blocking|Detected blocking|Update of .* is taking|slow|Executor|Timer" | cut -c1-240 | head -10
echo "--- coordinator refresh time (seconds): count, max, average"
echo "$L" | grep -oE "Finished fetching Home Keeper data in [0-9.]+" | awk '{v=$NF; n++; s+=v; if(v>m)m=v} END{printf "count=%d max=%.3f avg=%.3f\n", n, m, (n?s/n:0)}'
echo "--- store save debug lines (if any)"
echo "$L" | grep -iE "saving|saved|Writing" | grep -i home_keeper | cut -c1-160 | tail -3
