#!/bin/bash

# Configure the folder to analyze and number of items to show
TARGET_DIR="../instance/users"
NUM_ITEMS="${1:-10}"

echo "=== TOP $NUM_ITEMS LARGEST FOLDERS in $TARGET_DIR ==="
echo "Size | Folder Path"
echo "-----+------------------------------------------"
du -h -d 1 "$TARGET_DIR" 2>/dev/null | sort -hr | head -$NUM_ITEMS

echo ""
echo "=== TOP $NUM_ITEMS OLDEST UNCHANGED FOLDERS in $TARGET_DIR ==="
echo "Last Modified | Size | Folder Path"
echo "--------------+------+------------------------------------------"
total_kb=0
find "$TARGET_DIR" -type d -mindepth 1 -maxdepth 1 2>/dev/null | while read dir; do
    size=$(du -sh "$dir" 2>/dev/null | cut -f1)
    size_kb=$(du -sk "$dir" 2>/dev/null | cut -f1)
    modified=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$dir")
    echo "$modified|$size|$dir|$size_kb"
done | sort | head -$NUM_ITEMS | tee /tmp/oldest_folders.tmp | column -t -s '|' | cut -d'|' -f1-3

echo ""
echo "=== TOTAL SIZE OF TOP $NUM_ITEMS OLDEST FOLDERS ==="
total_kb=$(awk -F'|' '{sum += $4} END {print sum}' /tmp/oldest_folders.tmp)
total_mb=$((total_kb / 1024))
total_gb=$(echo "scale=2; $total_kb / 1024 / 1024" | bc)
echo "Total: ${total_mb} MB (${total_gb} GB)"
rm -f /tmp/oldest_folders.tmp
